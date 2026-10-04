"""Allowlisted, explicit, ephemeral exports using synthetic uploaded rows."""
import csv
import io
import json
from dataclasses import replace

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.workbench.analysis import AnalysisResult
from cids.workbench.export import (export_document, serialize_export, neutralize_csv_string,
                                   RECORD_FIELDS, METADATA_FIELDS, CSV_FIELDS)
from cids.workbench.review import simulate_threshold
from test_workbench_analysis import PACK_ID, session, Upload, scoring
from test_workbench_review import sample
from test_workbench_contracts import valid_frame, payload


def result(records, data):
    return AnalysisResult(data.input_sha256, PACK_ID, records, ())


@pytest.mark.parametrize("binary,family", [(False, False), (True, False), (False, True), (True, True)])
def test_json_allowlists_provenance_original_and_review(binary, family):
    data, records = sample(binary, family)
    doc = export_document(data, result(records, data))
    encoded = serialize_export(doc)
    actual = json.loads(encoded, parse_constant=lambda _: pytest.fail("nonstandard JSON"))
    assert set(actual) == {*METADATA_FIELDS, "records"}
    assert actual["export_schema_version"] == "cids-review-export-v1"
    assert actual["input_sha256"] == data.input_sha256 and actual["model_pack_id"] == PACK_ID
    assert actual["provenance_type"] == "maintainer_final_v2"
    assert actual["record_count"] == 4 and actual["export_scope"] == "full_analysis"
    assert actual["simulation"] is None and actual["notices"]
    assert all(set(r) == set(RECORD_FIELDS) for r in actual["records"])
    assert "dur" not in actual["records"][0] and "top_contributions" not in encoded.decode()
    assert (actual["records"][0]["actual_binary_label"] is not None) == binary
    assert (actual["records"][0]["actual_family_label"] is not None) == family


def test_filtered_scope_preserves_sorted_original_indices_and_full_simulation_scope():
    data, records = sample()
    sim = simulate_threshold(data, records, .9)
    doc = export_document(data, result(records, data), scope="current_filtered_review", indices=[3, 1], order="score", simulation=sim)
    assert [r["record_id"] for r in doc["records"]] == ["d", "b"]
    assert [r["record_sequence"] for r in doc["records"]] == [4, 2]
    assert doc["record_count"] == 2 and doc["full_analysis_record_count"] == 4
    assert doc["exported_scope_metrics"]["record_count"] == 2
    assert doc["simulation"]["sample_scope"] == "full_current_uploaded_sample"
    assert doc["simulation"]["threshold"] == .9
    assert doc["simulation"]["alert_count"] == 0
    assert doc["records"][0]["simulated_binary_decision"] == 0
    assert doc["records"][0]["binary_prediction"] == "normal"
    assert doc["original_sample_metrics"]["counts"]["TP"] == 1
    # Full scope always preserves original sequence even with filtered inputs.
    assert export_document(data, result(records, data), indices=[3], order="score")["ordering"] == "sequence"


@pytest.mark.parametrize("text", ["=1+1", "+SUM(A1)", "-2+1", "@sum(A1)", "\ttext", "\rtext", " =1", "\n+1", "\u00a0@sum(A1)", "\x01-1", "\u200b=1", " \x01\ttext", "\n\rtext"])
def test_formula_initiators_behind_whitespace_and_controls(text):
    assert neutralize_csv_string(text) == "'" + text


def test_every_csv_string_cell_is_neutralized_with_quoting_and_typed_numerics():
    data, records = sample()
    unsafe = '=HYPERLINK("https://invalid", "x,y")\nnext'
    data.frame.loc[0, "id"] = unsafe
    records = (replace(records[0], record_id=unsafe), *records[1:])
    doc = export_document(data, result(records, data))
    doc["notices"] = [unsafe]
    encoded = serialize_export(doc, "CSV")
    rows = list(csv.DictReader(io.StringIO(encoded.decode(), newline="")))
    assert rows[0]["record_id"] == "'" + unsafe
    assert rows[0]["attack_model_score"] == "0.9"
    assert rows[0]["actual_binary_label"] == "1"
    assert rows[0]["record_sequence"] == "1"
    assert set(rows[0]) == set(CSV_FIELDS)
    # Standards-compliant JSON preserves IDs, without spreadsheet mutation.
    assert json.loads(serialize_export(doc))["records"][0]["record_id"] == unsafe


def test_json_undefined_metrics_are_null_and_nan_infinity_are_rejected():
    data, records = sample(True, False)
    data.frame["label"] = 0
    records = tuple(replace(r, binary_prediction="normal", queue_band="not_alerted", triage_family="not_alerted") for r in records)
    doc = export_document(data, result(records, data))
    assert json.loads(serialize_export(doc))["original_sample_metrics"]["metrics"]["recall"]["value"] is None
    for value in (float("nan"), float("inf")):
        doc["records"][0]["attack_model_score"] = value
        for format in ("JSON", "CSV"):
            with pytest.raises(ValueError):
                serialize_export(doc, format)


def test_empty_filtered_export_retains_metadata_and_unavailable_metrics():
    data, records = sample()
    doc = export_document(data, result(records, data), scope="current_filtered_review", indices=[])
    assert json.loads(serialize_export(doc))["records"] == []
    rows = list(csv.DictReader(io.StringIO(serialize_export(doc, "CSV").decode())))
    assert len(rows) == 1 and rows[0]["record_count"] == "0" and rows[0]["record_id"] == ""


@pytest.mark.parametrize("indices", [[0, 0], [-1], [4], [True]])
def test_invalid_scope_indices_rejected(indices):
    data, records = sample()
    with pytest.raises(ValueError):
        export_document(data, result(records, data), scope="current_filtered_review", indices=indices)


def test_mismatched_provenance_and_simulation_rejected():
    data, records = sample()
    with pytest.raises(ValueError, match="provenance"):
        export_document(data, replace(result(records, data), input_sha256="b" * 64))
    sim = simulate_threshold(data, records)
    with pytest.raises(ValueError, match="simulation"):
        export_document(data, result(records, data), simulation=replace(sim, decisions=(0,) * 4))


@pytest.mark.parametrize("transition", ["replace", "same_bytes_replace", "invalid", "remove", "pack", "clear", "failure", "reanalyze"])
def test_simulation_export_lifecycle_and_no_loading_on_derivatives(tmp_path, scoring, monkeypatch, transition):
    state = session(tmp_path)
    upload = Upload(payload(valid_frame(4).assign(label=[0, 1, 0, 1])))
    state.receive(upload)
    state.analyze()
    original = state.current_result()
    assert state.simulation is None and state.prepared_export is None
    state.simulate(.9)
    assert state.simulation.threshold == .9 and state.current_result() is original
    state.simulate()  # reset baseline
    assert state.simulation.threshold == .5
    state.prepare_export(include_simulation=True)
    assert state.prepared_export and scoring == ["load", "infer"]
    if transition == "replace":
        state.receive(Upload(payload(valid_frame(2)), "two"))
    elif transition == "same_bytes_replace":
        state.receive(Upload(upload.getvalue(), "two"))
    elif transition == "invalid":
        state.receive(Upload(b"bad", "two"))
    elif transition == "remove":
        state.receive(None)
    elif transition == "pack":
        state.bind(tmp_path, "b" * 64)
    elif transition == "clear":
        state.invalidate(reset_uploader=True)
    elif transition == "failure":
        from cids.workbench import inference
        def fail(*_):
            raise RuntimeError("private")
        monkeypatch.setattr(inference, "infer", fail)
        state.analyze()
    else:
        state.analyze()
    assert state.simulation is None and state.prepared_export is None and state.export_context is None


def test_derivative_changes_invalidate_prepared_bytes_and_sessions_are_isolated(tmp_path, scoring):
    first, second = session(tmp_path), session(tmp_path)
    first.receive(Upload(payload(valid_frame().assign(label=[0, 1]))))
    first.analyze()
    first.simulate()
    first.sync_export_context(("full",))
    first.prepare_export()
    first.sync_export_context(("full",))
    assert first.prepared_export
    first.sync_export_context(("filtered",))
    assert first.prepared_export is None
    first.prepare_export()
    first.simulate(.9)
    assert first.prepared_export is None
    assert second.simulation is None and second.prepared_export is None
    second.invalidate()
    assert first.simulation.threshold == .9 and scoring == ["load", "infer"]
