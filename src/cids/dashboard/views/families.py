"""Attack-family classification: per-class weaknesses and confusion structure."""

from __future__ import annotations

import pandas as pd
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
from cids.workbench.confusion import confusion_matrix
from cids.workbench.formatting import format_count, format_percent, format_ratio
from cids.workbench.reporting import (
    HEADLINE_METRICS,
    OFFICIAL_RESULT_PATH,
    OFFICIAL_TEST,
    SECONDARY_METRICS,
    SMALL_SUPPORT_BOUND,
    WEAK_METRIC_BOUND,
    family_detection_table,
    json_pointer,
    model_display_name,
    official_metrics,
    per_class_table,
    unrecorded_classes,
)

TASK = "multiclass"
HEATMAP_LABEL_MIN_SHARE = 0.05


def _weaknesses(table: pd.DataFrame) -> None:
    unrecorded = set(unrecorded_classes(table))
    recorded = table[~table["class"].isin(unrecorded)]
    flagged = recorded[recorded["weakness"] != ""]
    with st.container(border=True):
        st.markdown("**Where the model struggles**")
        st.caption(
            f"Flag rule (presentation only): recall below {WEAK_METRIC_BOUND:.2f} is"
            f" *mostly missed*; precision below {WEAK_METRIC_BOUND:.2f} is"
            f" *over-predicted*. Support below {SMALL_SUPPORT_BOUND} records is marked"
            " as a noisy estimate."
        )
        if flagged.empty:
            st.markdown("No class with recorded metrics meets the flag rule.")
        for row in flagged.to_dict("records"):
            caution = " · small support, noisy estimate" if row["small_support"] else ""
            st.markdown(
                f"- **{row['class']}**: {row['weakness']} (precision "
                f"{format_ratio(row['precision'])}, recall "
                f"{format_ratio(row['recall'])}, {format_count(row['support'])} "
                f"records{caution})"
            )
        small = recorded[recorded["small_support"] & (recorded["weakness"] == "")]
        for row in small.to_dict("records"):
            st.markdown(
                f"- **{row['class']}**: not flagged, but only "
                f"{format_count(row['support'])} records; treat its metrics as noisy."
            )
        if unrecorded:
            st.warning(
                "Precision or recall is not recorded for "
                + ", ".join(sorted(unrecorded))
                + "; these classes are neither flagged nor cleared.",
                icon=":material/help:",
            )


def _per_class(table: pd.DataFrame) -> None:
    st.header("Per-class performance")
    left, right = st.columns([2, 3], gap="large")
    with left:
        st.altair_chart(
            charts.precision_recall_dots(table, current_palette()), width="stretch"
        )
        st.caption(
            "A long bar between the two points means the class is either over-predicted"
            " (precision far left) or missed (recall far left)."
        )
    with right:
        st.dataframe(
            table[
                [
                    "class",
                    "weakness",
                    "support",
                    "precision",
                    "recall",
                    "f1",
                    "false_positive_rate",
                    "false_negative_rate",
                ]
            ],
            hide_index=True,
            width="stretch",
            column_config={
                "class": "Class",
                "support": count_column("Support"),
                "precision": ratio_column("Precision"),
                "recall": ratio_column("Recall"),
                "f1": ratio_column("F1"),
                "false_positive_rate": ratio_column(
                    "FPR (1-vs-rest)",
                    "Share of records from other classes predicted as this class.",
                ),
                "false_negative_rate": ratio_column(
                    "FNR (1-vs-rest)", "Share of this class predicted as another class."
                ),
                "weakness": "Flag",
            },
        )


def _confusion(catalog: EvidenceCatalog, table: pd.DataFrame) -> None:
    matrix = confusion_matrix(catalog.official, TASK)
    st.header("Confusion structure")
    st.caption(
        "Colour is each cell's share of its actual class (row). Labels show shares of"
        f" at least {HEATMAP_LABEL_MIN_SHARE:.0%}; hover for exact counts."
    )
    st.altair_chart(
        charts.confusion_heatmap(
            matrix, current_palette(), label_min_share=HEATMAP_LABEL_MIN_SHARE
        ),
        width="content",
    )
    top = matrix.top_confusions(limit=6)
    st.subheader("Largest misclassifications")
    st.dataframe(
        top,
        hide_index=True,
        width="stretch",
        column_config={
            "actual": "Actual class",
            "predicted": "Predicted as",
            "count": count_column("Records"),
            "share_of_actual": ratio_column("Share of actual class"),
        },
    )
    st.caption(_sink_summary(top, table))
    with st.expander("Exact confusion matrix", icon=":material/table:"):
        count_matrix(matrix.wide_frame())


def _sink_summary(top: pd.DataFrame, table: pd.DataFrame) -> str:
    """Name the class absorbing most listed errors, linking precision only if low."""
    caveat = "The matrix shows where errors go; it does not establish why."
    if top.empty:
        return caveat
    into = top.groupby("predicted")["count"].sum().sort_values(ascending=False)
    sink, count = into.index[0], int(into.iloc[0])
    summary = (
        f"{format_count(count)} of the {format_count(int(top['count'].sum()))} records "
        f"in this list were predicted as {sink}."
    )
    precision = table.loc[table["class"] == sink, "precision"]
    if not precision.empty and precision.iloc[0] < WEAK_METRIC_BOUND:
        summary += (
            f" This is consistent with {sink}'s low precision"
            f" ({precision.iloc[0]:.4f})."
        )
    return f"{summary} {caveat}"


def _binary_contrast(catalog: EvidenceCatalog, table: pd.DataFrame) -> None:
    st.header("Detected as attack ≠ attributed to the right family")
    st.caption(
        "Both columns are official-test results from the same records. The binary"
        " model's detection rate and the family model's recall answer different"
        " questions."
    )
    detection = family_detection_table(catalog.official)[
        ["family", "class", "detection_rate"]
    ]
    recall = table[["label", "recall"]].rename(columns={"label": "family"})
    merged = detection.merge(recall, on="family", how="left", validate="one_to_one")
    merged = merged.sort_values("recall")
    st.dataframe(
        merged[["class", "detection_rate", "recall"]],
        hide_index=True,
        width="stretch",
        column_config={
            "class": "Attack family",
            "detection_rate": ratio_column(
                "Binary detection rate",
                "Share of this family the binary model classified as attack.",
            ),
            "recall": ratio_column(
                "Family recall",
                "Share of this family the multiclass model labelled correctly.",
            ),
        },
    )
    worst = merged.iloc[0]
    st.caption(
        f"For example, {format_percent(worst['detection_rate'])} of {worst['class']}"
        " records were flagged as attacks by the binary model, but only"
        f" {format_percent(worst['recall'])} were attributed to the correct family."
    )


def render(catalog: EvidenceCatalog) -> None:
    page_header(
        "Attack-family classification",
        "Ten classes (normal plus nine attack families) on the official held-out test,"
        " from the single frozen run.",
        OFFICIAL_TEST,
    )
    if official_blocked(catalog):
        return
    metadata = catalog.official.report["tasks"][TASK]["metadata"]
    st.caption(
        f"Model: {model_display_name(metadata['model_name'])}"
        f" (`{metadata['estimator_class']}`), trained independently of the binary"
        " model."
    )
    headline = official_metrics(catalog.official, TASK, HEADLINE_METRICS[TASK])
    secondary = official_metrics(catalog.official, TASK, SECONDARY_METRICS[TASK])
    metric_tiles(headline)
    metric_tiles(secondary)
    table = per_class_table(catalog.official, TASK)
    _weaknesses(table)
    _per_class(table)
    _confusion(catalog, table)
    _binary_contrast(catalog, table)
    with st.expander(
        "Sources for every metric on this page", icon=":material/data_object:"
    ):
        source_table(headline + secondary)
        base = ("tasks", TASK, "official_test_metrics")
        st.caption(
            f"Per-class values come from `{json_pointer((*base, 'per_class'))}` and "
            f"the matrix from `{json_pointer((*base, 'confusion_matrix'))}` in "
            f"`{OFFICIAL_RESULT_PATH}`."
        )
