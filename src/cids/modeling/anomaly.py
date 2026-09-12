"""Normal-only Isolation Forest baseline for binary intrusion detection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.utils.validation import check_is_fitted

from cids.config import (
    ANOMALY_MODEL_NAME,
    config_sha256,
    load_experiment_config,
    validate_experiment_config,
    validate_split_report,
)
from cids.datasets.split_unsw_nb15 import PreparedSplits
from cids.datasets.unsw_nb15 import (
    ATTACK_FAMILY_COLUMN,
    BINARY_LABEL_COLUMN,
    SCHEMA_VERSION,
)
from cids.evaluation import evaluate_binary_detector
from cids.preprocessing import (
    PreprocessingArtifact,
    fit_preprocessor,
    transform_partition,
    validate_artifact as validate_preprocessor,
)

ANOMALY_ARTIFACT_VERSION = "unsw-nb15-isolation-forest-v1"


class AnomalyArtifactError(ValueError):
    """Raised when an anomaly artifact or training request is invalid."""


@dataclass
class AnomalyModelArtifact:
    version: str
    schema_version: str
    task: str
    model_name: str
    preprocessor: PreprocessingArtifact
    estimator: IsolationForest
    threshold: float
    metadata: dict


@dataclass(frozen=True)
class AnomalyTrainingResult:
    artifact: AnomalyModelArtifact
    validation_metrics: dict


def _anomaly_scores(estimator: IsolationForest, features) -> np.ndarray:
    return -np.asarray(estimator.score_samples(features))


def train_and_validate_anomaly(
    splits: PreparedSplits,
    *,
    config: dict | None = None,
) -> AnomalyTrainingResult:
    """Fit only normal training rows and evaluate only binary validation rows."""
    experiment_config = (
        load_experiment_config()
        if config is None
        else validate_experiment_config(config)
    )
    validate_split_report(experiment_config, splits.report)
    if splits.report.get("task") != "binary":
        raise AnomalyArtifactError("Isolation Forest baseline requires binary splits")

    model_config = experiment_config["models"]["anomaly"]
    normal_training = splits.train.loc[
        splits.train[BINARY_LABEL_COLUMN].eq(0)
    ].copy()
    if normal_training.empty:
        raise AnomalyArtifactError("normal-only training partition is empty")
    preprocessor = fit_preprocessor(
        splits,
        training_frame=normal_training,
        training_scope=model_config["training_scope"],
    )
    training_features = transform_partition(preprocessor, normal_training)
    validation_features = transform_partition(preprocessor, splits.validation)

    seed = experiment_config["split"]["seed"]
    estimator = IsolationForest(
        **model_config["parameters"],
        random_state=seed,
    )
    started = perf_counter()
    estimator.fit(training_features)
    fit_seconds = perf_counter() - started

    normal_training_scores = _anomaly_scores(estimator, training_features)
    quantile = model_config["threshold"]["normal_training_quantile"]
    threshold = float(np.quantile(normal_training_scores, quantile, method="higher"))
    estimator.score_samples(validation_features[: min(len(splits.validation), 256)])
    started = perf_counter()
    validation_scores = _anomaly_scores(estimator, validation_features)
    predictions = (validation_scores >= threshold).astype("int8")
    prediction_seconds = perf_counter() - started
    validation_metrics = evaluate_binary_detector(
        predictions,
        validation_scores,
        splits.validation[BINARY_LABEL_COLUMN],
        family_labels=splits.validation[ATTACK_FAMILY_COLUMN],
        prediction_seconds=prediction_seconds,
    )

    metadata = {
        "artifact_version": ANOMALY_ARTIFACT_VERSION,
        "experiment_config_version": experiment_config["config_version"],
        "experiment_config_sha256": config_sha256(experiment_config),
        "schema_version": SCHEMA_VERSION,
        "split_policy_version": splits.report["split_policy_version"],
        "task": "binary",
        "model_name": ANOMALY_MODEL_NAME,
        "seed": seed,
        "estimator_class": type(estimator).__name__,
        "estimator_parameters": estimator.get_params(deep=False),
        "training_scope": model_config["training_scope"],
        "source_training_rows": len(splits.train),
        "normal_training_rows": len(normal_training),
        "normal_training_id_sha256": preprocessor.metadata["training_id_sha256"],
        "validation_rows": len(splits.validation),
        "validation_id_sha256": splits.report["id_sha256"]["validation"],
        "official_test_id_sha256": splits.report["id_sha256"]["official_test"],
        "official_test_status": "sealed_not_evaluated",
        "threshold_strategy": model_config["threshold"]["strategy"],
        "normal_training_quantile": quantile,
        "threshold": threshold,
        "normal_training_alert_rate": float(
            np.mean(normal_training_scores >= threshold)
        ),
        "fit_seconds": fit_seconds,
        "library_versions": {
            "joblib": joblib.__version__,
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "preprocessor": preprocessor.metadata,
    }
    artifact = AnomalyModelArtifact(
        version=ANOMALY_ARTIFACT_VERSION,
        schema_version=SCHEMA_VERSION,
        task="binary",
        model_name=ANOMALY_MODEL_NAME,
        preprocessor=preprocessor,
        estimator=estimator,
        threshold=threshold,
        metadata=metadata,
    )
    validate_artifact(artifact)
    return AnomalyTrainingResult(
        artifact=artifact,
        validation_metrics=validation_metrics,
    )


def validate_artifact(artifact: object) -> None:
    if not isinstance(artifact, AnomalyModelArtifact):
        raise AnomalyArtifactError("not a CIDS anomaly model artifact")
    if artifact.version != ANOMALY_ARTIFACT_VERSION:
        raise AnomalyArtifactError(f"unsupported artifact version: {artifact.version!r}")
    if artifact.schema_version != SCHEMA_VERSION:
        raise AnomalyArtifactError(f"artifact schema must be {SCHEMA_VERSION!r}")
    if artifact.task != "binary" or artifact.preprocessor.task != "binary":
        raise AnomalyArtifactError("anomaly artifact requires binary preprocessing")
    if artifact.model_name != ANOMALY_MODEL_NAME:
        raise AnomalyArtifactError(f"unsupported anomaly model: {artifact.model_name!r}")
    if artifact.preprocessor.metadata.get("training_scope") != "normal_only":
        raise AnomalyArtifactError("anomaly preprocessor must be fitted on normal rows")
    if artifact.metadata.get("official_test_status") != "sealed_not_evaluated":
        raise AnomalyArtifactError("artifact does not preserve the official test seal")
    if not np.isfinite(artifact.threshold):
        raise AnomalyArtifactError("anomaly threshold must be finite")
    validate_preprocessor(artifact.preprocessor)
    check_is_fitted(artifact.estimator)


def score_anomalies(artifact: AnomalyModelArtifact, frame) -> np.ndarray:
    validate_artifact(artifact)
    features = transform_partition(artifact.preprocessor, frame)
    return _anomaly_scores(artifact.estimator, features)


def predict(artifact: AnomalyModelArtifact, frame) -> np.ndarray:
    scores = score_anomalies(artifact, frame)
    return (scores >= artifact.threshold).astype("int8")


def save_artifact(artifact: AnomalyModelArtifact, path: str | Path) -> Path:
    validate_artifact(artifact)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output)
    return output


def load_artifact(path: str | Path) -> AnomalyModelArtifact:
    """Load a trusted local artifact. Never load untrusted joblib files."""
    artifact = joblib.load(Path(path))
    validate_artifact(artifact)
    return artifact
