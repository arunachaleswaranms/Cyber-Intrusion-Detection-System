"""Input and prediction contracts for the v2.1 analyst workbench."""

from __future__ import annotations

import csv
import hashlib
import io
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import numpy as np
import pandas as pd

from cids.datasets.unsw_nb15 import (
    ATTACK_FAMILIES,
    ATTACK_FAMILY_COLUMN,
    BINARY_LABEL_COLUMN,
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    ID_COLUMN,
    NUMERIC_FEATURES,
    normalize_attack_family,
)
from cids.workbench.config import load_workbench_config, validate_workbench_config

EVENT_TIME_COLUMN = "event_time"
OPTIONAL_COLUMNS = (
    ID_COLUMN,
    EVENT_TIME_COLUMN,
    BINARY_LABEL_COLUMN,
    ATTACK_FAMILY_COLUMN,
)
COMPRESSED_MAGIC = (
    b"\x1f\x8b",  # gzip
    b"PK\x03\x04",  # zip
    b"BZh",  # bzip2
    b"\xfd7zXZ\x00",  # xz
)
QueueBand = Literal[
    "not_alerted", "review", "higher_score_review", "model_disagreement"
]
ExplanationStatus = Literal["available", "not_requested", "unsupported", "failed"]


class InputContractError(ValueError):
    """Raised when an uploaded inference CSV violates the frozen contract."""


class PredictionContractError(ValueError):
    """Raised when a prediction record violates the workbench contract."""


@dataclass(frozen=True)
class InferenceInput:
    frame: pd.DataFrame
    input_sha256: str
    source_bytes: int
    generated_ids: bool
    has_event_time: bool
    has_binary_labels: bool
    has_family_labels: bool


@dataclass(frozen=True)
class FeatureContribution:
    feature: str
    observed_value: object
    contribution: float
    explained_class: str
    baseline_output: float
    model_output: float

    def __post_init__(self) -> None:
        if self.feature not in FEATURE_COLUMNS:
            raise PredictionContractError(f"unknown contribution feature: {self.feature}")
        if self.explained_class not in {"attack", *ATTACK_FAMILIES}:
            raise PredictionContractError("unsupported explained class")
        for name in ("contribution", "baseline_output", "model_output"):
            if not np.isfinite(float(getattr(self, name))):
                raise PredictionContractError(f"{name} must be finite")


@dataclass(frozen=True)
class PredictionRecord:
    record_id: str
    event_time_utc: str | None
    binary_prediction: Literal["normal", "attack"]
    attack_model_score: float
    family_prediction_raw: str
    family_model_score: float
    triage_family: str
    queue_band: QueueBand
    explanation_status: ExplanationStatus
    top_contributions: tuple[FeatureContribution, ...]
    model_pack_id: str

    def __post_init__(self) -> None:
        if not self.record_id:
            raise PredictionContractError("record_id must not be empty")
        if self.binary_prediction not in {"normal", "attack"}:
            raise PredictionContractError("unsupported binary prediction")
        if self.family_prediction_raw not in ATTACK_FAMILIES:
            raise PredictionContractError("unsupported attack-family prediction")
        for name in ("attack_model_score", "family_model_score"):
            value = float(getattr(self, name))
            if not np.isfinite(value) or not 0 <= value <= 1:
                raise PredictionContractError(f"{name} must be between 0 and 1")
        if self.queue_band not in {
            "not_alerted",
            "review",
            "higher_score_review",
            "model_disagreement",
        }:
            raise PredictionContractError("unsupported queue band")
        if self.explanation_status not in {
            "available",
            "not_requested",
            "unsupported",
            "failed",
        }:
            raise PredictionContractError("unsupported explanation status")
        if not _is_sha256(self.model_pack_id):
            raise PredictionContractError("model_pack_id must be a SHA-256 digest")
        if self.binary_prediction == "normal":
            if self.triage_family != "not_alerted" or self.queue_band != "not_alerted":
                raise PredictionContractError("normal prediction must not enter review")
        elif self.family_prediction_raw == "normal":
            if (
                self.triage_family != "unresolved"
                or self.queue_band != "model_disagreement"
            ):
                raise PredictionContractError("binary/family disagreement is inconsistent")
        elif self.triage_family != self.family_prediction_raw or self.queue_band not in {
            "review",
            "higher_score_review",
        }:
            raise PredictionContractError("attack review routing is inconsistent")
        if self.explanation_status == "available" and not self.top_contributions:
            raise PredictionContractError("available explanation requires contributions")
        if self.explanation_status != "available" and self.top_contributions:
            raise PredictionContractError("unavailable explanation cannot have contributions")


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def queue_band_for(
    binary_prediction: str,
    family_prediction: str,
    attack_model_score: float,
    *,
    config: dict | None = None,
) -> QueueBand:
    policy = load_workbench_config() if config is None else validate_workbench_config(config)
    if binary_prediction not in {"normal", "attack"}:
        raise PredictionContractError("unsupported binary prediction")
    if family_prediction not in ATTACK_FAMILIES:
        raise PredictionContractError("unsupported attack-family prediction")
    score = float(attack_model_score)
    if not np.isfinite(score) or not 0 <= score <= 1:
        raise PredictionContractError("attack_model_score must be between 0 and 1")
    if binary_prediction == "normal":
        return "not_alerted"
    if family_prediction == "normal":
        return "model_disagreement"
    if score >= policy["queue"]["higher_score_boundary"]:
        return "higher_score_review"
    return "review"


def _parse_event_time(value: object) -> str:
    if pd.isna(value) or not isinstance(value, str) or not value.strip():
        raise InputContractError("event_time contains a null or empty value")
    text = value.strip()
    compatible = f"{text[:-1]}+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(compatible)
    except ValueError as exc:
        raise InputContractError(f"event_time is not valid ISO 8601: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputContractError("event_time must include an explicit UTC offset")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_header(text: str) -> list[str]:
    try:
        header = next(csv.reader(io.StringIO(text), strict=True))
    except StopIteration as exc:
        raise InputContractError("CSV is empty") from exc
    except csv.Error as exc:
        raise InputContractError("CSV header is malformed") from exc
    duplicates = sorted(name for name, count in Counter(header).items() if count > 1)
    if duplicates:
        raise InputContractError(f"duplicate CSV columns: {duplicates}")
    return header


def _validate_columns(header: list[str]) -> None:
    actual = set(header)
    required = set(FEATURE_COLUMNS)
    allowed = required | set(OPTIONAL_COLUMNS)
    missing = sorted(required - actual)
    extra = sorted(actual - allowed)
    if missing or extra:
        raise InputContractError(
            f"inference schema mismatch; missing={missing}, extra={extra}"
        )


def _validate_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    validated = frame.copy()
    generated_ids = ID_COLUMN not in validated
    if generated_ids:
        width = max(6, len(str(len(validated))))
        validated.insert(
            0,
            ID_COLUMN,
            [f"record-{index:0{width}d}" for index in range(1, len(validated) + 1)],
        )
    else:
        if validated[ID_COLUMN].isna().any():
            raise InputContractError("id contains null values")
        validated[ID_COLUMN] = validated[ID_COLUMN].astype(str).str.strip()
        if validated[ID_COLUMN].eq("").any():
            raise InputContractError("id contains empty values")
        if validated[ID_COLUMN].duplicated().any():
            raise InputContractError("id must be unique")

    for column in CATEGORICAL_FEATURES:
        if validated[column].isna().any():
            raise InputContractError(f"{column} contains null values")
        validated[column] = validated[column].astype(str).str.strip()
        if validated[column].eq("").any():
            raise InputContractError(f"{column} contains empty values")

    try:
        validated[list(NUMERIC_FEATURES)] = validated[list(NUMERIC_FEATURES)].apply(
            pd.to_numeric, errors="raise"
        )
    except (TypeError, ValueError) as exc:
        raise InputContractError("numeric features contain non-numeric values") from exc
    try:
        numeric = validated.loc[:, NUMERIC_FEATURES].to_numpy(dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InputContractError("numeric features cannot be represented safely") from exc
    if not np.isfinite(numeric).all():
        raise InputContractError("numeric features must be non-null and finite")

    if EVENT_TIME_COLUMN in validated:
        validated[EVENT_TIME_COLUMN] = validated[EVENT_TIME_COLUMN].map(
            _parse_event_time
        )

    if BINARY_LABEL_COLUMN in validated:
        try:
            labels = pd.to_numeric(validated[BINARY_LABEL_COLUMN], errors="raise")
        except (TypeError, ValueError) as exc:
            raise InputContractError("label must contain only 0 or 1") from exc
        if labels.isna().any() or not labels.isin([0, 1]).all():
            raise InputContractError("label must contain only 0 or 1")
        validated[BINARY_LABEL_COLUMN] = labels.astype("int8")

    if ATTACK_FAMILY_COLUMN in validated:
        try:
            validated[ATTACK_FAMILY_COLUMN] = validated[ATTACK_FAMILY_COLUMN].map(
                normalize_attack_family
            )
        except ValueError as exc:
            raise InputContractError(str(exc)) from exc

    if {BINARY_LABEL_COLUMN, ATTACK_FAMILY_COLUMN}.issubset(validated):
        is_normal = validated[ATTACK_FAMILY_COLUMN].eq("normal")
        inconsistent = is_normal.ne(validated[BINARY_LABEL_COLUMN].eq(0))
        if inconsistent.any():
            ids = validated.loc[inconsistent, ID_COLUMN].head(5).tolist()
            raise InputContractError(f"attack_cat and label disagree for IDs {ids}")

    ordered = [ID_COLUMN]
    if EVENT_TIME_COLUMN in validated:
        ordered.append(EVENT_TIME_COLUMN)
    ordered.extend(FEATURE_COLUMNS)
    ordered.extend(
        column
        for column in (ATTACK_FAMILY_COLUMN, BINARY_LABEL_COLUMN)
        if column in validated
    )
    return validated.loc[:, ordered].copy(), generated_ids


def parse_inference_csv(
    payload: bytes,
    *,
    config: dict | None = None,
) -> InferenceInput:
    """Parse a bounded in-memory CSV without using its filename or filesystem."""
    policy = load_workbench_config() if config is None else validate_workbench_config(config)
    if not isinstance(payload, bytes):
        raise InputContractError("CSV payload must be bytes")
    if not payload:
        raise InputContractError("CSV is empty")
    if len(payload) > policy["input"]["max_upload_bytes"]:
        raise InputContractError("CSV exceeds the configured upload-size limit")
    if any(payload.startswith(magic) for magic in COMPRESSED_MAGIC):
        raise InputContractError("compressed or archived uploads are not accepted")
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise InputContractError("CSV must be valid UTF-8 text") from exc
    if "\x00" in text:
        raise InputContractError("CSV contains null bytes")

    header = _read_header(text)
    _validate_columns(header)
    try:
        frame = pd.read_csv(
            io.StringIO(text),
            encoding=policy["input"]["encoding"],
            nrows=policy["input"]["max_rows"] + 1,
            on_bad_lines="error",
        )
    except (pd.errors.ParserError, UnicodeError, ValueError) as exc:
        raise InputContractError("CSV body is malformed") from exc
    if frame.empty:
        raise InputContractError("CSV must contain at least one data row")
    if len(frame) > policy["input"]["max_rows"]:
        raise InputContractError("CSV exceeds the configured row limit")
    validated, generated_ids = _validate_frame(frame)
    return InferenceInput(
        frame=validated,
        input_sha256=hashlib.sha256(payload).hexdigest(),
        source_bytes=len(payload),
        generated_ids=generated_ids,
        has_event_time=EVENT_TIME_COLUMN in validated,
        has_binary_labels=BINARY_LABEL_COLUMN in validated,
        has_family_labels=ATTACK_FAMILY_COLUMN in validated,
    )
