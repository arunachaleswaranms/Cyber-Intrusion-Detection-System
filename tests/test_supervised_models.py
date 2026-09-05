import sys
from dataclasses import replace
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
from cids.modeling.supervised import (  # noqa: E402
    MODEL_ARTIFACT_VERSION,
    SUPPORTED_MODELS,
    ModelArtifactError,
    load_artifact,
    predict,
    save_artifact,
    train_and_validate,
    validate_artifact,
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


def make_splits(task="binary"):
    training = pd.DataFrame(
        [
            row(1, 1),
            row(2, 2),
            row(3, 3),
            row(4, 4),
            row(5, 5),
            row(6, 6),
            row(7, 7, "generic", 1, "udp"),
            row(8, 8, "generic", 1, "udp"),
            row(9, 9, "generic", 1, "udp"),
            row(10, 10, "generic", 1, "udp"),
            row(11, 11, "exploits", 1),
            row(12, 12, "exploits", 1),
            row(13, 13, "exploits", 1),
            row(14, 14, "exploits", 1),
        ]
    )
    testing = pd.DataFrame(
        [
            row(1, 101),
            row(2, 102, "generic", 1),
            row(3, 103, "exploits", 1),
        ]
    )
    return prepare_splits(training, testing, task, validation_fraction=0.25)


@pytest.mark.parametrize("model_name", SUPPORTED_MODELS)
def test_trains_supported_models_without_accessing_official_test(model_name):
    splits = replace(make_splits(), test=object())

    result = train_and_validate(splits, model_name)

    assert result.artifact.version == MODEL_ARTIFACT_VERSION
    assert result.artifact.metadata["official_test_status"] == "sealed_not_evaluated"
    assert result.artifact.metadata["training_rows"] == len(splits.train)
    assert result.validation_metrics["samples"] == len(splits.validation)
    observed_attack_families = set(splits.validation[ATTACK_FAMILY_COLUMN]) - {
        "normal"
    }
    assert set(result.validation_metrics["per_family_detection_rate"]) == (
        observed_attack_families
    )


def test_model_artifact_round_trip_preserves_predictions(tmp_path):
    splits = make_splits()
    result = train_and_validate(splits, "random_forest")
    before = predict(result.artifact, splits.validation)

    path = save_artifact(result.artifact, tmp_path / "model.joblib")
    restored = load_artifact(path)

    np.testing.assert_array_equal(before, predict(restored, splits.validation))
    assert restored.metadata["training_id_sha256"] == splits.report["id_sha256"]["train"]


@pytest.mark.parametrize("model_name", SUPPORTED_MODELS)
def test_seeded_training_is_deterministic(model_name):
    splits = make_splits()

    first = train_and_validate(splits, model_name, seed=42)
    second = train_and_validate(splits, model_name, seed=42)

    np.testing.assert_array_equal(
        predict(first.artifact, splits.validation),
        predict(second.artifact, splits.validation),
    )


def test_rejects_artifact_with_changed_test_status():
    artifact = train_and_validate(make_splits(), "random_forest").artifact
    artifact.metadata["official_test_status"] = "evaluated"

    with pytest.raises(ModelArtifactError, match="test seal"):
        validate_artifact(artifact)
