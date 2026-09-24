"""Deterministic text formatting for evidence values.

Missing values are rendered as ``not recorded`` rather than zero so that absent
evidence is never presented as a measured result.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

NOT_RECORDED = "not recorded"


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def format_ratio(value: object, digits: int = 4) -> str:
    if not _is_number(value):
        return NOT_RECORDED
    return f"{value:.{digits}f}"


def format_percent(value: object, digits: int = 2) -> str:
    if not _is_number(value):
        return NOT_RECORDED
    return f"{value * 100:.{digits}f}%"


def format_delta(value: object, digits: int = 4) -> str:
    if not _is_number(value):
        return NOT_RECORDED
    # Avoid rendering a negative zero such as "-0.0000".
    rounded = round(value, digits)
    if rounded == 0:
        return f"{0:.{digits}f}"
    return f"{rounded:+.{digits}f}"


def format_count(value: object) -> str:
    if not _is_number(value) or int(value) != value:
        return NOT_RECORDED
    return f"{int(value):,}"


def format_scientific(value: object, digits: int = 2) -> str:
    if not _is_number(value):
        return NOT_RECORDED
    return f"{value:.{digits}e}"


def format_seconds(value: object, digits: int = 3) -> str:
    if not _is_number(value):
        return NOT_RECORDED
    return f"{value:.{digits}f} s"


def format_timestamp(value: object) -> str:
    """Render an offset-aware ISO 8601 timestamp in UTC; never guess a zone."""
    if not isinstance(value, str):
        return NOT_RECORDED
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return NOT_RECORDED
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return NOT_RECORDED
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def short_digest(value: object, length: int = 12) -> str:
    if not isinstance(value, str) or not value:
        return NOT_RECORDED
    return value[:length] + ("…" if len(value) > length else "")
