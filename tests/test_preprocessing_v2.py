import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.datasets.split_unsw_nb15 import prepare_splits  # noqa: E402
from cids.datasets.unsw_nb15 import (  # noqa: E402
    ATTACK_FAMILY_COLUMN,
    BINARY_LABEL_COLUMN,
    ID_COLUMN,
    NUMERIC_FEATURES,
)
from cids.preprocessing import (  # noqa: E402
    PREPROCESSOR_VERSION,
    PreprocessingArtifactError,
    fit_preprocessor,
    load_artifact,
    output_feature_names,
    save_artifact,
    transform_partition,
)


def row(
    row_id,
    duration,
    family="normal",
    label=0,
    proto="tcp",
    service="http",
    state="FIN",
):
    values = {column: 0 for column in NUMERIC_FEATURES}
    values.update(
        {
            ID_COLUMN: row_id,
            "dur": duration,
            "proto": proto,
            "service": service,
            "state": state,
            ATTACK_FAMILY_COLUMN: family,
            BINARY_LABEL_COLUMN: label,
        }
    )
    return values


def make_splits():
    training = pd.DataFrame(
        [
            row(1, 1),
            row(2, 2),
            row(3, 3, proto="udp"),
            row(4, 4, proto="udp"),
            row(5, 5, "generic", 1, service="dns"),
            row(6, 6, "generic", 1, service="dns"),
            row(7, 7, "exploits", 1, state="CON"),
            row(8, 8, "exploits", 1, state="CON"),
        ]
    )
    testing = pd.DataFrame(
        [
            row(1, 20, proto="icmp", service="smtp", state="RST"),
            row(2, 21, "generic", 1, proto="icmp", service="smtp", state="RST"),
        ]
    )
    return prepare_splits(training, testing, "binary", validation_fraction=0.25)


def dense(matrix):
    return matrix.toarray() if sparse.issparse(matrix) else np.asarray(matrix)


def test_fits_vocabulary_only_from_training_partition():
    splits = make_splits()
    artifact = fit_preprocessor(splits)
    encoder = artifact.transformer.named_transformers_["categorical"]

    observed = [set(values) for values in encoder.categories_]
    training = splits.train

    assert observed == [
        set(training["proto"]),
        set(training["service"]),
        set(training["state"]),
    ]
    assert "icmp" not in observed[0]
    assert "smtp" not in observed[1]
    assert "RST" not in observed[2]
    assert artifact.version == PREPROCESSOR_VERSION
    assert artifact.metadata["training_rows"] == len(training)
    assert artifact.metadata["training_id_sha256"] == splits.report["id_sha256"]["train"]


def test_transforms_unseen_categories_without_expanding_output():
    splits = make_splits()
    artifact = fit_preprocessor(splits)

    train_matrix = transform_partition(artifact, splits.train)
    test_matrix = transform_partition(artifact, splits.test)

    assert train_matrix.shape[1] == test_matrix.shape[1]
    assert train_matrix.shape[1] == artifact.metadata["output_feature_count"]
    categorical_start = len(NUMERIC_FEATURES)
    assert np.all(dense(test_matrix)[:, categorical_start:] == 0)


def test_feature_names_exclude_identifiers_and_targets():
    artifact = fit_preprocessor(make_splits())
    names = output_feature_names(artifact)

    assert len(names) == len(set(names))
    assert ID_COLUMN not in names
    assert ATTACK_FAMILY_COLUMN not in names
    assert BINARY_LABEL_COLUMN not in names
    assert names[: len(NUMERIC_FEATURES)] == list(NUMERIC_FEATURES)


def test_serialization_round_trip_preserves_output(tmp_path):
    splits = make_splits()
    artifact = fit_preprocessor(splits)
    before = dense(transform_partition(artifact, splits.validation))
    path = save_artifact(artifact, tmp_path / "preprocessor.joblib")

    restored = load_artifact(path)
    after = dense(transform_partition(restored, splits.validation))

    np.testing.assert_array_equal(before, after)
    assert restored.metadata == artifact.metadata


def test_rejects_training_frame_not_matching_split_report():
    splits = make_splits()
    splits.train.loc[0, ID_COLUMN] = 999

    with pytest.raises(PreprocessingArtifactError, match="training IDs"):
        fit_preprocessor(splits)
