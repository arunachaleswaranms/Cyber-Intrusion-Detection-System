"""Retrain frozen selected models and evaluate the official test once."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.utils.validation import check_is_fitted

from cids.config import (
    config_sha256,
    load_experiment_config,
    validate_experiment_config,
    validate_split_report,
)
from cids.datasets.split_unsw_nb15 import PreparedSplits, target_for_task
from cids.datasets.unsw_nb15 import (
    ATTACK_FAMILY_COLUMN,
    ID_COLUMN,
    SCHEMA_VERSION,
    validate_prepared_frame,
)
from cids.evaluation import evaluate_classifier
from cids.final_protocol import (
    load_final_protocol,
    protocol_sha256,
    validate_final_protocol,
)
from cids.modeling.supervised import (
    MODEL_ARTIFACT_VERSION,
    build_estimator,
    model_features_for_estimator,
)
from cids.preprocessing import (
    PreprocessingArtifact,
    fit_preprocessor,
    transform_partition,
    validate_artifact as validate_preprocessor,
)
from cids.selection import (
    load_model_selection,
    selection_sha256,
    validate_model_selection,
)

FINAL_MODEL_ARTIFACT_VERSION = "unsw-nb15-final-supervised-v1"


class FinalEvaluationError(ValueError):
    """Raised when final training or official-test evaluation is invalid."""


@dataclass
class FinalModelArtifact:
    version: str
    schema_version: str
    task: str
    model_name: str
    preprocessor: PreprocessingArtifact
    estimator: object
    metadata: dict


@dataclass(frozen=True)
class FinalEvaluationResult:
    artifact: FinalModelArtifact
    official_test_metrics: dict


def _id_digest(frame: pd.DataFrame) -> str:
    values = "\n".join(str(value) for value in frame[ID_COLUMN]).encode()
    return hashlib.sha256(values).hexdigest()


def _combined_development_splits(splits: PreparedSplits) -> PreparedSplits:
    training = validate_prepared_frame(splits.train)
    validation = validate_prepared_frame(splits.validation)
    expected_digests = splits.report.get("id_sha256", {})
    if _id_digest(training) != expected_digests.get("train"):
        raise FinalEvaluationError("training IDs do not match the split report")
    if _id_digest(validation) != expected_digests.get("validation"):
        raise FinalEvaluationError("validation IDs do not match the split report")
    if set(training[ID_COLUMN]) & set(validation[ID_COLUMN]):
        raise FinalEvaluationError("training and validation IDs overlap")

    combined = (
        pd.concat([training, validation], ignore_index=True)
        .sort_values(ID_COLUMN)
        .reset_index(drop=True)
    )
    combined = validate_prepared_frame(combined)
    report = copy.deepcopy(splits.report)
    report["id_sha256"]["train"] = _id_digest(combined)
    report["prepared_rows"]["train"] = len(combined)
    report["final_training_scope"] = "prepared_train_plus_validation"
    return PreparedSplits(
        train=combined,
        validation=splits.validation,
        test=splits.test,
        report=report,
    )


def train_and_evaluate_selected(
    splits: PreparedSplits,
    *,
    config: dict | None = None,
    selection: dict | None = None,
    protocol: dict | None = None,
) -> FinalEvaluationResult:
    """Retrain one frozen task model, then evaluate its official test partition."""
    experiment_config = (
        load_experiment_config()
        if config is None
        else validate_experiment_config(config)
    )
    model_selection = (
        load_model_selection(config=experiment_config)
        if selection is None
        else validate_model_selection(selection, experiment_config)
    )
    final_protocol = (
        load_final_protocol(config=experiment_config, selection=model_selection)
        if protocol is None
        else validate_final_protocol(
            protocol,
            config=experiment_config,
            selection=model_selection,
        )
    )
    validate_split_report(experiment_config, splits.report)
    task = splits.report.get("task")
    if task not in {"binary", "multiclass"}:
        raise FinalEvaluationError(f"unsupported final task: {task!r}")
    selected = model_selection["selected"][task]
    if selected["selected_artifact_version"] != MODEL_ARTIFACT_VERSION:
        raise FinalEvaluationError("selected artifact version is incompatible")
    model_name = selected["selected_model"]
    if final_protocol["official_test"]["tasks"][task] != model_name:
        raise FinalEvaluationError("protocol model does not match selected model")

    final_splits = _combined_development_splits(splits)
    preprocessor = fit_preprocessor(final_splits)
    development_features = model_features_for_estimator(
        model_name,
        transform_partition(preprocessor, final_splits.train),
    )
    target_column = target_for_task(task)
    estimator = build_estimator(
        model_name,
        experiment_config["models"]["supervised"][model_name],
        experiment_config["split"]["seed"],
    )
    started = perf_counter()
    estimator.fit(development_features, final_splits.train[target_column])
    fit_seconds = perf_counter() - started

    official_test = validate_prepared_frame(splits.test)
    if _id_digest(official_test) != splits.report["id_sha256"]["official_test"]:
        raise FinalEvaluationError("official-test IDs do not match the split report")
    official_test_features = model_features_for_estimator(
        model_name,
        transform_partition(preprocessor, official_test),
    )
    metrics = evaluate_classifier(
        estimator,
        official_test_features,
        official_test[target_column],
        task=task,
        family_labels=official_test[ATTACK_FAMILY_COLUMN],
        warmup=False,
    )
    metadata = {
        "artifact_version": FINAL_MODEL_ARTIFACT_VERSION,
        "source_artifact_version": MODEL_ARTIFACT_VERSION,
        "experiment_config_version": experiment_config["config_version"],
        "experiment_config_sha256": config_sha256(experiment_config),
        "model_selection_version": model_selection["selection_version"],
        "model_selection_sha256": selection_sha256(
            model_selection, experiment_config
        ),
        "final_protocol_version": final_protocol["protocol_version"],
        "final_protocol_sha256": protocol_sha256(
            final_protocol,
            config=experiment_config,
            selection=model_selection,
        ),
        "schema_version": SCHEMA_VERSION,
        "split_policy_version": splits.report["split_policy_version"],
        "task": task,
        "model_name": model_name,
        "seed": experiment_config["split"]["seed"],
        "estimator_class": type(estimator).__name__,
        "estimator_parameters": estimator.get_params(deep=False),
        "training_scope": "prepared_train_plus_validation",
        "development_training_rows": len(final_splits.train),
        "development_training_id_sha256": final_splits.report["id_sha256"]["train"],
        "official_test_rows": len(official_test),
        "official_test_id_sha256": splits.report["id_sha256"]["official_test"],
        "official_test_status": "evaluated_once",
        "fit_seconds": fit_seconds,
        "library_versions": {
            "joblib": joblib.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "preprocessor": preprocessor.metadata,
    }
    artifact = FinalModelArtifact(
        version=FINAL_MODEL_ARTIFACT_VERSION,
        schema_version=SCHEMA_VERSION,
        task=task,
        model_name=model_name,
        preprocessor=preprocessor,
        estimator=estimator,
        metadata=metadata,
    )
    validate_artifact(artifact)
    return FinalEvaluationResult(
        artifact=artifact,
        official_test_metrics=metrics,
    )


def validate_artifact(artifact: object) -> None:
    if not isinstance(artifact, FinalModelArtifact):
        raise FinalEvaluationError("not a CIDS final model artifact")
    if artifact.version != FINAL_MODEL_ARTIFACT_VERSION:
        raise FinalEvaluationError(f"unsupported final artifact: {artifact.version!r}")
    if artifact.schema_version != SCHEMA_VERSION:
        raise FinalEvaluationError(f"artifact schema must be {SCHEMA_VERSION!r}")
    if artifact.task not in {"binary", "multiclass"}:
        raise FinalEvaluationError(f"unsupported artifact task: {artifact.task!r}")
    if artifact.task != artifact.preprocessor.task:
        raise FinalEvaluationError("model and preprocessor tasks do not match")
    if artifact.metadata.get("official_test_status") != "evaluated_once":
        raise FinalEvaluationError("final artifact must record one test evaluation")
    validate_preprocessor(artifact.preprocessor)
    check_is_fitted(artifact.estimator)


def predict(artifact: FinalModelArtifact, frame) -> np.ndarray:
    validate_artifact(artifact)
    features = transform_partition(artifact.preprocessor, frame)
    return np.asarray(
        artifact.estimator.predict(
            model_features_for_estimator(artifact.model_name, features)
        )
    )


def save_artifact(artifact: FinalModelArtifact, path: str | Path) -> Path:
    validate_artifact(artifact)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output)
    return output


def load_artifact(path: str | Path) -> FinalModelArtifact:
    """Load a trusted local artifact. Never load untrusted joblib files."""
    artifact = joblib.load(Path(path))
    validate_artifact(artifact)
    return artifact
