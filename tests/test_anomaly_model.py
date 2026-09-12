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
from cids.modeling.anomaly import (  # noqa: E402
    ANOMALY_ARTIFACT_VERSION,
    AnomalyArtifactError,
    load_artifact,
    predict,
    save_artifact,
    score_anomalies,
    train_and_validate_anomaly,
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
    training_rows = [row(index, index) for index in range(1, 11)]
    training_rows.extend(
        row(index, index, "generic", 1, "udp") for index in range(11, 17)
    )
    training_rows.extend(
        row(index, index, "exploits", 1, "udp") for index in range(17, 23)
    )
    testing = pd.DataFrame(
        [
            row(1, 101),
            row(2, 102, "generic", 1, "udp"),
            row(3, 103, "exploits", 1, "udp"),
        ]
    )
    return prepare_splits(
        pd.DataFrame(training_rows),
        testing,
        task,
        validation_fraction=0.20,
    )


def test_trains_only_on_normal_rows_without_accessing_official_test():
    splits = replace(make_splits(), test=object())

    result = train_and_validate_anomaly(splits)
    encoder = result.artifact.preprocessor.transformer.named_transformers_[
        "categorical"
    ]

    assert result.artifact.version == ANOMALY_ARTIFACT_VERSION
    assert result.artifact.metadata["official_test_status"] == "sealed_not_evaluated"
    assert result.artifact.metadata["training_scope"] == "normal_only"
    assert result.artifact.metadata["normal_training_rows"] == int(
        splits.train[BINARY_LABEL_COLUMN].eq(0).sum()
    )
    assert set(encoder.categories_[0]) == {"tcp"}
    assert result.validation_metrics["samples"] == len(splits.validation)


def test_anomaly_artifact_round_trip_preserves_scores_and_predictions(tmp_path):
    splits = make_splits()
    result = train_and_validate_anomaly(splits)
    before_scores = score_anomalies(result.artifact, splits.validation)
    before_predictions = predict(result.artifact, splits.validation)

    path = save_artifact(result.artifact, tmp_path / "isolation_forest.joblib")
    restored = load_artifact(path)

    np.testing.assert_array_equal(
        before_scores,
        score_anomalies(restored, splits.validation),
    )
    np.testing.assert_array_equal(
        before_predictions,
        predict(restored, splits.validation),
    )


def test_anomaly_training_is_deterministic():
    splits = make_splits()

    first = train_and_validate_anomaly(splits)
    second = train_and_validate_anomaly(splits)

    assert first.artifact.threshold == second.artifact.threshold
    np.testing.assert_array_equal(
        predict(first.artifact, splits.validation),
        predict(second.artifact, splits.validation),
    )


def test_rejects_multiclass_splits():
    with pytest.raises(AnomalyArtifactError, match="requires binary"):
        train_and_validate_anomaly(make_splits("multiclass"))
