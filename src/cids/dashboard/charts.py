"""Altair chart specifications for evidence views.

Colors follow a validated two-slot categorical palette (blue/orange, checked
for colour-vision-deficiency separation in light and dark modes) and a single
blue sequential ramp. Every chart ships with a tooltip, and every page pairs
each chart with an exact-value table, so no value depends on colour alone.
"""

from __future__ import annotations

from dataclasses import dataclass

import altair as alt
import pandas as pd

from cids.workbench.confusion import ConfusionMatrix
from cids.workbench.reporting import StageComparison


@dataclass(frozen=True)
class Palette:
    series_1: str
    series_2: str
    sequential: tuple[str, ...]
    neutral: str
    ink_on_dark: str
    ink_on_light: str


LIGHT = Palette(
    series_1="#2a78d6",
    series_2="#eb6834",
    sequential=(
        "#f0f5fc",
        "#cde2fb",
        "#9ec5f4",
        "#6da7ec",
        "#3987e5",
        "#256abf",
        "#184f95",
        "#0d366b",
    ),
    neutral="#a3a29d",
    ink_on_dark="#ffffff",
    ink_on_light="#0b0b0b",
)
DARK = Palette(
    series_1="#3987e5",
    series_2="#d95926",
    sequential=(
        "#1f2530",
        "#0d366b",
        "#184f95",
        "#256abf",
        "#3987e5",
        "#6da7ec",
        "#9ec5f4",
        "#cde2fb",
    ),
    neutral="#6f6e69",
    ink_on_dark="#ffffff",
    ink_on_light="#0b0b0b",
)


def palette_for(theme_type: str | None) -> Palette:
    return DARK if theme_type == "dark" else LIGHT


def confusion_heatmap(
    matrix: ConfusionMatrix, palette: Palette, *, label_min_share: float
) -> alt.Chart:
    """Row-normalised heatmap: colour is the share of each actual class.

    Normalising by row keeps rare classes readable next to the 37,000 normal
    records. Cell labels are selective; tooltips carry the exact counts.
    """
    frame = matrix.long_frame()
    order = list(matrix.display_labels)
    frame["label"] = [
        f"{share:.0%}" if share >= label_min_share else ""
        for share in frame["share_of_actual"]
    ]
    # Light ramps put dark cells at high shares; the dark-mode ramp is reversed.
    high_share = alt.datum.share_of_actual >= 0.55
    dark_ink, light_ink = palette.ink_on_dark, palette.ink_on_light
    ink = (
        alt.condition(high_share, alt.value(dark_ink), alt.value(light_ink))
        if palette is LIGHT
        else alt.condition(high_share, alt.value(light_ink), alt.value(dark_ink))
    )
    step = 44 if len(order) > 2 else 90
    base = alt.Chart(frame).encode(
        x=alt.X(
            "predicted:N",
            sort=order,
            title="Predicted class",
            axis=alt.Axis(
                labelAngle=-40, orient="top", labelLimit=0, labelOverlap=False
            ),
        ),
        y=alt.Y(
            "actual:N",
            sort=order,
            title="Actual class",
            axis=alt.Axis(labelLimit=0, labelOverlap=False),
        ),
    )
    cells = base.mark_rect(cornerRadius=2).encode(
        color=alt.Color(
            "share_of_actual:Q",
            title="Share of actual class",
            scale=alt.Scale(domain=[0, 1], range=list(palette.sequential)),
            legend=alt.Legend(format=".0%", orient="bottom", gradientLength=220),
        ),
        tooltip=[
            alt.Tooltip("actual:N", title="Actual"),
            alt.Tooltip("predicted:N", title="Predicted"),
            alt.Tooltip("count:Q", title="Records", format=","),
            alt.Tooltip(
                "share_of_actual:Q", title="Share of actual class", format=".2%"
            ),
        ],
    )
    text = base.mark_text(fontSize=12 if len(order) > 2 else 16).encode(
        text="label:N",
        color=ink,
    )
    return (cells + text).properties(width=alt.Step(step), height=alt.Step(step))


def _series_legend() -> alt.Legend:
    # Colour and shape share one legend so identity is never colour alone.
    return alt.Legend(orient="top", title=None, labelLimit=0)


def precision_recall_dots(per_class: pd.DataFrame, palette: Palette) -> alt.Chart:
    """Precision and recall per class on one 0–1 axis, joined by a range rule."""
    order = list(per_class["class"])
    long = per_class.melt(
        id_vars=["class", "support"],
        value_vars=["precision", "recall"],
        var_name="metric",
        value_name="value",
    )
    long["metric"] = long["metric"].str.capitalize()
    rules = (
        alt.Chart(per_class)
        .mark_rule(color=palette.neutral, strokeWidth=2)
        .encode(
            y=alt.Y("class:N", sort=order, title=None),
            x=alt.X("precision:Q"),
            x2="recall:Q",
        )
    )
    points = (
        alt.Chart(long)
        .mark_point(filled=True, size=110, opacity=1)
        .encode(
            y=alt.Y("class:N", sort=order, title=None),
            x=alt.X(
                "value:Q",
                title="Official-test value",
                scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(format=".1f"),
            ),
            color=alt.Color(
                "metric:N",
                scale=alt.Scale(
                    domain=["Precision", "Recall"],
                    range=[palette.series_1, palette.series_2],
                ),
                legend=_series_legend(),
            ),
            shape=alt.Shape(
                "metric:N",
                scale=alt.Scale(
                    domain=["Precision", "Recall"], range=["circle", "square"]
                ),
                legend=_series_legend(),
            ),
            tooltip=[
                alt.Tooltip("class:N", title="Class"),
                alt.Tooltip("metric:N", title="Metric"),
                alt.Tooltip("value:Q", title="Value", format=".4f"),
                alt.Tooltip("support:Q", title="Support", format=","),
            ],
        )
    )
    return (rules + points).properties(height=alt.Step(34))


def miss_rate_bars(detection: pd.DataFrame, palette: Palette) -> alt.Chart:
    """Share of each family's attack records the binary model called normal.

    Detection rates cluster near 1.0, so plotting the complement makes the
    differences visible without truncating a bar axis.
    """
    frame = detection.assign(miss_rate=1 - detection["detection_rate"])
    order = list(frame.sort_values("miss_rate", ascending=False)["class"])
    return (
        alt.Chart(frame)
        .mark_bar(color=palette.series_1, cornerRadiusEnd=4, height=16)
        .encode(
            y=alt.Y("class:N", sort=order, title=None),
            x=alt.X(
                "miss_rate:Q",
                title="Missed (classified as normal)",
                axis=alt.Axis(format=".0%", tickMinStep=0.01),
            ),
            tooltip=[
                alt.Tooltip("class:N", title="Attack family"),
                alt.Tooltip("miss_rate:Q", title="Missed share", format=".2%"),
                alt.Tooltip("missed:Q", title="Missed records", format=","),
                alt.Tooltip("support:Q", title="Family records", format=","),
            ],
        )
        .properties(height=alt.Step(30))
    )


def stage_dumbbell(comparisons: list[StageComparison], palette: Palette) -> alt.Chart:
    """Validation and official-test values for the frozen ranking metrics."""
    rows = []
    for comparison in comparisons:
        for metric in (comparison.validation, comparison.official):
            if metric.value is None:
                continue
            rows.append(
                {
                    "metric": comparison.definition.label,
                    "stage": metric.stage.label,
                    "value": metric.value,
                }
            )
    frame = pd.DataFrame(rows)
    order = [comparison.definition.label for comparison in comparisons]
    stages = [
        comparisons[0].validation.stage.label,
        comparisons[0].official.stage.label,
    ]
    rules = (
        alt.Chart(frame)
        .mark_line(color=palette.neutral, strokeWidth=2)
        .encode(
            y=alt.Y("metric:N", sort=order, title=None, axis=alt.Axis(labelLimit=0)),
            x="value:Q",
            detail="metric:N",
        )
    )
    points = (
        alt.Chart(frame)
        .mark_point(filled=True, size=110, opacity=1)
        .encode(
            y=alt.Y("metric:N", sort=order, title=None, axis=alt.Axis(labelLimit=0)),
            x=alt.X(
                "value:Q",
                title=None,
                scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(format=".1f"),
            ),
            color=alt.Color(
                "stage:N",
                scale=alt.Scale(
                    domain=stages, range=[palette.series_1, palette.series_2]
                ),
                legend=_series_legend(),
            ),
            shape=alt.Shape(
                "stage:N",
                scale=alt.Scale(domain=stages, range=["circle", "square"]),
                legend=_series_legend(),
            ),
            tooltip=[
                alt.Tooltip("metric:N", title="Metric"),
                alt.Tooltip("stage:N", title="Stage"),
                alt.Tooltip("value:Q", title="Value", format=".4f"),
            ],
        )
    )
    return (rules + points).properties(height=alt.Step(40))
