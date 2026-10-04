"""Bounded SHAP compatibility checks for trusted v2.0 final artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np

from cids.datasets.unsw_nb15 import (
    ATTACK_FAMILIES, FEATURE_COLUMNS, NUMERIC_FEATURES, validate_model_feature_frame,
)
from cids.final_evaluation import FinalModelArtifact, validate_artifact
from cids.modeling.supervised import model_features_for_estimator
from cids.preprocessing import output_feature_names, transform_partition
from cids.workbench.config import load_workbench_config, validate_workbench_config


class ExplanationGateError(ValueError):
    """Raised when the pinned explanation contract cannot be satisfied."""


@dataclass(frozen=True)
class ExplanationGateResult:
    task: str
    model_name: str
    class_labels: tuple[object, ...]
    explained_classes: tuple[object, ...]
    background_rows: int
    explained_rows: int
    transformed_feature_count: int
    source_feature_count: int
    shap_values_shape: tuple[int, ...]
    max_additivity_error: float
    max_aggregation_error: float
    elapsed_seconds: float
    model_output: str
    explainer_algorithm: str
    masker: str
    permutation_rounds: int


def source_feature_mapping(artifact: FinalModelArtifact) -> tuple[str, ...]:
    """Map transformed columns to the original 42 source features safely."""
    validate_artifact(artifact)
    transformer = artifact.preprocessor.transformer
    names = output_feature_names(artifact.preprocessor)
    mapping: list[str | None] = [None] * len(names)

    numeric_slice = transformer.output_indices_.get("numeric")
    categorical_slice = transformer.output_indices_.get("categorical")
    if not isinstance(numeric_slice, slice) or not isinstance(categorical_slice, slice):
        raise ExplanationGateError("preprocessor output slices are unavailable")
    numeric_positions = list(range(numeric_slice.start, numeric_slice.stop))
    if len(numeric_positions) != len(NUMERIC_FEATURES):
        raise ExplanationGateError("numerical feature mapping is inconsistent")
    for position, source in zip(numeric_positions, NUMERIC_FEATURES):
        mapping[position] = source

    categorical = transformer.named_transformers_.get("categorical")
    categories = getattr(categorical, "categories_", None)
    if categories is None:
        raise ExplanationGateError("categorical vocabularies are unavailable")
    categorical_sources: list[str] = []
    transformer_columns = {
        name: columns for name, _, columns in transformer.transformers_
    }
    categorical_columns = transformer_columns.get("categorical")
    if categorical_columns is None:
        raise ExplanationGateError("categorical source columns are unavailable")
    for source, vocabulary in zip(categorical_columns, categories):
        categorical_sources.extend([str(source)] * len(vocabulary))
    categorical_positions = list(
        range(categorical_slice.start, categorical_slice.stop)
    )
    if len(categorical_positions) != len(categorical_sources):
        raise ExplanationGateError("categorical feature mapping is inconsistent")
    for position, source in zip(categorical_positions, categorical_sources):
        mapping[position] = source

    if any(source not in FEATURE_COLUMNS for source in mapping):
        raise ExplanationGateError("transformed features cannot map to source schema")
    return tuple(str(source) for source in mapping)


def aggregate_to_source_features(
    shap_values: np.ndarray,
    mapping: tuple[str, ...],
) -> np.ndarray:
    """Sum one-hot contributions into the ordered original feature vocabulary."""
    values = np.asarray(shap_values, dtype=float)
    if (values.ndim not in {2, 3} or values.shape[1] != len(mapping)
            or not np.isfinite(values).all() or any(s not in FEATURE_COLUMNS for s in mapping)
            or set(mapping) != set(FEATURE_COLUMNS)):
        raise ExplanationGateError("SHAP values have an incompatible feature axis")
    trailing = values.shape[2:]
    aggregated = np.zeros((values.shape[0], len(FEATURE_COLUMNS), *trailing))
    source_positions = {name: index for index, name in enumerate(FEATURE_COLUMNS)}
    for transformed_position, source in enumerate(mapping):
        aggregated[:, source_positions[source], ...] += values[
            :, transformed_position, ...
        ]
    return aggregated


def _maximum_error(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        raise ExplanationGateError(
            f"explanation output shape mismatch: {left.shape} != {right.shape}"
        )
    if not np.isfinite(left).all() or not np.isfinite(right).all():
        raise ExplanationGateError("explanation contains non-finite values")
    return float(np.max(np.abs(left - right))) if left.size else 0.0


def _permutation_values(artifact, background, foreground, policy):
    """The accepted method, shared by the historical gate and runtime service."""
    import shap

    if shap.__version__ != policy["shap_version"]:
        raise ExplanationGateError("SHAP runtime does not match pinned policy")
    masker = shap.maskers.Independent(background, max_samples=len(background))
    explainer = shap.PermutationExplainer(
        lambda values: np.asarray(artifact.estimator.decision_function(values), dtype=float),
        masker, seed=policy["seed"],
    )
    return explainer(foreground, max_evals=policy["permutation_rounds"] *
                     (2 * foreground.shape[1] + 1), silent=True)


def validate_contributions(task, classes, values, bases, raw, mapping, predictions, policy):
    """Check every class and encoded contribution before selecting display output."""
    values, bases, raw = (np.asarray(v, dtype=float) for v in (values, bases, raw))
    classes = tuple(v.item() if isinstance(v, np.generic) else v for v in classes)
    n, p = len(predictions), len(mapping)
    if not n or len(set(classes)) != len(classes):
        raise ExplanationGateError("invalid class mapping")
    if task == "binary":
        if (classes != (0, 1) or any(type(c) is not int for c in classes)
                or values.shape != (n, p) or bases.shape != (n,) or raw.shape != (n,)):
            raise ExplanationGateError("binary explanation dimensions or classes are incompatible")
        if tuple(predictions) != tuple((raw > 0).astype(int)):
            raise ExplanationGateError("binary raw prediction mismatch")
        positions = [None] * n
        explained = [1] * n  # Attack output even when the predicted class is normal.
    elif task == "multiclass":
        if (len(classes) < 3 or not set(classes).issubset(ATTACK_FAMILIES)
                or values.shape != (n, p, len(classes))
                or bases.shape != (n, len(classes)) or raw.shape != bases.shape):
            raise ExplanationGateError("multiclass explanation dimensions or classes are incompatible")
        positions = raw.argmax(axis=1).tolist()
        explained = [classes[i] for i in positions]
        if tuple(predictions) != tuple(explained):
            raise ExplanationGateError("independent raw family prediction mismatch")
    else:
        raise ExplanationGateError("unsupported explanation task")
    error = _maximum_error(bases + values.sum(axis=1), raw)
    if error > policy["additivity_abs_tolerance"]:
        raise ExplanationGateError("explanation additivity failed")
    aggregated = aggregate_to_source_features(values, mapping)
    aggregation_error = _maximum_error(values.sum(axis=1), aggregated.sum(axis=1))
    if aggregation_error > policy["aggregation_abs_tolerance"]:
        raise ExplanationGateError("explanation aggregation failed")
    results = []
    for i, position in enumerate(positions):
        results.append({
            "explained_class": explained[i],
            "baseline_output": float(bases[i] if position is None else bases[i, position]),
            "model_output": float(raw[i] if position is None else raw[i, position]),
            "contributions": (aggregated[i] if position is None else aggregated[i, :, position]).tolist(),
            "max_additivity_error": error, "max_aggregation_error": aggregation_error,
        })
    return results


def explain_records(artifact, background_frame, explain_frame):
    """Compute local contributions inside a cancellable worker, feature-only data.

    The caller must use the verified pack loader and enforce the wall-clock limit
    with process isolation. This calculation holds no global state or cache.
    """
    policy = load_workbench_config()["explainability"]
    validate_artifact(artifact)
    if (not 0 < len(background_frame) <= min(256, policy["background_rows"])
            or not 0 < len(explain_frame) <= policy["max_explain_rows"]):
        raise ExplanationGateError("explanation inputs exceed bounds")
    matrices = []
    for frame in (background_frame, explain_frame):
        features = validate_model_feature_frame(frame)
        matrix = model_features_for_estimator(artifact.model_name, artifact.preprocessor.transformer.transform(features))
        if matrix.ndim != 2 or matrix.shape[1] > 512 or not np.isfinite(matrix).all():
            raise ExplanationGateError("transformed features exceed supported bounds")
        matrices.append(matrix)
    explanation = _permutation_values(artifact, *matrices, policy)
    foreground = matrices[1]
    return validate_contributions(
        artifact.task, artifact.estimator.classes_, explanation.values, explanation.base_values,
        artifact.estimator.decision_function(foreground), source_feature_mapping(artifact),
        artifact.estimator.predict(foreground), policy,
    )


def run_explanation_gate(
    artifact: FinalModelArtifact,
    background_frame,
    explain_frame,
    *,
    config: dict | None = None,
) -> ExplanationGateResult:
    """Prove compatibility, class mapping, additivity, aggregation, and bounds."""
    policy = load_workbench_config() if config is None else validate_workbench_config(config)
    explanation_policy = policy["explainability"]
    validate_artifact(artifact)
    if artifact.model_name != "hist_gradient_boosting":
        raise ExplanationGateError("SHAP gate supports only the selected HGB models")
    if not 0 < len(background_frame) <= explanation_policy["background_rows"]:
        raise ExplanationGateError("background row count is outside the gate bound")
    if not 0 < len(explain_frame) <= explanation_policy["max_explain_rows"]:
        raise ExplanationGateError("explanation row count is outside the gate bound")

    try:
        import shap
    except ImportError as exc:
        raise ExplanationGateError(
            "SHAP is not installed; use requirements-workbench.txt"
        ) from exc
    if shap.__version__ != explanation_policy["shap_version"]:
        raise ExplanationGateError(
            f"SHAP must be {explanation_policy['shap_version']}, "
            f"found {shap.__version__}"
        )

    started = perf_counter()
    background = model_features_for_estimator(
        artifact.model_name,
        transform_partition(artifact.preprocessor, background_frame),
    )
    foreground = model_features_for_estimator(
        artifact.model_name,
        transform_partition(artifact.preprocessor, explain_frame),
    )
    try:
        explanation = _permutation_values(artifact, background, foreground, explanation_policy)
    except Exception as exc:
        raise ExplanationGateError("bounded permutation explanation failed") from exc
    elapsed = perf_counter() - started
    if elapsed > explanation_policy["max_task_seconds"]:
        raise ExplanationGateError(
            f"SHAP gate exceeded {explanation_policy['max_task_seconds']} seconds"
        )

    values = np.asarray(explanation.values, dtype=float)
    base_values = np.asarray(explanation.base_values, dtype=float)
    class_labels = tuple(
        value.item() if isinstance(value, np.generic) else value
        for value in artifact.estimator.classes_
    )
    raw_output = np.asarray(artifact.estimator.decision_function(foreground), dtype=float)
    if artifact.task == "binary":
        if values.ndim != 2 or base_values.shape != (len(foreground),):
            raise ExplanationGateError("binary SHAP dimensions are incompatible")
        explained_classes = (class_labels[1],)
    elif artifact.task == "multiclass":
        expected_shape = (len(foreground), len(class_labels))
        if values.ndim != 3 or base_values.shape != expected_shape:
            raise ExplanationGateError("multiclass SHAP dimensions are incompatible")
        if values.shape[2] != len(class_labels):
            raise ExplanationGateError("SHAP class axis does not match estimator labels")
        explained_classes = class_labels
    else:
        raise ExplanationGateError(f"unsupported artifact task: {artifact.task!r}")

    reconstructed = base_values + values.sum(axis=1)
    additivity_error = _maximum_error(reconstructed, raw_output)
    if additivity_error > explanation_policy["additivity_abs_tolerance"]:
        raise ExplanationGateError(
            f"SHAP additivity error exceeds tolerance: {additivity_error}"
        )

    mapping = source_feature_mapping(artifact)
    aggregated = aggregate_to_source_features(values, mapping)
    aggregation_error = _maximum_error(
        values.sum(axis=1), aggregated.sum(axis=1)
    )
    if aggregation_error > explanation_policy["aggregation_abs_tolerance"]:
        raise ExplanationGateError(
            f"source-feature aggregation error exceeds tolerance: {aggregation_error}"
        )

    return ExplanationGateResult(
        task=artifact.task,
        model_name=artifact.model_name,
        class_labels=class_labels,
        explained_classes=explained_classes,
        background_rows=len(background_frame),
        explained_rows=len(explain_frame),
        transformed_feature_count=values.shape[1],
        source_feature_count=len(FEATURE_COLUMNS),
        shap_values_shape=values.shape,
        max_additivity_error=additivity_error,
        max_aggregation_error=aggregation_error,
        elapsed_seconds=elapsed,
        model_output="raw",
        explainer_algorithm="permutation",
        masker="independent_development_background",
        permutation_rounds=explanation_policy["permutation_rounds"],
    )
