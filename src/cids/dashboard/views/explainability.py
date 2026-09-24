"""Explainability: approved method, gate evidence, and what is not yet available."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cids.dashboard.components import component_problem, page_header
from cids.workbench.catalog import ComponentStatus, EvidenceCatalog
from cids.workbench.formatting import (
    format_count,
    format_scientific,
    format_seconds,
    format_timestamp,
    short_digest,
)
from cids.workbench.reporting import (
    EXPLANATION_GATE,
    TASK_TITLES,
    TASKS,
    class_display_name,
)

PARTITION_NAMES = {
    "prepared_train": "Prepared training split",
    "prepared_validation": "Prepared validation split",
}


def _meaning() -> None:
    left, right = st.columns(2, gap="large")
    with left, st.container(border=True):
        st.markdown("**What a SHAP value is**")
        st.markdown("""
A SHAP value is a signed contribution of one input feature to **one model output
for one record**, relative to a baseline output over a background sample. The
contributions plus the baseline add up to the model's output (*additivity*).
Here the explained output is the estimator's **raw decision score**, not a
probability. Contributions for one-hot columns are summed back to the 42
original flow features.
""")
    with right, st.container(border=True):
        st.markdown("**What it is not**")
        st.markdown("""
- **Not causality.** A feature that *influenced this model output* did not
  necessarily cause, or even correlate with, malicious behaviour.
- **Not confidence.** Scores were never calibrated; contributions do not turn
  them into a chance that traffic is malicious.
- **Not ground truth.** Explanations describe what the model does, including
  its mistakes, and depend on the chosen background sample.
""")


def _explained_classes(task: str, gate_task) -> str:
    classes = gate_task.explained_classes
    if set(classes) == set(gate_task.class_labels) and len(classes) > 1:
        return f"All {len(classes)} classes"
    return ", ".join(
        f"{class_display_name(task, label)} (label {label})" for label in classes
    )


def _gate_table(catalog: EvidenceCatalog) -> pd.DataFrame:
    gate = catalog.gate
    policy = gate.policy["explainability"]
    rows = []
    for task in TASKS:
        t = gate.tasks[task]
        rows.append(
            {
                "Task": TASK_TITLES[task],
                "Explainer": (
                    f"SHAP {t.explainer_algorithm} ({t.permutation_rounds}"
                    " forward/reverse cycle)"
                ),
                "Explained output": f"{t.model_output} decision score",
                "Explained classes": _explained_classes(task, t),
                "Background": (
                    f"{format_count(t.background_rows)} rows ·"
                    f" {PARTITION_NAMES.get(t.background_partition, t.background_partition)}"
                ),
                "Explained rows": (
                    f"{format_count(t.explained_rows)} rows ·"
                    f" {PARTITION_NAMES.get(t.foreground_partition, t.foreground_partition)}"
                ),
                "Max additivity error": (
                    f"{format_scientific(t.max_additivity_error)} (limit"
                    f" {format_scientific(policy['additivity_abs_tolerance'])})"
                ),
                "Max aggregation error": (
                    f"{format_scientific(t.max_aggregation_error)} (limit"
                    f" {format_scientific(policy['aggregation_abs_tolerance'])})"
                ),
                "Elapsed": (
                    f"{format_seconds(t.elapsed_seconds)} (limit"
                    f" {format_seconds(policy['max_task_seconds'], 0)})"
                ),
                "Features": (
                    f"{t.transformed_feature_count} encoded → {t.source_feature_count}"
                    " source"
                ),
                "Artifact SHA-256": short_digest(t.artifact_sha256, 16),
            }
        )
    return pd.DataFrame(rows).set_index("Task").T


def _gate(catalog: EvidenceCatalog) -> None:
    report = catalog.gate.report
    st.header("Phase 1 explanation gate")
    st.success(
        f"**Passed** on {format_timestamp(report['completed_at_utc'])} with SHAP "
        f"{report['environment']['shap']} on Python {report['environment']['python']}. "
        f"Official-test status: `{report['official_test_status']}`.",
        icon=":material/task_alt:",
    )
    st.dataframe(_gate_table(catalog), width="stretch")
    st.caption(
        "The gate checked that the bounded method reproduces each model's raw output "
        "and maps back to the source features within the committed policy limits. "
        "The tree-specific explainer originally proposed was rejected after failing "
        "additivity on the selected binary artifact (ADR 0003)."
    )


def _availability(catalog: EvidenceCatalog) -> None:
    st.header("Feature attributions")
    message = (
        "**Global feature importance and per-record contributions are not available "
        "in evidence mode.** The committed gate report stores correctness and resource "
        "diagnostics only; it contains no attribution values. Producing attributions "
        "requires the local trusted model artifacts and dataset, which evidence mode "
        "never loads."
    )
    if catalog.gate is not None:
        rows = max(task.explained_rows for task in catalog.gate.tasks.values())
        message += (
            f" The gate explained at most {rows} validation rows per task, too few "
            "to support a global ranking."
        )
    st.warning(message, icon=":material/visibility_off:")
    st.markdown(
        "The v2.1 design schedules global and per-record explanation views for "
        "**Phase 4**, after trusted local inference exists (Phase 3). When added, "
        "they must state the dataset and records they were computed on and use "
        "*influenced this model output* wording."
    )


def render(catalog: EvidenceCatalog) -> None:
    page_header(
        "Explainability",
        "What the approved explanation method means, and the evidence that it works on"
        " the frozen models.",
        EXPLANATION_GATE,
    )
    _meaning()
    component = catalog.component("explanation_gate")
    if component.status is ComponentStatus.VERIFIED:
        _gate(catalog)
    else:
        st.header("Phase 1 explanation gate")
        component_problem(catalog, component)
        st.info(
            "Without verified gate evidence, the dashboard makes no claim that the "
            "explanation method is correct for these models.",
            icon=":material/info:",
        )
    _availability(catalog)
