"""Versioned schema contract for the prepared UNSW-NB15 CSV partitions."""

from __future__ import annotations

from collections.abc import Hashable

import pandas as pd

SCHEMA_VERSION = "unsw-nb15-prepared-v1"

ID_COLUMN = "id"
CATEGORICAL_FEATURES = ("proto", "service", "state")
NUMERIC_FEATURES = (
    "dur",
    "spkts",
    "dpkts",
    "sbytes",
    "dbytes",
    "rate",
    "sttl",
    "dttl",
    "sload",
    "dload",
    "sloss",
    "dloss",
    "sinpkt",
    "dinpkt",
    "sjit",
    "djit",
    "swin",
    "stcpb",
    "dtcpb",
    "dwin",
    "tcprtt",
    "synack",
    "ackdat",
    "smean",
    "dmean",
    "trans_depth",
    "response_body_len",
    "ct_srv_src",
    "ct_state_ttl",
    "ct_dst_ltm",
    "ct_src_dport_ltm",
    "ct_dst_sport_ltm",
    "ct_dst_src_ltm",
    "is_ftp_login",
    "ct_ftp_cmd",
    "ct_flw_http_mthd",
    "ct_src_ltm",
    "ct_srv_dst",
    "is_sm_ips_ports",
)
FEATURE_COLUMNS = (
    "dur",
    "proto",
    "service",
    "state",
    *NUMERIC_FEATURES[1:],
)
ATTACK_FAMILY_COLUMN = "attack_cat"
BINARY_LABEL_COLUMN = "label"
REQUIRED_COLUMNS = (
    ID_COLUMN,
    *FEATURE_COLUMNS,
    ATTACK_FAMILY_COLUMN,
    BINARY_LABEL_COLUMN,
)

ATTACK_FAMILIES = (
    "normal",
    "analysis",
    "backdoor",
    "dos",
    "exploits",
    "fuzzers",
    "generic",
    "reconnaissance",
    "shellcode",
    "worms",
)
_ATTACK_FAMILY_ALIASES = {
    family: family for family in ATTACK_FAMILIES
} | {"backdoors": "backdoor"}


class SchemaValidationError(ValueError):
    """Raised when a prepared UNSW-NB15 partition violates the contract."""


def normalize_attack_family(value: object) -> str:
    """Convert an official attack label to the project's canonical value."""
    if pd.isna(value):
        raise SchemaValidationError("attack_cat contains a null value")
    normalized = str(value).strip().casefold()
    try:
        return _ATTACK_FAMILY_ALIASES[normalized]
    except KeyError as exc:
        raise SchemaValidationError(f"unknown attack_cat value: {value!r}") from exc


def _require_unique_columns(columns: pd.Index) -> None:
    duplicates: list[Hashable] = columns[columns.duplicated()].tolist()
    if duplicates:
        raise SchemaValidationError(f"duplicate columns: {duplicates}")


def validate_prepared_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate, normalize, and order an official prepared CSV partition.

    The input frame is not mutated. Extra columns are rejected so schema drift
    cannot silently change training behavior.
    """
    _require_unique_columns(frame.columns)
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    extra = sorted(set(frame.columns) - set(REQUIRED_COLUMNS))
    if missing or extra:
        raise SchemaValidationError(
            f"schema mismatch for {SCHEMA_VERSION}; missing={missing}, extra={extra}"
        )

    validated = frame.loc[:, REQUIRED_COLUMNS].copy()
    if validated[ID_COLUMN].isna().any():
        raise SchemaValidationError("id contains null values")
    if validated[ID_COLUMN].duplicated().any():
        raise SchemaValidationError("id must be unique within each partition")

    for column in CATEGORICAL_FEATURES:
        if validated[column].isna().any():
            raise SchemaValidationError(f"{column} contains null values")
        validated[column] = validated[column].astype(str).str.strip()
        if validated[column].eq("").any():
            raise SchemaValidationError(f"{column} contains empty values")

    try:
        validated[list(NUMERIC_FEATURES)] = validated[list(NUMERIC_FEATURES)].apply(
            pd.to_numeric, errors="raise"
        )
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError("numeric features contain non-numeric values") from exc

    numeric = validated.loc[:, NUMERIC_FEATURES]
    if numeric.isna().any().any():
        raise SchemaValidationError("numeric features contain null values")
    if numeric.isin([float("inf"), float("-inf")]).any().any():
        raise SchemaValidationError("numeric features contain infinite values")

    try:
        labels = pd.to_numeric(validated[BINARY_LABEL_COLUMN], errors="raise")
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError("label must contain only 0 or 1") from exc
    if labels.isna().any() or not labels.isin([0, 1]).all():
        raise SchemaValidationError("label must contain only 0 or 1")
    validated[BINARY_LABEL_COLUMN] = labels.astype("int8")

    validated[ATTACK_FAMILY_COLUMN] = validated[ATTACK_FAMILY_COLUMN].map(
        normalize_attack_family
    )
    is_normal = validated[ATTACK_FAMILY_COLUMN].eq("normal")
    inconsistent = is_normal.ne(validated[BINARY_LABEL_COLUMN].eq(0))
    if inconsistent.any():
        row_ids = validated.loc[inconsistent, ID_COLUMN].head(5).tolist()
        raise SchemaValidationError(
            "attack_cat and label disagree for row IDs " f"{row_ids}"
        )

    return validated
