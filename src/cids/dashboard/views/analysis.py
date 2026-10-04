"""Opt-in local analysis and bounded research review; no frozen metrics here."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict

import pandas as pd
import streamlit as st

from cids.datasets.unsw_nb15 import FEATURE_COLUMNS
from cids.datasets.unsw_nb15 import ATTACK_FAMILIES
from cids.workbench.review import (
    BASELINE_THRESHOLD, COMPARISON_RULE, BINARY_ERRORS, FAMILY_ERRORS,
    review_rows, review_indices, original_binary_metrics,
)
from cids.workbench.export import FILENAMES, MIME_TYPES
from cids.workbench.analysis import (
    AnalysisUnavailable, PAGE_ROWS, QUEUE_BANDS, models_disagree,
    preflight_binding,
)


def _bounded(value, limit=200):
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "… [truncated]"


def _warnings(warnings):
    if warnings:
        st.warning("Out-of-vocabulary categorical values found. The fitted OneHotEncoder uses handle_unknown='ignore': unknown categories become all-zero categorical indicators; preprocessing is unchanged.")
        st.dataframe(pd.DataFrame([asdict(w) for w in warnings]), hide_index=True)


def _record_row(record, index):
    row = {
        "Record sequence": index + 1,
        "Record ID": _bounded(record.record_id),
        "Binary prediction": record.binary_prediction,
        "Attack model score (uncalibrated)": record.attack_model_score,
        "Independent raw attack-family prediction": record.family_prediction_raw,
        "Family model score (uncalibrated)": record.family_model_score,
        "Triage family": record.triage_family,
        "Queue band": record.queue_band,
        "Models disagree (either direction)": models_disagree(record),
        "Model-pack ID": record.model_pack_id,
    }
    if record.event_time_utc is not None:
        row["Timestamp (UTC)"] = record.event_time_utc
    return row


def _sample_metrics(report, title):
    st.subheader(title)
    st.caption("Derived from the full current uploaded sample, separate from frozen benchmark evidence. Filters do not change these metrics.")
    st.dataframe(pd.DataFrame([report["counts"]]), hide_index=True)
    matrix = report["confusion_matrix"]
    st.dataframe(pd.DataFrame(matrix["values"], index=["Actual normal", "Actual attack"],
                              columns=["Predicted normal", "Predicted attack"]))
    st.dataframe(pd.DataFrame([{
        "Uploaded-sample metric": name,
        "Value": "Unavailable" if metric["value"] is None else f'{metric["value"]:.6f}',
        "Numerator": metric["numerator"], "Denominator": metric["denominator"],
        "Denominator definition": metric["denominator_definition"],
        "Explanation": metric["unavailable_reason"] or "Defined on this uploaded sample",
    } for name, metric in report["metrics"].items()]), hide_index=True)


def _labels(row, review):
    if review["actual_binary_label"] is not None:
        row.update({"Actual binary label": review["actual_binary_label"], "Binary review category": review["binary_error"]})
    if review["actual_family_label"] is not None:
        row.update({"Actual attack family": review["actual_family_label"], "Independent family review": review["family_error"]})
    return row


def _simulation(session, prefix):
    if not session.input_data.has_binary_labels:
        return
    st.subheader("Ephemeral, sample-specific threshold simulation")
    st.caption(f"Full current uploaded sample only. Baseline {BASELINE_THRESHOLD:.2f}: {COMPARISON_RULE}. The 0.90 queue boundary is a separate frozen display policy. Scores remain uncalibrated; this is not threshold selection or an optimal-threshold recommendation.")
    st.caption("The estimator uses raw logit > 0; its exact tie predicts normal. Simulation compares stored scores only, so floating-point rounding near 0.50 can differ from a raw-logit decision. Original predictions and review categories remain authoritative and unchanged.")
    st.caption("Do not upload official-test rows or use benchmark evidence for threshold selection. Uploaded-data provenance cannot be established from arbitrary feature rows alone.")
    threshold_key = prefix + "threshold"
    if threshold_key not in st.session_state:
        st.session_state[threshold_key] = BASELINE_THRESHOLD
    def reset():
        st.session_state[threshold_key] = BASELINE_THRESHOLD
        session.simulate(BASELINE_THRESHOLD)
    st.button("Reset simulation to baseline", on_click=reset)
    threshold = st.slider("Simulation attack-score threshold (uncalibrated)", 0.0, 1.0,
                          value=None, step=0.01, key=threshold_key)
    if session.simulation is None or session.simulation.threshold != threshold:
        session.simulate(threshold)
    report = session.simulation.report(session.input_data)
    st.metric("Simulated alerts — full uploaded sample", report["alert_count"])
    _sample_metrics(report["sample_metrics"], "Simulated uploaded-sample binary metrics")


def _export(session, indices, order, prefix):
    st.subheader("Explicit research export")
    st.caption("JSON is the default. Prepare only after choosing scope and format. Exports include prediction/review results and provenance; omit all raw features, model contents, filesystem paths and unrelated session data.")
    scope_label = st.selectbox("Export scope", ("Full analysis", "Current filtered review"), key=prefix + "export_scope")
    scope = "full_analysis" if scope_label == "Full analysis" else "current_filtered_review"
    format = st.selectbox("Export format", ("JSON", "CSV"), key=prefix + "export_format")
    include = False
    if session.simulation is not None:
        include = st.checkbox("Include ephemeral simulation in export", key=prefix + "export_simulation")
    context = (session.revision, scope, format, tuple(indices) if scope != "full_analysis" else (),
               order if scope != "full_analysis" else "sequence", include,
               session.simulation.threshold if include else None)
    session.sync_export_context(context)
    count = len(session.result.records) if scope == "full_analysis" else len(indices)
    st.caption(f"Export scope: {scope_label} · Records: {count:,}. Current filtered review includes all matching pages in review order.")
    if st.button("Prepare export", key=prefix + "prepare_export"):
        session.prepare_export(format=format, scope=scope, indices=indices, order=order,
                               include_simulation=include)
    if session.prepared_export is not None:
        st.download_button("Download prepared " + format, session.prepared_export,
                           file_name=FILENAMES[format], mime=MIME_TYPES[format],
                           key=prefix + str(context) + "download", on_click="ignore")


def render(session, repo_root, pack_id):
    st.title("Local CSV analysis")
    st.caption("Explicit local analysis • separate from frozen benchmark evidence")
    st.markdown("Scores are **model scores (uncalibrated)**. Queue bands organize research review; they do not measure threat severity or business risk. Independent model predictions are shown in both directions of disagreement.")
    st.caption("Uploaded bytes, validated features, predictions and prepared exports stay in this session's process memory. The application does not persist or log them. Clearing drops references; it does not securely erase process memory. Uploaded label and attack_cat independently enable measured binary and raw-family review.")
    st.button("Clear analysis", on_click=session.invalidate, kwargs={"reset_uploader": True})
    if st.get_option("client.disableDataExport") is not True:
        session.invalidate(reset_uploader=True)
        st.warning("Analysis unavailable: table data export must be disabled. Start from the repository root or pass --client.disableDataExport true.")
        return
    try:
        verified = preflight_binding(repo_root, pack_id)
    except AnalysisUnavailable as exc:
        if session.input_data is not None or session.result is not None:
            session.invalidate(reset_uploader=True)
        st.warning(str(exc))
        return

    manifest = verified.manifest
    st.caption(f"Configured model-pack ID: {manifest['model_pack_id']} · Provenance: {manifest['provenance_type']}")
    with st.expander("Registered model-pack provenance"):
        st.json({key: manifest[key] for key in ("model_pack_id", "provenance_type", "created_at_utc", "runtime", "contracts", "artifacts", "creation_config_sha256")})

    st.caption("One uncompressed UTF-8 CSV • maximum 10 MiB and 50,000 data rows • exactly 42 features • optional id, event_time, label, attack_cat")
    with st.expander("Required feature columns"):
        st.code(",".join(FEATURE_COLUMNS), language=None)
    upload = st.file_uploader("Feature CSV", type=["csv"], accept_multiple_files=False,
                              max_upload_size=10, key=f"analysis_upload_{session.uploader_epoch}")
    session.receive(upload)
    if session.error:
        st.error(session.error)
    if session.input_data is not None:
        st.caption(f"Validated rows: {len(session.input_data.frame):,} · Input SHA-256: {session.input_data.input_sha256}")
    warning_panel = st.container()
    analyzed = st.button("Analyze CSV", disabled=session.input_data is None, type="primary")
    if analyzed:
        with st.spinner("Verifying registered models and analyzing CSV…"):
            with warning_panel:
                session.analyze(before_scoring=_warnings)
        if session.error:
            st.error(session.error)
    result = session.current_result()
    if result is None:
        st.info("Select a valid CSV and choose Analyze CSV. Ordinary page views and filter changes do not load models or score records.")
        return
    # Completed results are reusable only with matching input digest and pack ID.
    if not analyzed:
        _warnings(result.warnings)
    st.subheader("Research review queue")
    st.caption(f"Analysis input SHA-256: {result.input_sha256} · Model-pack ID: {result.model_pack_id}")
    records = result.records
    bands = Counter(r.queue_band for r in records)
    predictions = Counter(r.binary_prediction for r in records)
    st.dataframe(pd.DataFrame([{"Queue band": b, "Records": bands[b]} for b in QUEUE_BANDS]), hide_index=True)
    st.dataframe(pd.DataFrame([{"Binary prediction": p, "Records": predictions[p]} for p in ("normal", "attack")]), hide_index=True)
    st.metric("Models disagree (either direction)", sum(models_disagree(r) for r in records))
    st.caption("The policy's model_disagreement band contains binary attack + raw family normal only. Binary normal + raw attack family is also a disagreement, but remains not_alerted. Binary decisions and queue policy are unchanged.")

    prefix = f"analysis_view_{session.revision}_"
    rows = review_rows(session.input_data, records)
    chosen_bands = st.multiselect("Queue bands", QUEUE_BANDS, default=QUEUE_BANDS, key=prefix + "bands")
    chosen_predictions = st.multiselect("Binary predictions", ("normal", "attack"), default=("normal", "attack"), key=prefix + "predictions")
    disagree_only = st.checkbox("Only model disagreements (either direction)", key=prefix + "disagree")
    score_range = st.select_slider("Attack-score review range (uncalibrated)",
                                   options=[i / 100 for i in range(101)], value=(0.0, 1.0), key=prefix + "scores")
    label_filters = {}
    families = tuple(sorted(ATTACK_FAMILIES))
    label_filters["predicted_family"] = st.multiselect("Independent predicted attack families", families, default=families, key=prefix + "predicted_family")
    if session.input_data.has_binary_labels:
        label_filters["actual_binary"] = st.multiselect("Actual binary labels", (0, 1), default=(0, 1), key=prefix + "actual_binary")
        label_filters["binary_errors"] = st.multiselect("Binary review categories", BINARY_ERRORS, default=BINARY_ERRORS, key=prefix + "binary_errors")
    if session.input_data.has_family_labels:
        label_filters["actual_family"] = st.multiselect("Actual attack families", families, default=families, key=prefix + "actual_family")
        label_filters["family_errors"] = st.multiselect("Independent family review categories", FAMILY_ERRORS, default=FAMILY_ERRORS, key=prefix + "family_errors")
    has_times = session.input_data.has_event_time
    orders = ["Record sequence", "Attack model score (uncalibrated), descending"]
    if has_times:
        orders.append("Timestamp (UTC), ascending")
    order = st.selectbox("Review order", orders, key=prefix + "order")
    order_key = {orders[0]: "sequence", orders[1]: "score"}
    if has_times:
        order_key[orders[2]] = "timestamp"
        st.caption("Timestamp view: supplied event_time normalized to UTC. Sorting keeps each record ID aligned with its independent results.")
    else:
        st.caption("Record sequence: original CSV row order; no event timestamps were supplied.")
    indices = review_indices(records, rows, bands=chosen_bands, predictions=chosen_predictions,
                             disagreements_only=disagree_only, order=order_key[order],
                             score_range=score_range, **label_filters)
    st.caption(f"Matching records: {len(indices):,} of {len(records):,} · At most {PAGE_ROWS} records per page")
    if not indices:
        st.info("No records match these filters.")
    else:
        _details(session, records, rows, indices, prefix)
    if session.input_data.has_binary_labels:
        _sample_metrics(original_binary_metrics(session.input_data, records), "Original uploaded-sample binary review metrics")
    if session.input_data.has_family_labels:
        st.subheader("Independent uploaded-sample attack-family review")
        st.caption("Derived from uploaded attack_cat versus family_prediction_raw on the full current sample. Binary-gated triage family is not used; separate from frozen benchmark evidence.")
        st.dataframe(pd.DataFrame([{"Uploaded-sample family review": key, "Records": sum(r["family_error"] == key for r in rows)} for key in FAMILY_ERRORS]), hide_index=True)
    if not session.input_data.has_binary_labels and not session.input_data.has_family_labels:
        st.info("Prediction review only: no uploaded ground truth. Measured-error and threshold controls require uploaded labels; predictions never supply ground truth.")
    _simulation(session, prefix)
    _export(session, indices, order_key[order], prefix)


def _details(session, records, rows, indices, prefix):
    pages = (len(indices) + PAGE_ROWS - 1) // PAGE_ROWS
    # Widget identity includes the filter context; old page and selection cannot survive it.
    context = str(tuple(indices))
    page = st.selectbox("Record page", range(1, pages + 1), key=prefix + context + "page")
    shown = indices[(page - 1) * PAGE_ROWS : page * PAGE_ROWS]
    st.dataframe(pd.DataFrame([_labels(_record_row(records[i], i), rows[i]) for i in shown]), hide_index=True)
    selected = st.selectbox("Record detail", shown,
                            format_func=lambda i: f"{i + 1}: {_bounded(records[i].record_id, 80)}",
                            key=prefix + context + str(page) + "selection")
    record = records[selected]
    st.subheader("Selected record")
    st.dataframe(pd.DataFrame([_labels(_record_row(record, selected), rows[selected])]), hide_index=True)
    st.caption("explanation_status: not_requested · Values longer than 200 characters are truncated for display; selection uses original row identity.")
    # One aligned record, 42 features, bounded string cells.
    row = session.input_data.frame.iloc[selected]
    st.dataframe(pd.DataFrame([{"Feature": column, "Value": _bounded(row[column])} for column in FEATURE_COLUMNS]), hide_index=True)
