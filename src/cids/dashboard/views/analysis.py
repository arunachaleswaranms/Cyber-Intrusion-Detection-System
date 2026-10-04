"""Opt-in local analysis and bounded research review; no frozen metrics here."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict

import pandas as pd
import streamlit as st

from cids.datasets.unsw_nb15 import FEATURE_COLUMNS
from cids.workbench.analysis import (
    AnalysisUnavailable, PAGE_ROWS, QUEUE_BANDS, models_disagree,
    preflight_binding, queue_indices,
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


def render(session, repo_root, pack_id):
    st.title("Local CSV analysis")
    st.caption("Explicit local analysis • separate from frozen benchmark evidence")
    st.markdown("Scores are **model scores (uncalibrated)**. Queue bands organize research review; they do not measure threat severity or business risk. Independent model predictions are shown in both directions of disagreement.")
    st.caption("Uploaded bytes, validated features and predictions stay in this session's process memory. The application does not persist or log them. Clearing drops references; it does not securely erase process memory. Optional labels are validated only; label-backed error review is Phase 3D.")
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
    chosen_bands = st.multiselect("Queue bands", QUEUE_BANDS, default=QUEUE_BANDS, key=prefix + "bands")
    chosen_predictions = st.multiselect("Binary predictions", ("normal", "attack"), default=("normal", "attack"), key=prefix + "predictions")
    disagree_only = st.checkbox("Only model disagreements (either direction)", key=prefix + "disagree")
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
    indices = queue_indices(records, bands=chosen_bands, predictions=chosen_predictions,
                            disagreements_only=disagree_only, order=order_key[order])
    st.caption(f"Matching records: {len(indices):,} of {len(records):,} · At most {PAGE_ROWS} records per page")
    if not indices:
        st.info("No records match these filters.")
        return
    pages = (len(indices) + PAGE_ROWS - 1) // PAGE_ROWS
    # Widget identity includes the filter context; old page and selection cannot survive it.
    context = str((tuple(chosen_bands), tuple(chosen_predictions), disagree_only, order))
    page = st.selectbox("Record page", range(1, pages + 1), key=prefix + context + "page")
    shown = indices[(page - 1) * PAGE_ROWS : page * PAGE_ROWS]
    st.dataframe(pd.DataFrame([_record_row(records[i], i) for i in shown]), hide_index=True)
    selected = st.selectbox("Record detail", shown,
                            format_func=lambda i: f"{i + 1}: {_bounded(records[i].record_id, 80)}",
                            key=prefix + context + str(page) + "selection")
    record = records[selected]
    st.subheader("Selected record")
    st.dataframe(pd.DataFrame([_record_row(record, selected)]), hide_index=True)
    st.caption("explanation_status: not_requested · Values longer than 200 characters are truncated for display; selection uses original row identity.")
    # One aligned record, 42 features, bounded string cells. No optional label/error view.
    row = session.input_data.frame.iloc[selected]
    st.dataframe(pd.DataFrame([{"Feature": column, "Value": _bounded(row[column])} for column in FEATURE_COLUMNS]), hide_index=True)
