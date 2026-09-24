"""Binary detection: official-test errors, per-family detection, and sources."""

from __future__ import annotations

import streamlit as st

from cids.dashboard import charts
from cids.dashboard.components import (
    count_column,
    count_matrix,
    current_palette,
    metric_tiles,
    official_blocked,
    page_header,
    ratio_column,
    source_table,
)
from cids.workbench.catalog import EvidenceCatalog
from cids.workbench.confusion import binary_outcomes, confusion_matrix
from cids.workbench.formatting import format_count, format_percent, format_ratio
from cids.workbench.reporting import (
    HEADLINE_METRICS,
    OFFICIAL_TEST,
    SECONDARY_METRICS,
    family_detection_table,
    model_display_name,
    official_metric,
    official_metrics,
    per_class_table,
)

TASK = "binary"


def _errors(catalog: EvidenceCatalog) -> None:
    matrix = confusion_matrix(catalog.official, TASK)
    outcomes = binary_outcomes(catalog.official)
    fnr = official_metric(catalog.official, TASK, "false_negative_rate")
    fpr = official_metric(catalog.official, TASK, "false_positive_rate")
    st.header("Where the errors are")
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.altair_chart(
            charts.confusion_heatmap(matrix, current_palette(), label_min_share=0.0),
            width="content",
        )
    with right:
        st.markdown("**Exact counts** (rows: actual, columns: predicted)")
        count_matrix(matrix.wide_frame())
        o = outcomes
        st.markdown(
            "\n".join(
                [
                    (
                        f"- **{format_count(o.attack_predictions)}** records classified"
                        f" as attack; **{format_count(o.false_positives)}** of them"
                        " were normal."
                    ),
                    (
                        f"- **{format_count(o.false_negatives)}** of "
                        f"{format_count(o.attack_records)} attack records were missed "
                        f"({format_percent(fnr.value)} false-negative rate)."
                    ),
                    (
                        f"- **{format_count(o.false_positives)}** of "
                        f"{format_count(o.normal_records)} normal records were flagged "
                        f"({format_percent(fpr.value)} false-positive rate)."
                    ),
                ]
            )
        )
        st.caption(
            "Ground-truth labels exist for the official test, so these counts are"
            " true/false positives and negatives on that partition only."
        )


def _per_class(catalog: EvidenceCatalog) -> None:
    st.subheader("Per-class metrics")
    table = per_class_table(catalog.official, TASK)[
        ["class", "support", "precision", "recall", "f1"]
    ]
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "class": "Class",
            "support": count_column("Support", "Official-test records of this class."),
            "precision": ratio_column("Precision"),
            "recall": ratio_column("Recall"),
            "f1": ratio_column("F1"),
        },
    )
    st.caption(
        "Normal-class recall is the complement of the false-positive rate, and"
        " attack-class recall is the complement of the false-negative rate."
    )


def _families(catalog: EvidenceCatalog) -> None:
    st.header("Missed attacks by family")
    st.caption(
        "The binary model predicts only normal or attack. Official-test attack-family"
        " labels are used here solely to group its errors; they were not model input."
    )
    detection = family_detection_table(catalog.official)
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.altair_chart(
            charts.miss_rate_bars(detection, current_palette()), width="stretch"
        )
    with right:
        st.dataframe(
            detection[["class", "support", "detected", "missed", "detection_rate"]],
            hide_index=True,
            width="stretch",
            column_config={
                "class": "Attack family",
                "support": count_column("Records"),
                "detected": count_column("Detected"),
                "missed": count_column("Missed"),
                "detection_rate": ratio_column("Detection rate"),
            },
        )
    worst = detection.sort_values("missed", ascending=False).iloc[0]
    st.caption(
        f"{worst['class']} accounts for {format_count(int(worst['missed']))} of the "
        f"{format_count(int(detection['missed'].sum()))} missed attacks. Detected and "
        "missed counts are reconstructed from the recorded rate × family support and "
        "checked to be whole numbers."
    )


def _timing(catalog: EvidenceCatalog) -> None:
    metrics = catalog.official.report["tasks"][TASK]["official_test_metrics"]
    st.caption(
        ":material/timer: Recorded prediction time"
        f" {format_ratio(metrics.get('prediction_ms_per_record'))} ms per record on the"
        " maintainer's Mac. It excludes model loading, preprocessing and probability"
        " scoring and is not a throughput benchmark."
    )


def render(catalog: EvidenceCatalog) -> None:
    page_header(
        "Binary attack detection",
        "Normal versus attack on the official held-out test, from the single frozen"
        " run.",
        OFFICIAL_TEST,
    )
    if official_blocked(catalog):
        return
    metadata = catalog.official.report["tasks"][TASK]["metadata"]
    st.caption(
        f"Model: {model_display_name(metadata['model_name'])}"
        f" (`{metadata['estimator_class']}`), class weight"
        f" `{metadata['estimator_parameters']['class_weight']}`, default `predict`"
        " decision rule."
    )
    headline = official_metrics(catalog.official, TASK, HEADLINE_METRICS[TASK])
    secondary = official_metrics(catalog.official, TASK, SECONDARY_METRICS[TASK])
    metric_tiles(headline)
    metric_tiles(secondary, columns=6)
    st.caption(
        "ROC-AUC and PR-AUC summarize ranking by the uncalibrated attack score; they do"
        " not describe the fixed decision rule the other metrics use."
    )
    _errors(catalog)
    _per_class(catalog)
    _families(catalog)
    _timing(catalog)
    with st.expander(
        "Sources for every metric on this page", icon=":material/data_object:"
    ):
        source_table(headline + secondary)
