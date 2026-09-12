"""Security-relevant validation metrics for v2.0 classifiers."""

from __future__ import annotations

from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    multilabel_confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.preprocessing import label_binarize


class EvaluationError(ValueError):
    """Raised when a classifier cannot be evaluated under the v2.0 contract."""


def _python_value(value: Any) -> str | int | float | bool | None:
    if isinstance(value, np.generic):
        return value.item()
    return value


def _rate(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _predict_with_timing(
    estimator, features, *, warmup: bool
) -> tuple[np.ndarray, dict[str, float | int]]:
    samples = features.shape[0]
    if samples == 0:
        raise EvaluationError("validation partition must not be empty")

    if warmup:
        estimator.predict(features[: min(samples, 256)])
    started = perf_counter()
    predictions = np.asarray(estimator.predict(features))
    seconds = perf_counter() - started
    return predictions, {
        "samples": samples,
        "prediction_seconds": seconds,
        "prediction_ms_per_record": seconds * 1000 / samples,
    }


def _averaged_metrics(target, predictions, average: str) -> dict[str, float]:
    precision, recall, f1, _ = precision_recall_fscore_support(
        target,
        predictions,
        average=average,
        zero_division=0,
    )
    return {
        f"precision_{average}": float(precision),
        f"recall_{average}": float(recall),
        f"f1_{average}": float(f1),
    }


def _per_class_metrics(target, predictions, classes) -> dict[str, dict[str, float | int]]:
    precision, recall, f1, support = precision_recall_fscore_support(
        target,
        predictions,
        labels=classes,
        average=None,
        zero_division=0,
    )
    return {
        str(_python_value(label)): {
            "precision": float(precision[index]),
            "recall": float(recall[index]),
            "f1": float(f1[index]),
            "support": int(support[index]),
        }
        for index, label in enumerate(classes)
    }


def _binary_metrics(target, predictions, positive_scores) -> dict:
    tn, fp, fn, tp = confusion_matrix(target, predictions, labels=[0, 1]).ravel()
    precision, recall, f1, _ = precision_recall_fscore_support(
        target,
        predictions,
        average="binary",
        pos_label=1,
        zero_division=0,
    )
    return {
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "false_positive_rate": _rate(int(fp), int(fp + tn)),
        "false_negative_rate": _rate(int(fn), int(fn + tp)),
        "roc_auc": float(roc_auc_score(target, positive_scores)),
        "pr_auc": float(average_precision_score(target, positive_scores)),
    }


def evaluate_binary_detector(
    predictions,
    positive_scores,
    target,
    *,
    family_labels: pd.Series,
    prediction_seconds: float,
) -> dict:
    """Evaluate fixed binary predictions and higher-is-more-malicious scores."""
    target_array = np.asarray(target)
    prediction_array = np.asarray(predictions)
    score_array = np.asarray(positive_scores)
    samples = len(target_array)
    if samples == 0:
        raise EvaluationError("validation partition must not be empty")
    if (
        prediction_array.shape != target_array.shape
        or score_array.shape != target_array.shape
    ):
        raise EvaluationError("binary predictions and scores must align with targets")
    if not set(np.unique(target_array)).issubset({0, 1}):
        raise EvaluationError("binary targets must contain only 0 and 1")
    if not set(np.unique(prediction_array)).issubset({0, 1}):
        raise EvaluationError("binary predictions must contain only 0 and 1")

    classes = np.array([0, 1])
    per_class = _per_class_metrics(target_array, prediction_array, classes)
    results = {
        "samples": samples,
        "prediction_seconds": float(prediction_seconds),
        "prediction_ms_per_record": float(prediction_seconds * 1000 / samples),
        "accuracy": float(accuracy_score(target_array, prediction_array)),
        "balanced_accuracy": float(
            balanced_accuracy_score(target_array, prediction_array)
        ),
        **_averaged_metrics(target_array, prediction_array, "macro"),
        **_averaged_metrics(target_array, prediction_array, "weighted"),
        "labels": [0, 1],
        "confusion_matrix": confusion_matrix(
            target_array, prediction_array, labels=classes
        ).tolist(),
        "per_class": per_class,
        **_binary_metrics(target_array, prediction_array, score_array),
    }
    results["per_family_detection_rate"] = _family_detection_rates(
        "binary",
        target_array,
        prediction_array,
        family_labels,
        per_class,
    )
    return results


def _multiclass_metrics(target, predictions, probabilities, classes) -> dict:
    encoded_target = label_binarize(target, classes=classes)
    if encoded_target.shape[1] != len(classes):
        raise EvaluationError("multiclass evaluation requires at least three classes")

    matrices = multilabel_confusion_matrix(target, predictions, labels=classes)
    false_positive_rates: dict[str, float] = {}
    false_negative_rates: dict[str, float] = {}
    for index, label in enumerate(classes):
        tn, fp, fn, tp = matrices[index].ravel()
        key = str(_python_value(label))
        false_positive_rates[key] = _rate(int(fp), int(fp + tn))
        false_negative_rates[key] = _rate(int(fn), int(fn + tp))

    return {
        "false_positive_rate_macro": float(np.mean(list(false_positive_rates.values()))),
        "false_negative_rate_macro": float(np.mean(list(false_negative_rates.values()))),
        "false_positive_rate_by_class": false_positive_rates,
        "false_negative_rate_by_class": false_negative_rates,
        "roc_auc_ovr_macro": float(
            roc_auc_score(
                encoded_target,
                probabilities,
                average="macro",
            )
        ),
        "roc_auc_ovr_weighted": float(
            roc_auc_score(
                encoded_target,
                probabilities,
                average="weighted",
            )
        ),
        "pr_auc_macro": float(
            average_precision_score(encoded_target, probabilities, average="macro")
        ),
        "pr_auc_weighted": float(
            average_precision_score(encoded_target, probabilities, average="weighted")
        ),
    }


def _family_detection_rates(
    task: str,
    target,
    predictions,
    family_labels: pd.Series,
    per_class: dict[str, dict[str, float | int]],
) -> dict[str, float]:
    if len(family_labels) != len(target):
        raise EvaluationError("family labels must align with validation targets")
    if task == "multiclass":
        return {
            family: float(metrics["recall"])
            for family, metrics in per_class.items()
            if family != "normal"
        }

    families = np.asarray(family_labels)
    predicted_attack = np.asarray(predictions) == 1
    rates: dict[str, float] = {}
    for family in sorted(set(families) - {"normal"}):
        members = families == family
        rates[str(family)] = float(np.mean(predicted_attack[members]))
    return rates


def evaluate_classifier(
    estimator,
    features,
    target,
    *,
    task: str,
    family_labels: pd.Series,
    warmup: bool = True,
) -> dict:
    """Evaluate one fitted classifier on a validation partition only."""
    if task not in {"binary", "multiclass"}:
        raise EvaluationError(f"unsupported task: {task!r}")
    if not hasattr(estimator, "predict_proba"):
        raise EvaluationError("classifier must implement predict_proba")

    target_array = np.asarray(target)
    predictions, timing = _predict_with_timing(estimator, features, warmup=warmup)
    classes = np.asarray(estimator.classes_)
    probabilities = np.asarray(estimator.predict_proba(features))
    if probabilities.shape != (len(target_array), len(classes)):
        raise EvaluationError("predict_proba returned an incompatible shape")

    class_values = [_python_value(value) for value in classes]
    if task == "binary":
        if 1 not in class_values:
            raise EvaluationError("binary classifier does not expose attack class 1")
        positive_index = class_values.index(1)
        return evaluate_binary_detector(
            predictions,
            probabilities[:, positive_index],
            target_array,
            family_labels=family_labels,
            prediction_seconds=timing["prediction_seconds"],
        )

    per_class = _per_class_metrics(target_array, predictions, classes)
    results = {
        **timing,
        "accuracy": float(accuracy_score(target_array, predictions)),
        "balanced_accuracy": float(
            balanced_accuracy_score(target_array, predictions)
        ),
        **_averaged_metrics(target_array, predictions, "macro"),
        **_averaged_metrics(target_array, predictions, "weighted"),
        "labels": class_values,
        "confusion_matrix": confusion_matrix(
            target_array, predictions, labels=classes
        ).tolist(),
        "per_class": per_class,
    }
    results.update(
        _multiclass_metrics(target_array, predictions, probabilities, classes)
    )
    results["per_family_detection_rate"] = _family_detection_rates(
        task,
        target_array,
        predictions,
        family_labels,
        per_class,
    )
    return results
