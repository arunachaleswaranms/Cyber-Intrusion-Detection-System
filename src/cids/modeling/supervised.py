"""Reproducible supervised tree baselines for UNSW-NB15."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Literal

import joblib
import numpy as np
import sklearn
from scipy import sparse
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.utils.validation import check_is_fitted

from cids.config import (
    config_sha256,
    load_experiment_config,
    validate_experiment_config,
    validate_split_report,
)
from cids.datasets.split_unsw_nb15 import (
    PreparedSplits,
    target_for_task,
)
from cids.datasets.unsw_nb15 import ATTACK_FAMILY_COLUMN, SCHEMA_VERSION
from cids.evaluation import evaluate_classifier
from cids.preprocessing import (
    PreprocessingArtifact,
    fit_preprocessor,
    transform_partition,
    validate_artifact as validate_preprocessor,
)

MODEL_ARTIFACT_VERSION = "unsw-nb15-supervised-v1"
ModelName = Literal["random_forest", "hist_gradient_boosting"]
SUPPORTED_MODELS: tuple[ModelName, ...] = (
    "random_forest",
    "hist_gradient_boosting",
)


class ModelArtifactError(ValueError):
    """Raised when a supervised model artifact is incompatible or invalid."""


@dataclass
class SupervisedModelArtifact:
    version: str
    schema_version: str
    task: str
    model_name: str
    requires_dense: bool
    preprocessor: PreprocessingArtifact
    estimator: object
    metadata: dict


@dataclass(frozen=True)
class TrainingResult:
    artifact: SupervisedModelArtifact
    validation_metrics: dict


def build_estimator(model_name: ModelName, parameters: dict, seed: int):
    effective_parameters = {**parameters, "random_state": seed}
    if model_name == "random_forest":
        return RandomForestClassifier(**effective_parameters)
    if model_name == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(**effective_parameters)
    raise ModelArtifactError(f"unsupported model: {model_name!r}")


def _requires_dense(model_name: str) -> bool:
    return model_name == "hist_gradient_boosting"


def model_features_for_estimator(model_name: str, matrix):
    if _requires_dense(model_name):
        return matrix.toarray() if sparse.issparse(matrix) else np.asarray(matrix)
    return matrix


def train_and_validate(
    splits: PreparedSplits,
    model_name: ModelName,
    *,
    config: dict | None = None,
) -> TrainingResult:
    """Fit on prepared training data and score only prepared validation data.

    The official test frame in ``splits`` is deliberately never accessed here.
    """
    if model_name not in SUPPORTED_MODELS:
        raise ModelArtifactError(f"unsupported model: {model_name!r}")
    experiment_config = (
        load_experiment_config()
        if config is None
        else validate_experiment_config(config)
    )
    validate_split_report(experiment_config, splits.report)
    seed = experiment_config["split"]["seed"]
    task = splits.report.get("task")
    target_column = target_for_task(task)
    preprocessor = fit_preprocessor(splits)
    training_features = model_features_for_estimator(
        model_name, transform_partition(preprocessor, splits.train)
    )
    validation_features = model_features_for_estimator(
        model_name, transform_partition(preprocessor, splits.validation)
    )
    training_target = splits.train[target_column]
    validation_target = splits.validation[target_column]

    estimator = build_estimator(
        model_name,
        experiment_config["models"]["supervised"][model_name],
        seed,
    )
    started = perf_counter()
    estimator.fit(training_features, training_target)
    fit_seconds = perf_counter() - started
    validation_metrics = evaluate_classifier(
        estimator,
        validation_features,
        validation_target,
        task=task,
        family_labels=splits.validation[ATTACK_FAMILY_COLUMN],
    )
    metadata = {
        "artifact_version": MODEL_ARTIFACT_VERSION,
        "experiment_config_version": experiment_config["config_version"],
        "experiment_config_sha256": config_sha256(experiment_config),
        "schema_version": SCHEMA_VERSION,
        "split_policy_version": splits.report["split_policy_version"],
        "task": task,
        "model_name": model_name,
        "seed": seed,
        "estimator_class": type(estimator).__name__,
        "estimator_parameters": estimator.get_params(deep=False),
        "training_rows": len(splits.train),
        "validation_rows": len(splits.validation),
        "training_id_sha256": splits.report["id_sha256"]["train"],
        "validation_id_sha256": splits.report["id_sha256"]["validation"],
        "official_test_id_sha256": splits.report["id_sha256"]["official_test"],
        "official_test_status": "sealed_not_evaluated",
        "fit_seconds": fit_seconds,
        "class_labels": [
            value.item() if isinstance(value, np.generic) else value
            for value in estimator.classes_
        ],
        "library_versions": {
            "joblib": joblib.__version__,
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "preprocessor": preprocessor.metadata,
    }
    artifact = SupervisedModelArtifact(
        version=MODEL_ARTIFACT_VERSION,
        schema_version=SCHEMA_VERSION,
        task=task,
        model_name=model_name,
        requires_dense=_requires_dense(model_name),
        preprocessor=preprocessor,
        estimator=estimator,
        metadata=metadata,
    )
    validate_artifact(artifact)
    return TrainingResult(artifact=artifact, validation_metrics=validation_metrics)


def validate_artifact(artifact: object) -> None:
    if not isinstance(artifact, SupervisedModelArtifact):
        raise ModelArtifactError("not a CIDS supervised model artifact")
    if artifact.version != MODEL_ARTIFACT_VERSION:
        raise ModelArtifactError(f"unsupported artifact version: {artifact.version!r}")
    if artifact.schema_version != SCHEMA_VERSION:
        raise ModelArtifactError(f"artifact schema must be {SCHEMA_VERSION!r}")
    if artifact.model_name not in SUPPORTED_MODELS:
        raise ModelArtifactError(f"unsupported model: {artifact.model_name!r}")
    if artifact.requires_dense != _requires_dense(artifact.model_name):
        raise ModelArtifactError("artifact feature representation is inconsistent")
    if artifact.task != artifact.preprocessor.task:
        raise ModelArtifactError("model and preprocessor tasks do not match")
    if artifact.metadata.get("official_test_status") != "sealed_not_evaluated":
        raise ModelArtifactError("artifact does not preserve the official test seal")
    validate_preprocessor(artifact.preprocessor)
    check_is_fitted(artifact.estimator)


def predict(artifact: SupervisedModelArtifact, frame) -> np.ndarray:
    validate_artifact(artifact)
    features = transform_partition(artifact.preprocessor, frame)
    return np.asarray(
        artifact.estimator.predict(
            model_features_for_estimator(artifact.model_name, features)
        )
    )


def save_artifact(artifact: SupervisedModelArtifact, path: str | Path) -> Path:
    validate_artifact(artifact)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output)
    return output


def load_artifact(path: str | Path) -> SupervisedModelArtifact:
    """Load a trusted local artifact. Never load untrusted joblib files."""
    artifact = joblib.load(Path(path))
    validate_artifact(artifact)
    return artifact
