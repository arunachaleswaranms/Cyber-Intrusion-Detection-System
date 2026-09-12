import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.datasets.split_unsw_nb15 import prepare_splits  # noqa: E402
from cids.datasets.unsw_nb15 import (  # noqa: E402
    ATTACK_FAMILY_COLUMN,
    BINARY_LABEL_COLUMN,
    ID_COLUMN,
    NUMERIC_FEATURES,
)
from cids.final_evaluation import (  # noqa: E402
    FINAL_MODEL_ARTIFACT_VERSION,
    load_artifact,
    predict,
    save_artifact,
    train_and_evaluate_selected,
)


def row(row_id, duration, family="normal", label=0, proto="tcp"):
    values = {column: 0 for column in NUMERIC_FEATURES}
    values.update(
        {
            ID_COLUMN: row_id,
            "dur": duration,
            "proto": proto,
            "service": "-",
            "state": "FIN",
            ATTACK_FAMILY_COLUMN: family,
            BINARY_LABEL_COLUMN: label,
        }
    )
    return values


def make_splits(task):
    training_rows = [row(index, index) for index in range(1, 11)]
    training_rows.extend(
        row(index, index, "generic", 1, "udp") for index in range(11, 21)
    )
    training_rows.extend(
        row(index, index, "exploits", 1, "udp") for index in range(21, 31)
    )
    testing = pd.DataFrame(
        [
            row(1, 101),
            row(2, 102),
            row(3, 103, "generic", 1, "udp"),
            row(4, 104, "generic", 1, "udp"),
            row(5, 105, "exploits", 1, "udp"),
            row(6, 106, "exploits", 1, "udp"),
        ]
    )
    return prepare_splits(
        pd.DataFrame(training_rows),
        testing,
        task,
        validation_fraction=0.20,
    )


@pytest.mark.parametrize("task", ["binary", "multiclass"])
def test_retrains_selected_model_on_combined_development_before_test(task):
    splits = make_splits(task)

    result = train_and_evaluate_selected(splits)
    expected_training_rows = len(splits.train) + len(splits.validation)

    assert result.artifact.version == FINAL_MODEL_ARTIFACT_VERSION
    assert result.artifact.model_name == "hist_gradient_boosting"
    assert result.artifact.metadata["training_scope"] == (
        "prepared_train_plus_validation"
    )
    assert result.artifact.metadata["development_training_rows"] == (
        expected_training_rows
    )
    assert result.artifact.preprocessor.metadata["training_rows"] == (
        expected_training_rows
    )
    assert result.artifact.metadata["official_test_status"] == "evaluated_once"
    assert result.official_test_metrics["samples"] == len(splits.test)


def test_final_artifact_round_trip_preserves_predictions(tmp_path):
    splits = make_splits("binary")
    result = train_and_evaluate_selected(splits)
    before = predict(result.artifact, splits.test)

    path = save_artifact(result.artifact, tmp_path / "final.joblib")
    restored = load_artifact(path)

    np.testing.assert_array_equal(before, predict(restored, splits.test))
