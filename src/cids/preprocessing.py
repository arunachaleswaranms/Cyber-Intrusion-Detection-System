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
    NUMERIC_FEATURES,
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


def fit_preprocessor(splits: PreparedSplits) -> PreprocessingArtifact:
    """Fit categorical vocabulary exclusively from a prepared training split."""
    report = splits.report
    required_report_keys = {"task", "split_policy_version", "id_sha256"}
    if not required_report_keys.issubset(report):
        raise PreprocessingArtifactError("prepared split report is incomplete")

    training = validate_prepared_frame(splits.train)
    expected_digest = report["id_sha256"].get("train")
    actual_ids = "\n".join(str(value) for value in training["id"]).encode()
    actual_digest = hashlib.sha256(actual_ids).hexdigest()
    if actual_digest != expected_digest:
        raise PreprocessingArtifactError(
            "training IDs do not match the prepared split report"
        )

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
