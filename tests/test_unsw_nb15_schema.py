import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.datasets.unsw_nb15 import (  # noqa: E402
    ATTACK_FAMILIES,
    ATTACK_FAMILY_COLUMN,
    BINARY_LABEL_COLUMN,
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    ID_COLUMN,
    NUMERIC_FEATURES,
    REQUIRED_COLUMNS,
    SCHEMA_VERSION,
    SchemaValidationError,
    validate_prepared_frame,
)


def valid_row(**overrides):
    row = {column: 0 for column in NUMERIC_FEATURES}
    row.update(
        {
            ID_COLUMN: 1,
            "proto": "tcp",
            "service": "-",
            "state": "FIN",
            ATTACK_FAMILY_COLUMN: "Normal",
            BINARY_LABEL_COLUMN: 0,
        }
    )
    row.update(overrides)
    return row


def test_schema_contract_has_expected_shape():
    assert SCHEMA_VERSION == "unsw-nb15-prepared-v1"
    assert len(FEATURE_COLUMNS) == 42
    assert len(NUMERIC_FEATURES) == 39
    assert len(CATEGORICAL_FEATURES) == 3
    assert len(REQUIRED_COLUMNS) == 45
    assert len(ATTACK_FAMILIES) == 10


def test_validation_normalizes_columns_without_mutating_input():
    frame = pd.DataFrame(
        [valid_row(attack_cat=" Backdoors ", label=1, service="  http ")]
    )[list(reversed(REQUIRED_COLUMNS))]

    validated = validate_prepared_frame(frame)

    assert list(validated.columns) == list(REQUIRED_COLUMNS)
    assert validated.loc[0, ATTACK_FAMILY_COLUMN] == "backdoor"
    assert validated.loc[0, "service"] == "http"
    assert frame.loc[0, ATTACK_FAMILY_COLUMN] == " Backdoors "


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"attack_cat": "Normal", "label": 1}, "disagree"),
        ({"attack_cat": "unknown", "label": 1}, "unknown attack_cat"),
        ({"label": 2}, "only 0 or 1"),
        ({"sbytes": float("inf")}, "infinite"),
        ({"proto": None}, "proto contains null"),
    ],
)
def test_validation_rejects_invalid_records(change, message):
    with pytest.raises(SchemaValidationError, match=message):
        validate_prepared_frame(pd.DataFrame([valid_row(**change)]))


def test_validation_rejects_schema_drift_and_duplicate_ids():
    missing_column = pd.DataFrame([valid_row()]).drop(columns="rate")
    with pytest.raises(SchemaValidationError, match="missing=.*rate"):
        validate_prepared_frame(missing_column)

    duplicates = pd.DataFrame([valid_row(), valid_row()])
    with pytest.raises(SchemaValidationError, match="id must be unique"):
        validate_prepared_frame(duplicates)
