"""Reusable Streamlit building blocks for the evidence dashboard."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import streamlit as st

from cids.dashboard.charts import Palette, palette_for
from cids.workbench.catalog import (
    CatalogHealth,
    ComponentStatus,
    EvidenceCatalog,
    EvidenceComponent,
)
from cids.workbench.reporting import EvaluationStage, MetricValue

STATUS_ICONS = {
    ComponentStatus.VERIFIED: ":material/verified:",
    ComponentStatus.MISSING: ":material/help:",
    ComponentStatus.FAILED: ":material/gpp_bad:",
    ComponentStatus.SKIPPED: ":material/block:",
}
STATUS_LABELS = {
    ComponentStatus.VERIFIED: "Verified",
    ComponentStatus.MISSING: "Missing",
    ComponentStatus.FAILED: "Integrity failure",
    ComponentStatus.SKIPPED: "Not checked",
}
STAGE_COLORS = {
    "validation": "blue",
    "official_test": "violet",
    "explanation_gate": "gray",
}
HEALTH_TEXT = {
    CatalogHealth.COMPLETE: (
        "All committed evidence verified",
        "green",
        ":material/verified_user:",
    ),
    CatalogHealth.DEGRADED: (
        "Partial evidence: some views unavailable",
        "orange",
        ":material/warning:",
    ),
    CatalogHealth.BLOCKED: (
        "Official evidence unavailable",
        "red",
        ":material/gpp_bad:",
    ),
}


def current_palette() -> Palette:
    return palette_for(st.context.theme.type)


def research_notice() -> None:
    st.caption(
        ":material/science: **Offline research artifact, not a production IDS.** "
        "Results describe frozen v2.0 models on the synthetic UNSW-NB15 dataset. "
        "Nothing here inspects live traffic, blocks connections, or loads a model."
    )


def stage_badge(stage: EvaluationStage) -> None:
    st.badge(stage.badge, color=STAGE_COLORS[stage.key], help=stage.description)


def page_header(
    title: str, subtitle: str, stage: EvaluationStage | None = None
) -> None:
    st.title(title)
    if stage is not None:
        stage_badge(stage)
    st.caption(subtitle)


def health_badge(catalog: EvidenceCatalog) -> None:
    text, color, icon = HEALTH_TEXT[catalog.health]
    st.badge(text, color=color, icon=icon)


def metric_tiles(metrics: Sequence[MetricValue], columns: int = 4) -> None:
    """Metric tiles whose help text names the definition and exact source."""
    for start in range(0, len(metrics), columns):
        row = st.columns(columns)
        for slot, metric in zip(row, metrics[start : start + columns]):
            with slot:
                st.metric(
                    metric.definition.label,
                    metric.display,
                    border=True,
                    help=(
                        f"{metric.definition.description}\n\n"
                        f"Stage: {metric.stage.label}.\n\n"
                        f"Source: `{metric.source}`"
                    ),
                )


def source_table(metrics: Sequence[MetricValue]) -> None:
    """Exact recorded values with full precision and their JSON pointers."""
    frame = pd.DataFrame(
        [
            {
                "Metric": metric.definition.label,
                "Recorded value": (
                    "not recorded" if metric.value is None else repr(metric.value)
                ),
                "Stage": metric.stage.label,
                "File": metric.source.path,
                "JSON pointer": metric.source.pointer,
            }
            for metric in metrics
        ]
    )
    st.dataframe(frame, hide_index=True, width="stretch")


def ratio_column(label: str, help_text: str | None = None):
    return st.column_config.NumberColumn(label, format="%.4f", help=help_text)


def count_column(label: str, help_text: str | None = None):
    return st.column_config.NumberColumn(label, format="localized", help=help_text)


def count_matrix(frame: pd.DataFrame) -> None:
    """A count table (such as a confusion matrix) with thousands separators."""
    st.dataframe(
        frame,
        width="stretch",
        column_config={column: count_column(column) for column in frame.columns},
    )


def full_height(rows: int) -> int:
    """Pixel height that shows every row of a dataframe without inner scrolling."""
    return (rows + 1) * 35 + 3


def fact_tile(label: str, value: str, help_text: str) -> None:
    """A bordered label/value pair whose value wraps instead of truncating."""
    with st.container(border=True, height="stretch"):
        st.caption(label, help=help_text)
        st.markdown(f"**{value}**")


def component_problem(catalog: EvidenceCatalog, component: EvidenceComponent) -> None:
    """Explain an unavailable component with the files and next step."""
    paths = ", ".join(f"`{catalog.relative(path)}`" for path in component.paths)
    if component.status is ComponentStatus.FAILED:
        st.error(
            f"**{component.title} failed verification.** {component.detail}\n\n"
            f"Files: {paths}. Do not trust values from these files. If they were "
            "edited, restore them from the repository (`git status`, then "
            "`git checkout -- <path>`). If they are unmodified, the pinned digests "
            "or the evidence they are bound to have changed; reconcile that "
            "change before trusting the dashboard.",
            icon=":material/gpp_bad:",
        )
    elif component.status is ComponentStatus.MISSING:
        st.warning(
            f"**{component.title} is missing.** {component.detail}\n\n"
            f"Expected: {paths}. These files are committed to the repository; "
            "check that the clone is complete.",
            icon=":material/help:",
        )
    elif component.status is ComponentStatus.SKIPPED:
        st.info(
            f"**{component.title} was not checked.** {component.detail}",
            icon=":material/block:",
        )


def official_blocked(catalog: EvidenceCatalog) -> bool:
    """Render a blocking error and return True when official evidence is unusable."""
    component = catalog.component("official_results")
    if component.status is ComponentStatus.VERIFIED:
        return False
    component_problem(catalog, component)
    st.info(
        "No official-test metric is shown because the frozen evidence could not be "
        "verified. The dashboard never substitutes sample or recomputed values.",
        icon=":material/info:",
    )
    return True
