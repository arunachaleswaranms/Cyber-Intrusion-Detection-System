"""Explicit allowlisted in-memory exports; never accepts a destination path."""
from __future__ import annotations

import csv
import io
import json
import unicodedata

from cids.workbench.analysis import models_disagree
from cids.workbench.review import original_binary_metrics, review_rows, binary_metrics

EXPORT_SCHEMA_VERSION = "cids-review-export-v1"
PROVENANCE_TYPE = "maintainer_final_v2"
NOTICES = (
    "Local research results, separate from frozen benchmark evidence; scores are uncalibrated, not production risk.",
    "Uploaded-data provenance cannot be established from arbitrary feature rows alone. Do not use official-test rows or benchmark evidence for threshold selection.",
    "Undefined metrics are null when the documented denominator is zero; no ground truth is inferred.",
    "Clearing drops references; it is not secure memory erasure. Downstream tools may transform CSV safeguards.",
)
RECORD_FIELDS = (
    "record_sequence", "record_id", "event_time_utc", "binary_prediction", "attack_model_score",
    "family_prediction_raw", "family_model_score", "triage_family", "queue_band", "models_disagree",
    "explanation_status", "actual_binary_label", "binary_error", "actual_family_label", "family_error",
    "simulated_binary_decision",
)
METADATA_FIELDS = (
    "export_schema_version", "input_sha256", "model_pack_id", "provenance_type", "export_scope",
    "record_count", "full_analysis_record_count", "ordering", "notices", "original_sample_metrics",
    "exported_scope_metrics", "simulation",
)
CSV_FIELDS = (*METADATA_FIELDS, *RECORD_FIELDS)
FILENAMES = {"JSON": "cids-review.json", "CSV": "cids-review.csv"}
MIME_TYPES = {"JSON": "application/json", "CSV": "text/csv"}


def neutralize_csv_string(value: str) -> str:
    """Prefix formula initiators even behind Unicode whitespace/control chars.

    The original text is retained after an apostrophe. Numeric typed fields do
    not enter this routine. Tabs/CR anywhere in the leading prefix are unsafe.
    """
    offset = 0
    unsafe_control = False
    for char in value:
        if not (char.isspace() or unicodedata.category(char).startswith("C")):
            break
        unsafe_control = unsafe_control or char in "\t\r"
        offset += 1
    if unsafe_control or (offset < len(value) and value[offset] in "=+-@"):
        return "'" + value
    return value


def export_document(input_data, result, *, scope="full_analysis", indices=None, order="sequence", simulation=None):
    if result.input_sha256 != input_data.input_sha256 or any(r.model_pack_id != result.model_pack_id for r in result.records):
        raise ValueError("export provenance mismatch")
    rows = review_rows(input_data, result.records)
    if scope == "full_analysis":
        selected = list(range(len(result.records)))
        order = "sequence"
    elif scope == "current_filtered_review":
        if indices is None:
            raise ValueError("filtered export requires explicit indices")
        selected = list(indices)
        if len(set(selected)) != len(selected) or any(type(i) is not int or not 0 <= i < len(rows) for i in selected):
            raise ValueError("invalid export record indices")
    else:
        raise ValueError("unsupported export scope")
    if order not in ("sequence", "score", "timestamp"):
        raise ValueError("unsupported export ordering")
    if simulation is not None:
        from cids.workbench.review import simulate_threshold
        if simulation != simulate_threshold(input_data, result.records, simulation.threshold):
            raise ValueError("simulation does not match the current full sample")
    exported = []
    for i in selected:
        r = result.records[i]
        exported.append(dict(zip(RECORD_FIELDS, (
            i + 1, r.record_id, r.event_time_utc, r.binary_prediction, float(r.attack_model_score),
            r.family_prediction_raw, float(r.family_model_score), r.triage_family, r.queue_band,
            models_disagree(r), r.explanation_status, rows[i]["actual_binary_label"], rows[i]["binary_error"],
            rows[i]["actual_family_label"], rows[i]["family_error"],
            None if simulation is None else simulation.decisions[i],
        ))))
    scope_metrics = None
    if input_data.has_binary_labels:
        scope_metrics = binary_metrics((rows[i]["actual_binary_label"] for i in selected),
                                       (int(result.records[i].binary_prediction == "attack") for i in selected))
        scope_metrics["scope"] = scope
    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION, "input_sha256": result.input_sha256,
        "model_pack_id": result.model_pack_id, "provenance_type": PROVENANCE_TYPE,
        "export_scope": scope, "record_count": len(selected), "full_analysis_record_count": len(rows),
        "ordering": order, "notices": list(NOTICES),
        "original_sample_metrics": original_binary_metrics(input_data, result.records),
        "exported_scope_metrics": scope_metrics,
        "simulation": None if simulation is None else simulation.report(input_data), "records": exported,
    }


def serialize_export(document, format="JSON") -> bytes:
    # Strict JSON serialization also validates nested metric/score finiteness for CSV.
    encoded = json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2)
    if format == "JSON":
        return encoded.encode("utf-8")
    if format != "CSV":
        raise ValueError("unsupported export format")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_ALL)
    writer.writeheader()
    metadata = {key: document[key] for key in METADATA_FIELDS}
    # A zero-record filtered export still has one metadata-only row (count=0).
    for record in document["records"] or [{}]:
        row = {**metadata, **record}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            row[key] = neutralize_csv_string(value) if isinstance(value, str) else value
        writer.writerow(row)
    return stream.getvalue().encode("utf-8")
