import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.datasets.split_unsw_nb15 import (  # noqa: E402
    SPLIT_POLICY_VERSION,
    SplitPreparationError,
    prepare_splits,
)
from cids.datasets.unsw_nb15 import (  # noqa: E402
    ATTACK_FAMILY_COLUMN,
    BINARY_LABEL_COLUMN,
    FEATURE_COLUMNS,
    ID_COLUMN,
    NUMERIC_FEATURES,
)


def row(row_id, feature_key, family="normal", label=0):
    values = {column: 0 for column in NUMERIC_FEATURES}
    values.update(
        {
            ID_COLUMN: row_id,
            "dur": feature_key,
            "proto": "tcp",
            "service": "-",
            "state": "FIN",
            ATTACK_FAMILY_COLUMN: family,
            BINARY_LABEL_COLUMN: label,
        }
    )
    return values


def frame(rows):
    return pd.DataFrame(rows)


def feature_keys(data):
    return set(map(tuple, data[list(FEATURE_COLUMNS)].itertuples(index=False, name=None)))


def test_binary_split_is_deterministic_and_leakage_resistant():
    official_train = frame(
        [
            row(1, 1),
            row(2, 2),
            row(3, 3),
            row(4, 4),
            row(5, 5, "generic", 1),
            row(6, 6, "generic", 1),
            row(7, 7, "exploits", 1),
            row(8, 8, "exploits", 1),
            row(9, 8, "exploits", 1),
            row(10, 9),
        ]
    )
    official_test = frame([row(1, 9), row(2, 10, "generic", 1)])

    first = prepare_splits(official_train, official_test, "binary", seed=42)
    second = prepare_splits(official_train, official_test, "binary", seed=42)

    assert first.report == second.report
    assert first.train[ID_COLUMN].tolist() == second.train[ID_COLUMN].tolist()
    assert feature_keys(first.train).isdisjoint(feature_keys(first.validation))
    assert feature_keys(first.train).isdisjoint(feature_keys(first.test))
    assert feature_keys(first.validation).isdisjoint(feature_keys(first.test))
    assert first.report["removed_from_training"] == {
        "official_test_overlap": 1,
        "conflicting_target_groups": 0,
        "conflicting_target_rows": 0,
        "redundant_feature_rows": 1,
    }
    assert SPLIT_POLICY_VERSION in first.report["split_policy_version"]


def test_conflicting_groups_are_target_specific():
    official_train = frame(
        [
            row(1, 1),
            row(2, 2),
            row(3, 3),
            row(4, 4),
            row(5, 5, "generic", 1),
            row(6, 5, "exploits", 1),
            row(7, 6, "generic", 1),
            row(8, 7, "exploits", 1),
            row(9, 8, "generic", 1),
            row(10, 9, "exploits", 1),
        ]
    )
    official_test = frame([row(1, 20), row(2, 21, "generic", 1)])

    binary = prepare_splits(official_train, official_test, "binary")
    multiclass = prepare_splits(official_train, official_test, "multiclass")

    assert binary.report["removed_from_training"]["conflicting_target_rows"] == 0
    assert multiclass.report["removed_from_training"]["conflicting_target_rows"] == 2


def test_official_test_and_inputs_are_not_modified():
    official_train = frame(
        [row(1, 1), row(2, 2), row(3, 3, "generic", 1), row(4, 4, "generic", 1)]
    )
    official_test = frame([row(1, 20), row(2, 20)])
    original_train = official_train.copy(deep=True)
    original_test = official_test.copy(deep=True)

    prepared = prepare_splits(official_train, official_test, "binary")

    pd.testing.assert_frame_equal(official_train, original_train)
    pd.testing.assert_frame_equal(official_test, original_test)
    assert len(prepared.test) == len(official_test)
    assert prepared.report["official_test_diagnostics"]["redundant_feature_rows"] == 1


@pytest.mark.parametrize("fraction", [0, 1, -0.1, 1.1])
def test_rejects_invalid_validation_fraction(fraction):
    official_train = frame(
        [row(1, 1), row(2, 2), row(3, 3, "generic", 1), row(4, 4, "generic", 1)]
    )
    official_test = frame([row(1, 20), row(2, 21, "generic", 1)])

    with pytest.raises(SplitPreparationError, match="between 0 and 1"):
        prepare_splits(
            official_train, official_test, "binary", validation_fraction=fraction
        )
