"""Overview: release identity, evidence health, and stage-labelled headlines."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cids.dashboard import charts
from cids.dashboard.components import (
    component_problem,
    count_column,
    current_palette,
    fact_tile,
    health_badge,
    metric_tiles,
    official_blocked,
    ratio_column,
    stage_badge,
)
from cids.workbench.catalog import ComponentStatus, EvidenceCatalog
from cids.workbench.confusion import binary_outcomes
from cids.workbench.formatting import (
    format_count,
    format_delta,
    format_percent,
    format_ratio,
    format_timestamp,
    short_digest,
)
from cids.workbench.reporting import (
    EXPLANATION_GATE,
    HEADLINE_METRICS,
    OFFICIAL_TEST,
    TASK_TITLES,
    TASKS,
    VALIDATION,
    WEAK_METRIC_BOUND,
    model_display_name,
    official_metric,
    official_metrics,
    per_class_table,
    stage_comparisons,
    unrecorded_classes,
    weak_classes,
)


def _stage_legend() -> None:
    with st.container(border=True):
        st.markdown(
            "**How to read the numbers.** Each result is tagged with the evaluation"
            " stage it came from. Stages use different models and partitions; do not"
            " compare them as if they were the same measurement."
        )
        for stage in (OFFICIAL_TEST, VALIDATION, EXPLANATION_GATE):
            left, right = st.columns([1, 4], vertical_alignment="center")
            with left:
                stage_badge(stage)
            with right:
                st.caption(stage.description)


def _identity(catalog: EvidenceCatalog) -> None:
    report = catalog.official.report
    binary = report["tasks"]["binary"]["metadata"]
    family = report["tasks"]["multiclass"]["metadata"]
    columns = st.columns(4)
    with columns[0]:
        fact_tile(
            "Binary model",
            model_display_name(binary["model_name"]),
            f"`{binary['estimator_class']}` · artifact version"
            f" `{binary['artifact_version']}`",
        )
    with columns[1]:
        fact_tile(
            "Attack-family model",
            model_display_name(family["model_name"]),
            f"`{family['estimator_class']}` · artifact version"
            f" `{family['artifact_version']}`",
        )
    with columns[2]:
        fact_tile(
            "Official test records",
            format_count(report["dataset_files"]["test"]["records"]),
            "Immutable official UNSW-NB15 testing partition, scored once.",
        )
    with columns[3]:
        fact_tile(
            "Official run completed",
            format_timestamp(report["completed_at_utc"]),
            f"Started {format_timestamp(report['started_at_utc'])}. Status"
            f" `{report['official_test_status']}`.",
        )


def _key_finding(catalog: EvidenceCatalog, task: str) -> str:
    official = catalog.official
    if task == "binary":
        outcomes = binary_outcomes(official)
        recall = official_metric(official, "binary", "recall")
        fpr = official_metric(official, "binary", "false_positive_rate")
        return (
            f"Found {format_percent(recall.value)} of attack records, but flagged "
            f"{format_percent(fpr.value)} of normal records as attacks "
            f"({format_count(outcomes.false_positives)} of "
            f"{format_count(outcomes.normal_records)}), so "
            f"{format_count(outcomes.false_positives)} of "
            f"{format_count(outcomes.attack_predictions)} attack alerts were normal "
            "records."
        )
    table = per_class_table(official, "multiclass")
    weak, unrecorded = weak_classes(table), unrecorded_classes(table)
    parts = []
    if weak:
        largest = table.sort_values("support", ascending=False).head(2)
        share = largest["support"].sum() / table["support"].sum()
        parts.append(
            f"Recall is below {WEAK_METRIC_BOUND:.2f} for {', '.join(weak)}. Macro "
            "F1 is the more representative summary; accuracy is dominated by "
            f"{' and '.join(largest['class'])}, which hold "
            f"{format_percent(share, 0)} of official-test records."
        )
    if unrecorded:
        parts.append(f"Recall is not recorded for {', '.join(unrecorded)}.")
    if not parts:
        parts.append("No class has official-test recall below the presentation bound.")
    return " ".join(parts)


def _task_card(catalog: EvidenceCatalog, task: str) -> None:
    metadata = catalog.official.report["tasks"][task]["metadata"]
    with st.container(border=True):
        st.subheader(TASK_TITLES[task])
        stage_badge(OFFICIAL_TEST)
        st.caption(
            f"{model_display_name(metadata['model_name'])}, refit on"
            f" {format_count(metadata['development_training_rows'])} development rows."
        )
        metric_tiles(
            official_metrics(catalog.official, task, HEADLINE_METRICS[task]), columns=2
        )
        st.markdown(f":material/insights: {_key_finding(catalog, task)}")


def _comparison(catalog: EvidenceCatalog) -> None:
    st.header("Validation → official test")
    with st.container(horizontal=True, gap="small"):
        stage_badge(VALIDATION)
        st.markdown("→")
        stage_badge(OFFICIAL_TEST)
    st.caption(
        "Frozen ranking metrics only: these are the metrics the selection rule used."
        " Validation values come from models fit on the training split; official-test"
        " values come from the same model configuration refit on train plus validation"
        " and scored on a different, immutable partition. The change indicates a"
        " generalization gap, not a like-for-like remeasurement."
    )
    selection_component = catalog.component("model_selection")
    if selection_component.status is not ComponentStatus.VERIFIED:
        component_problem(catalog, selection_component)
        st.info(
            "Validation metrics are hidden because their record could not be bound to"
            " the official run.",
            icon=":material/info:",
        )
        return
    palette = current_palette()
    columns = st.columns(2, gap="large")
    for column, task in zip(columns, TASKS):
        comparisons = stage_comparisons(catalog.selection, catalog.official, task)
        with column:
            st.subheader(TASK_TITLES[task])
            st.altair_chart(
                charts.stage_dumbbell(comparisons, palette), width="stretch"
            )
            table = pd.DataFrame(
                [
                    {
                        "Metric": c.definition.label,
                        "Validation": c.validation.value,
                        "Official test": c.official.value,
                        "Change": format_delta(c.delta),
                        "Reading": c.direction,
                    }
                    for c in comparisons
                ]
            )
            st.dataframe(
                table,
                hide_index=True,
                width="stretch",
                column_config={
                    "Validation": ratio_column("Validation", VALIDATION.description),
                    "Official test": ratio_column(
                        "Official test", OFFICIAL_TEST.description
                    ),
                },
            )
    _reproduction_note(catalog)


def _reproduction_note(catalog: EvidenceCatalog) -> None:
    report = catalog.official.report
    note = (
        "Validation values above are read from the committed frozen model-selection"
        " record (canonical SHA-256"
        f" `{short_digest(report['model_selection_sha256'])}`)."
        " `docs/v2-official-test-results.md` instead quotes the later Apple Silicon"
        " reproduction record"
        f" (`{short_digest(report['reproduction_selection_sha256'])}`), whose digest"
        " the official run recorded but whose file is not committed."
    )
    if catalog.protocol is not None:
        tolerance = catalog.protocol["run_guard"]["reproduction_metric_abs_tolerance"]
        note += (
            " The final protocol refused to unseal the test unless that reproduction"
            f" selected the same models with every selection metric within ±{tolerance}"
            " of this record, so the two sets of validation figures differ by at most"
            " that amount."
        )
    st.caption(f":material/info: {note}")


def _context(catalog: EvidenceCatalog) -> None:
    st.header("Evaluation context")
    report = catalog.official.report
    rows = []
    for task in TASKS:
        split = report["tasks"][task]["split_report"]
        rows.append(
            {
                "Task": TASK_TITLES[task],
                "Target": split["target"],
                "Train rows": split["prepared_rows"]["train"],
                "Validation rows": split["prepared_rows"]["validation"],
                "Official test rows": split["prepared_rows"]["official_test"],
                "Split policy": split["split_policy_version"],
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            name: count_column(name)
            for name in ("Train rows", "Validation rows", "Official test rows")
        },
    )
    diagnostics = report["tasks"]["multiclass"]["split_report"][
        "official_test_diagnostics"
    ]
    st.caption(
        "Training and validation rows differ by task because target-conflicting"
        " duplicates are removed per target. The official test was kept immutable: it"
        f" still contains {format_count(diagnostics['redundant_feature_rows'])}"
        " redundant feature rows and"
        f" {format_count(diagnostics['conflicting_target_groups'])}"
        " attack-family-conflicting feature groups, a plausible but unproven"
        " contributor to the validation-to-test drop."
    )


def _limitations(catalog: EvidenceCatalog) -> None:
    st.header("Limitations")
    fpr = catalog.official.report["tasks"]["binary"]["official_test_metrics"][
        "false_positive_rate"
    ]
    family_f1 = catalog.official.report["tasks"]["multiclass"]["official_test_metrics"][
        "f1_macro"
    ]
    limitations = [
        (
            f"**Not production-ready.** A {format_percent(fpr)} false-positive rate is "
            "too high for an unattended IDS."
        ),
        (
            f"**Weak family attribution.** Macro F1 of {format_ratio(family_f1)} shows "
            "several attack families do not generalize."
        ),
        (
            "**Synthetic, dated data.** UNSW-NB15 does not represent current "
            "organizational traffic."
        ),
        (
            "**Flow records only.** No packet capture, live inspection, blocking, or "
            "automated response."
        ),
        (
            "**Uncalibrated scores.** Model scores were not calibrated and are not "
            "probabilities of maliciousness."
        ),
        (
            "**Frozen by design.** These results must not be used to retune the v2.0 "
            "models."
        ),
    ]
    st.markdown("\n".join(f"- {item}" for item in limitations))
    st.caption(
        "Interpretation follows `docs/v2-official-test-results.md`; the figures in"
        " it are read from the verified evidence."
    )


def render(catalog: EvidenceCatalog) -> None:
    st.title("CIDS evidence dashboard")
    st.caption(
        "v2.1 Phase 2 · evidence mode. Every number on these pages is read from"
        " committed, hash-verified evidence; nothing is recomputed from data or a"
        " model."
    )
    health_badge(catalog)
    if official_blocked(catalog):
        return
    _identity(catalog)
    _stage_legend()
    columns = st.columns(2, gap="large")
    for column, task in zip(columns, TASKS):
        with column:
            _task_card(catalog, task)
    _comparison(catalog)
    _context(catalog)
    _limitations(catalog)
