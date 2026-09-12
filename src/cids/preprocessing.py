"""Train-only preprocessing for the UNSW-NB15 v2.0 baseline."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.utils.validation import check_is_fitted

from cids.datasets.split_unsw_nb15 import PreparedSplits
from cids.datasets.unsw_nb15 import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    ID_COLUMN,
    NUMERIC_FEATURES,
    REQUIRED_COLUMNS,
    SCHEMA_VERSION,
    validate_prepared_frame,
)

PREPROCESSOR_VERSION = "unsw-nb15-preprocessor-v1"


class PreprocessingArtifactError(ValueError):
    """Raised when a preprocessing artifact is incompatible or invalid."""


@dataclass
class PreprocessingArtifact:
    version: str
    schema_version: str
    task: str
    transformer: ColumnTransformer
    metadata: dict


def _build_transformer() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("numeric", "passthrough", list(NUMERIC_FEATURES)),
            (
                "categorical",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=True,
                    dtype=np.float32,
                ),
                list(CATEGORICAL_FEATURES),
            ),
        ],
        sparse_threshold=0.3,
        verbose_feature_names_out=False,
    )


def _names_digest(names: list[str]) -> str:
    return hashlib.sha256("\n".join(names).encode()).hexdigest()


def _id_digest(frame: pd.DataFrame) -> str:
    values = "\n".join(str(value) for value in frame[ID_COLUMN]).encode()
    return hashlib.sha256(values).hexdigest()


def _validate_training_subset(
    source_training: pd.DataFrame, candidate: pd.DataFrame
) -> pd.DataFrame:
    source_ids = set(source_training[ID_COLUMN])
    if not set(candidate[ID_COLUMN]).issubset(source_ids):
        raise PreprocessingArtifactError(
            "preprocessor training subset contains IDs outside prepared training"
        )
    source_by_id = source_training.set_index(ID_COLUMN, drop=False)
    expected = source_by_id.loc[candidate[ID_COLUMN]].reset_index(drop=True)
    if not expected.loc[:, REQUIRED_COLUMNS].equals(
        candidate.loc[:, REQUIRED_COLUMNS].reset_index(drop=True)
    ):
        raise PreprocessingArtifactError(
            "preprocessor training subset does not match prepared training rows"
        )
    return candidate.reset_index(drop=True)


def fit_preprocessor(
    splits: PreparedSplits,
    *,
    training_frame: pd.DataFrame | None = None,
    training_scope: str = "prepared_train",
) -> PreprocessingArtifact:
    """Fit vocabulary on all or a verified subset of prepared training data."""
    report = splits.report
    required_report_keys = {"task", "split_policy_version", "id_sha256"}
    if not required_report_keys.issubset(report):
        raise PreprocessingArtifactError("prepared split report is incomplete")

    source_training = validate_prepared_frame(splits.train)
    expected_digest = report["id_sha256"].get("train")
    source_digest = _id_digest(source_training)
    if source_digest != expected_digest:
        raise PreprocessingArtifactError(
            "training IDs do not match the prepared split report"
        )
    if training_frame is None:
        if training_scope != "prepared_train":
            raise PreprocessingArtifactError(
                "custom training_scope requires an explicit training subset"
            )
        training = source_training
    else:
        if not training_scope or training_scope == "prepared_train":
            raise PreprocessingArtifactError(
                "training subset requires a distinct non-empty training_scope"
            )
        candidate = validate_prepared_frame(training_frame)
        training = _validate_training_subset(source_training, candidate)
    actual_digest = _id_digest(training)

    transformer = _build_transformer()
    transformer.fit(training.loc[:, FEATURE_COLUMNS])
    output_names = transformer.get_feature_names_out().tolist()
    categorical = transformer.named_transformers_["categorical"]
    category_counts = {
        column: len(values)
        for column, values in zip(CATEGORICAL_FEATURES, categorical.categories_)
    }
    metadata = {
        "preprocessor_version": PREPROCESSOR_VERSION,
        "schema_version": SCHEMA_VERSION,
        "task": report["task"],
        "split_policy_version": report["split_policy_version"],
        "training_scope": training_scope,
        "source_training_rows": len(source_training),
        "source_training_id_sha256": source_digest,
        "training_rows": len(training),
        "training_id_sha256": actual_digest,
        "input_feature_count": len(FEATURE_COLUMNS),
        "output_feature_count": len(output_names),
        "output_feature_names_sha256": _names_digest(output_names),
        "categorical_vocabulary_sizes": category_counts,
    }
    return PreprocessingArtifact(
        version=PREPROCESSOR_VERSION,
        schema_version=SCHEMA_VERSION,
        task=report["task"],
        transformer=transformer,
        metadata=metadata,
    )


def transform_partition(
    artifact: PreprocessingArtifact, frame: pd.DataFrame
) -> np.ndarray | sparse.spmatrix:
    validate_artifact(artifact)
    validated = validate_prepared_frame(frame)
    return artifact.transformer.transform(validated.loc[:, FEATURE_COLUMNS])


def output_feature_names(artifact: PreprocessingArtifact) -> list[str]:
    validate_artifact(artifact)
    return artifact.transformer.get_feature_names_out().tolist()


def validate_artifact(artifact: object) -> None:
    if not isinstance(artifact, PreprocessingArtifact):
        raise PreprocessingArtifactError("not a CIDS preprocessing artifact")
    if artifact.version != PREPROCESSOR_VERSION:
        raise PreprocessingArtifactError(
            f"unsupported preprocessor version: {artifact.version!r}"
        )
    if artifact.schema_version != SCHEMA_VERSION:
        raise PreprocessingArtifactError(
            f"artifact schema must be {SCHEMA_VERSION!r}"
        )
    check_is_fitted(artifact.transformer)
    names = artifact.transformer.get_feature_names_out().tolist()
    if _names_digest(names) != artifact.metadata.get("output_feature_names_sha256"):
        raise PreprocessingArtifactError("output feature-name digest mismatch")


def save_artifact(artifact: PreprocessingArtifact, path: str | Path) -> Path:
    validate_artifact(artifact)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output)
    return output


def load_artifact(path: str | Path) -> PreprocessingArtifact:
    """Load a trusted local artifact. Never load untrusted joblib files."""
    artifact = joblib.load(Path(path))
    validate_artifact(artifact)
    return artifact
