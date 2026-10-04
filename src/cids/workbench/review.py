"""Uploaded-sample review and ephemeral simulation, using completed results only."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from cids.workbench.analysis import queue_indices

# Pinned sklearn HGB predicts classes_[1] iff raw logit > 0 (ties classes_[0]).
# Its binary sigmoid score boundary is 0.5; simulation uses stored scores only.
BASELINE_THRESHOLD = 0.5
COMPARISON_RULE = "attack_model_score > threshold; equality is normal"
SAMPLE_SCOPE = "full_current_uploaded_sample"
BINARY_ERRORS = ("TP", "TN", "FP", "FN")
FAMILY_ERRORS = ("correct", "misclassified")


@dataclass(frozen=True)
class SampleMetric:
    value: float | None
    numerator: int
    denominator: int
    denominator_definition: str
    unavailable_reason: str | None


def _rate(numerator, denominator, definition):
    return SampleMetric(numerator / denominator if denominator else None,
                        numerator, denominator, definition,
                        None if denominator else "Unavailable: denominator is zero in the uploaded sample.")


def binary_metrics(actual, predicted):
    actual, predicted = tuple(actual), tuple(predicted)
    if len(actual) != len(predicted) or any(v not in (0, 1) for v in (*actual, *predicted)):
        raise ValueError("aligned binary labels and decisions required")
    tp = sum(a == 1 and p == 1 for a, p in zip(actual, predicted))
    tn = sum(a == 0 and p == 0 for a, p in zip(actual, predicted))
    fp = sum(a == 0 and p == 1 for a, p in zip(actual, predicted))
    fn = sum(a == 1 and p == 0 for a, p in zip(actual, predicted))
    return {
        "scope": SAMPLE_SCOPE, "record_count": len(actual),
        "counts": {"TP": tp, "TN": tn, "FP": fp, "FN": fn},
        "confusion_matrix": {"actual_order": ["normal", "attack"],
                             "predicted_order": ["normal", "attack"], "values": [[tn, fp], [fn, tp]]},
        "metrics": {name: asdict(metric) for name, metric in {
            "precision": _rate(tp, tp + fp, "TP + FP (predicted attacks)"),
            "recall": _rate(tp, tp + fn, "TP + FN (actual attacks)"),
            "F1": _rate(2 * tp, 2 * tp + fp + fn, "2*TP + FP + FN"),
            "FPR": _rate(fp, fp + tn, "FP + TN (actual normals)"),
            "FNR": _rate(fn, fn + tp, "FN + TP (actual attacks)"),
        }.items()},
    }


def validate_alignment(input_data, records):
    if tuple(input_data.frame.id) != tuple(r.record_id for r in records):
        raise ValueError("review records must retain original input alignment")


def review_rows(input_data, records):
    """Independent ground truth columns; missing truth is never synthesized."""
    validate_alignment(input_data, records)
    binary_labels = input_data.frame.label.tolist() if input_data.has_binary_labels else None
    family_labels = input_data.frame.attack_cat.tolist() if input_data.has_family_labels else None
    rows = []
    for i, record in enumerate(records):
        row = {"actual_binary_label": None, "binary_error": None,
               "actual_family_label": None, "family_error": None}
        if input_data.has_binary_labels:
            actual = int(binary_labels[i])
            row["actual_binary_label"] = actual
            row["binary_error"] = ("TP" if actual else "FP") if record.binary_prediction == "attack" else ("FN" if actual else "TN")
        if input_data.has_family_labels:
            actual = str(family_labels[i])
            row["actual_family_label"] = actual
            row["family_error"] = "correct" if actual == record.family_prediction_raw else "misclassified"
        rows.append(row)
    return tuple(rows)


def original_binary_metrics(input_data, records):
    validate_alignment(input_data, records)
    if not input_data.has_binary_labels:
        return None
    return binary_metrics(input_data.frame.label, (int(r.binary_prediction == "attack") for r in records))


@dataclass(frozen=True)
class ThresholdSimulation:
    threshold: float
    decisions: tuple[int, ...]
    # Counts and metrics are recomputed from aligned labels; no mutable results.

    def report(self, input_data):
        return {"kind": "ephemeral, sample-specific threshold simulation",
                "threshold": self.threshold, "baseline_threshold": BASELINE_THRESHOLD,
                "comparison_rule": COMPARISON_RULE, "sample_scope": SAMPLE_SCOPE,
                "alert_count": sum(self.decisions),
                "sample_metrics": binary_metrics(input_data.frame.label, self.decisions)}


def simulate_threshold(input_data, records, threshold=BASELINE_THRESHOLD):
    validate_alignment(input_data, records)
    if not input_data.has_binary_labels:
        raise ValueError("uploaded binary labels are required for simulation")
    if isinstance(threshold, bool) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be finite and between zero and one")
    return ThresholdSimulation(float(threshold), tuple(int(r.attack_model_score > threshold) for r in records))


def review_indices(records, rows, *, actual_binary=None, binary_errors=None,
                   actual_family=None, predicted_family=None, family_errors=None,
                   score_range=(0.0, 1.0), **queue_filters):
    """Filter/sort original indices; range endpoints included and ties stable."""
    if len(records) != len(rows):
        raise ValueError("aligned review rows required")
    low, high = score_range
    if not 0 <= low <= high <= 1:
        raise ValueError("invalid score range")
    filters = (("actual_binary_label", actual_binary), ("binary_error", binary_errors),
               ("actual_family_label", actual_family), ("family_error", family_errors))
    return [i for i in queue_indices(records, **queue_filters)
            if low <= records[i].attack_model_score <= high
            and all(values is None or rows[i][key] in values for key, values in filters)
            and (predicted_family is None or records[i].family_prediction_raw in predicted_family)]
