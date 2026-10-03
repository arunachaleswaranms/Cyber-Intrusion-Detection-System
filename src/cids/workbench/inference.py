"""Verified local model loading and framework-independent, uncalibrated scoring.

Joblib deserialization executes trusted code. Only the maintainer's artifacts
anchored by the accepted gate may reach this module; a digest proves identity,
not safety. No web upload or caller-supplied artifact is accepted.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import OneHotEncoder
from sklearn.utils.validation import check_is_fitted

from cids.config import load_experiment_config
from cids.datasets.unsw_nb15 import (
    ATTACK_FAMILIES, ATTACK_FAMILY_COLUMN, BINARY_LABEL_COLUMN,
    CATEGORICAL_FEATURES, FEATURE_COLUMNS, ID_COLUMN, NUMERIC_FEATURES,
)
from cids.final_evaluation import FinalModelArtifact, validate_artifact
from cids.modeling.supervised import MODEL_ARTIFACT_VERSION, build_estimator, model_features_for_estimator
from cids.preprocessing import PreprocessingArtifact, validate_artifact as validate_preprocessor
from cids.workbench.config import load_workbench_config
from cids.workbench.contracts import (
    EVENT_TIME_COLUMN,
    InferenceInput,
    PredictionRecord,
    _is_sha256,
    _validate_frame,
    queue_band_for,
)
from cids.workbench.model_pack import (
    EXPECTED_CONTRACTS_BASE,
    EXPECTED_RUNTIME,
    MAX_ARTIFACT_BYTES,
    ModelPackError,
    preflight_model_pack,
)

BATCH_ROWS = 1024
_LOAD_SEAL = object()


class InferenceError(ValueError):
    """Raised when a verified model or prediction violates the frozen contract."""


@dataclass(frozen=True)
class LoadedModelPack:
    model_pack_id: str
    binary: FinalModelArtifact
    multiclass: FinalModelArtifact
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _LOAD_SEAL:
            raise InferenceError("model pack must come from verified loading")


def _validate_loaded(artifact: object, task: str, manifest: dict) -> FinalModelArtifact:
    if type(artifact) is not FinalModelArtifact:
        raise InferenceError(f"{task} has the wrong artifact type")
    if artifact.task != task:
        raise InferenceError(f"{task} artifact is in the wrong slot")
    if type(artifact.preprocessor) is not PreprocessingArtifact:
        raise InferenceError(f"{task} has the wrong preprocessor type")
    if type(artifact.preprocessor.transformer) is not ColumnTransformer:
        raise InferenceError(f"{task} has the wrong transformer type")
    if type(artifact.estimator) is not HistGradientBoostingClassifier:
        raise InferenceError(f"{task} has the wrong estimator type")
    contracts = manifest["contracts"]
    if artifact.version != contracts["artifact_version"] or artifact.schema_version != contracts["schema_version"]:
        raise InferenceError(f"{task} artifact version or schema mismatch")
    if artifact.model_name != "hist_gradient_boosting":
        raise InferenceError(f"{task} selected model mismatch")
    if artifact.preprocessor.task != task or artifact.preprocessor.schema_version != contracts["schema_version"]:
        raise InferenceError(f"{task} preprocessor task or schema mismatch")
    if artifact.preprocessor.version != contracts["preprocessor_version"]:
        raise InferenceError(f"{task} preprocessor version mismatch")
    transformer = artifact.preprocessor.transformer
    if (
        len(transformer.transformers) != 2
        or transformer.transformers[0] != ("numeric", "passthrough", list(NUMERIC_FEATURES))
        or transformer.transformers[1][0] != "categorical"
        or transformer.transformers[1][2] != list(CATEGORICAL_FEATURES)
        or type(transformer.transformers[1][1]) is not OneHotEncoder
        or transformer.transformers[1][1].handle_unknown != "ignore"
        or transformer.transformers[1][1].sparse_output is not True
        or transformer.transformers[1][1].dtype != np.float32
        or transformer.remainder != "drop"
        or transformer.sparse_threshold != 0.3
        or transformer.verbose_feature_names_out is not False
        or transformer.transformers[1][1].get_params(deep=False)
        != OneHotEncoder(
            handle_unknown="ignore", sparse_output=True, dtype=np.float32
        ).get_params(deep=False)
    ):
        raise InferenceError(f"{task} preprocessor configuration mismatch")
    try:
        validate_artifact(artifact)
        validate_preprocessor(artifact.preprocessor)
        check_is_fitted(artifact.estimator)
        check_is_fitted(artifact.preprocessor.transformer)
    except (ValueError, TypeError, AttributeError) as exc:
        raise InferenceError(f"{task} artifact is invalid or unfitted") from exc

    metadata = artifact.metadata
    if type(metadata) is not dict or type(artifact.preprocessor.metadata) is not dict:
        raise InferenceError(f"{task} metadata is malformed")
    required = {
        "artifact_version": artifact.version,
        "source_artifact_version": MODEL_ARTIFACT_VERSION,
        **{key: contracts[key] for key in EXPECTED_CONTRACTS_BASE if key != "preprocessor_version"},
        "task": task,
        "model_name": artifact.model_name,
        "split_policy_version": load_experiment_config()["split"]["policy_version"],
        "seed": load_experiment_config()["split"]["seed"],
        "estimator_class": type(artifact.estimator).__name__,
        "training_scope": "prepared_train_plus_validation",
        "official_test_status": "evaluated_once",
        "library_versions": EXPECTED_RUNTIME["libraries"],
        "preprocessor": artifact.preprocessor.metadata,
    }
    if any(metadata.get(key) != value for key, value in required.items()):
        raise InferenceError(f"{task} internal metadata or manifest mismatch")
    expected_keys = set(required) | {
        "estimator_parameters", "development_training_rows", "development_training_id_sha256",
        "official_test_rows", "official_test_id_sha256", "fit_seconds",
    }
    if set(metadata) != expected_keys:
        raise InferenceError(f"{task} metadata fields mismatch")
    expected_params = build_estimator("hist_gradient_boosting", load_experiment_config()["models"]["supervised"]["hist_gradient_boosting"], metadata["seed"]).get_params(deep=False)
    if artifact.estimator.get_params(deep=False) != expected_params or metadata["estimator_parameters"] != expected_params:
        raise InferenceError(f"{task} estimator parameters mismatch")
    pre = artifact.preprocessor.metadata
    expected_pre = {
        "preprocessor_version": contracts["preprocessor_version"],
        "schema_version": contracts["schema_version"],
        "task": task,
        "split_policy_version": metadata["split_policy_version"],
        "training_scope": "prepared_train",
        "source_training_rows": metadata["development_training_rows"],
        "source_training_id_sha256": metadata["development_training_id_sha256"],
        "training_rows": metadata["development_training_rows"],
        "training_id_sha256": metadata["development_training_id_sha256"],
        "input_feature_count": len(FEATURE_COLUMNS),
    }
    if any(pre.get(key) != value for key, value in expected_pre.items()):
        raise InferenceError(f"{task} preprocessor metadata mismatch")
    if set(pre) != set(expected_pre) | {"output_feature_count", "output_feature_names_sha256", "categorical_vocabulary_sizes"}:
        raise InferenceError(f"{task} preprocessor metadata fields mismatch")
    if not isinstance(pre["output_feature_count"], int) or pre["output_feature_count"] <= 0:
        raise InferenceError(f"{task} output feature count is invalid")
    if pre["output_feature_count"] != len(transformer.get_feature_names_out()):
        raise InferenceError(f"{task} transformed feature count mismatch")
    encoder = transformer.named_transformers_["categorical"]
    categories = {
        name: len(values)
        for name, values in zip(CATEGORICAL_FEATURES, encoder.categories_)
    }
    if pre["categorical_vocabulary_sizes"] != categories:
        raise InferenceError(f"{task} categorical vocabulary metadata mismatch")
    if artifact.estimator.n_features_in_ != pre["output_feature_count"]:
        raise InferenceError(f"{task} fitted feature count mismatch")
    if not isinstance(artifact.estimator._predictors, list) or not artifact.estimator._predictors:
        raise InferenceError(f"{task} estimator has no fitted predictors")
    expected_classes = (0, 1) if task == "binary" else tuple(sorted(ATTACK_FAMILIES))
    if tuple(artifact.estimator.classes_) != expected_classes:
        raise InferenceError(f"{task} class order mismatch")
    for key in ("development_training_rows", "official_test_rows"):
        if type(metadata[key]) is not int or metadata[key] <= 0:
            raise InferenceError(f"{task} {key} is invalid")
    for key in ("development_training_id_sha256", "official_test_id_sha256"):
        if not _is_sha256(metadata[key]):
            raise InferenceError(f"{task} {key} is invalid")
    if not np.isfinite(metadata["fit_seconds"]) or metadata["fit_seconds"] < 0:
        raise InferenceError(f"{task} fit duration is invalid")
    return artifact


def _read_verified_bytes(path: Path, spec: dict) -> bytes:
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_ARTIFACT_BYTES + 1)
            if len(payload) > MAX_ARTIFACT_BYTES or stream.read(1):
                raise InferenceError("artifact exceeds the 256 MiB limit")
    except OSError as exc:
        raise InferenceError("artifact could not be read") from exc
    if len(payload) != spec["size_bytes"] or hashlib.sha256(payload).hexdigest() != spec["sha256"]:
        raise InferenceError("artifact changed after preflight")
    return payload


def load_model_pack(pack_dir: str | Path) -> LoadedModelPack:
    """Preflight, hash exact bounded bytes, deserialize, and validate both tasks."""
    verified = preflight_model_pack(pack_dir)
    if verified.manifest["provenance_type"] != "maintainer_final_v2":
        raise ModelPackError("only accepted maintainer final artifacts may be loaded")
    loaded = {}
    digests = set()
    for task in ("binary", "multiclass"):
        spec = verified.manifest["artifacts"][task]
        if spec["sha256"] in digests:
            raise InferenceError("duplicate task artifacts")
        digests.add(spec["sha256"])
        payload = _read_verified_bytes(verified.artifact_paths[task], spec)
        try:
            artifact = joblib.load(io.BytesIO(payload))
        except Exception as exc:
            raise InferenceError(f"{task} artifact could not be deserialized") from exc
        loaded[task] = _validate_loaded(artifact, task, verified.manifest)
    return LoadedModelPack(
        verified.manifest["model_pack_id"],
        loaded["binary"],
        loaded["multiclass"],
        _LOAD_SEAL,
    )


def _predictions(artifact: FinalModelArtifact, features: pd.DataFrame, task: str):
    matrix = model_features_for_estimator(artifact.model_name, artifact.preprocessor.transformer.transform(features))
    labels = np.asarray(artifact.estimator.predict(matrix))
    probabilities = np.asarray(artifact.estimator.predict_proba(matrix))
    classes = tuple(artifact.estimator.classes_)
    count = len(features)
    if labels.shape != (count,) or probabilities.shape != (count, len(classes)):
        raise InferenceError(f"{task} prediction shape mismatch")
    if not np.issubdtype(probabilities.dtype, np.number) or not np.isfinite(probabilities).all():
        raise InferenceError(f"{task} model scores are malformed")
    if (probabilities < 0).any() or (probabilities > 1).any() or not np.allclose(probabilities.sum(axis=1), 1, atol=1e-6):
        raise InferenceError(f"{task} model scores are out of range")
    if any(label not in classes for label in labels):
        raise InferenceError(f"{task} predicted unknown class")
    return labels, probabilities, {value: index for index, value in enumerate(classes)}


def infer(pack: LoadedModelPack, input_data: InferenceInput) -> tuple[PredictionRecord, ...]:
    """Score bounded input in stable batches; scores are uncalibrated model scores."""
    if type(pack) is not LoadedModelPack or not _is_sha256(pack.model_pack_id):
        raise InferenceError("a loaded, verified model pack is required")
    if type(input_data) is not InferenceInput or not isinstance(input_data.frame, pd.DataFrame):
        raise InferenceError("validated InferenceInput is required")
    policy = load_workbench_config()
    columns = input_data.frame.columns
    allowed = {ID_COLUMN, EVENT_TIME_COLUMN, BINARY_LABEL_COLUMN, ATTACK_FAMILY_COLUMN, *FEATURE_COLUMNS}
    if columns.has_duplicates or not set(FEATURE_COLUMNS).issubset(columns) or not set(columns).issubset(allowed):
        raise InferenceError("input feature columns are invalid")
    frame, generated = _validate_frame(input_data.frame)
    if not 0 < len(frame) <= policy["input"]["max_rows"] or generated:
        raise InferenceError("input row count or IDs are invalid")
    if not _is_sha256(input_data.input_sha256) or not 0 < input_data.source_bytes <= policy["input"]["max_upload_bytes"]:
        raise InferenceError("input provenance is invalid")
    if input_data.has_event_time != (EVENT_TIME_COLUMN in frame):
        raise InferenceError("input timestamp contract mismatch")
    if input_data.has_binary_labels != (BINARY_LABEL_COLUMN in frame) or input_data.has_family_labels != (ATTACK_FAMILY_COLUMN in frame):
        raise InferenceError("input label contract mismatch")
    records = []
    for start in range(0, len(frame), BATCH_ROWS):
        batch = frame.iloc[start : start + BATCH_ROWS]
        features = batch.loc[:, FEATURE_COLUMNS]
        binary, binary_scores, binary_columns = _predictions(pack.binary, features, "binary")
        family, family_scores, family_columns = _predictions(pack.multiclass, features, "multiclass")
        for index, (_, row) in enumerate(batch.iterrows()):
            binary_prediction = "attack" if binary[index] == 1 else "normal"
            family_prediction = str(family[index])
            attack_score = float(binary_scores[index, binary_columns[1]])
            band = queue_band_for(binary_prediction, family_prediction, attack_score, config=policy)
            records.append(PredictionRecord(
                record_id=str(row[ID_COLUMN]),
                event_time_utc=row[EVENT_TIME_COLUMN] if EVENT_TIME_COLUMN in batch else None,
                binary_prediction=binary_prediction,
                attack_model_score=attack_score,
                family_prediction_raw=family_prediction,
                family_model_score=float(family_scores[index, family_columns[family_prediction]]),
                triage_family=("not_alerted" if binary_prediction == "normal" else "unresolved" if family_prediction == "normal" else family_prediction),
                queue_band=band,
                explanation_status="not_requested",
                top_contributions=(),
                model_pack_id=pack.model_pack_id,
            ))
    return tuple(records)
