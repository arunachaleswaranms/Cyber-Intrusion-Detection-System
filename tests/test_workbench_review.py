"""Synthetic sample review: labels independent, metrics explicit, no scoring."""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.workbench.review import (binary_metrics, original_binary_metrics, review_rows,
                                   review_indices, simulate_threshold, COMPARISON_RULE)
from cids.workbench.contracts import parse_inference_csv
from test_workbench_contracts import valid_frame, payload
from test_workbench_analysis import record


def sample(binary=True, family=True):
    frame = valid_frame(4).assign(id=["a", "b", "c", "d"])
    if binary:
        frame["label"] = [1, 0, 0, 1]
    if family:
        frame["attack_cat"] = ["generic", "normal", "normal", "exploits"]
    records = (record("a", "attack", "generic", .9), record("b", "normal", "generic", .1),
               record("c", "attack", "normal", .6), record("d", "normal", "exploits", .5))
    return parse_inference_csv(payload(frame)), records


@pytest.mark.parametrize("binary,family", [(False, False), (True, False), (False, True), (True, True)])
def test_each_truth_column_is_independent(binary, family):
    data, records = sample(binary, family)
    rows = review_rows(data, records)
    assert [r["binary_error"] for r in rows] == (["TP", "TN", "FP", "FN"] if binary else [None] * 4)
    # Binary-normal + raw-correct attack family remains correct; triage is ignored.
    assert [r["family_error"] for r in rows] == (["correct", "misclassified", "correct", "correct"] if family else [None] * 4)
    assert (original_binary_metrics(data, records) is not None) == binary
    if not binary:
        with pytest.raises(ValueError, match="binary labels"):
            simulate_threshold(data, records)


def test_known_counts_metrics_and_explicit_denominators():
    data, records = sample()
    report = original_binary_metrics(data, records)
    assert report["counts"] == {"TP": 1, "TN": 1, "FP": 1, "FN": 1}
    assert report["confusion_matrix"]["values"] == [[1, 1], [1, 1]]
    for metric in report["metrics"].values():
        assert metric["value"] == .5 and metric["denominator"] > 0
        assert metric["denominator_definition"] and metric["unavailable_reason"] is None
    assert report["metrics"]["F1"]["numerator"] == 2
    assert report["metrics"]["F1"]["denominator"] == 4
    other = binary_metrics([0, 0, 0, 1, 1, 1], [0, 0, 1, 1, 1, 0])
    assert other["counts"] == {"TP": 2, "TN": 2, "FP": 1, "FN": 1}
    assert other["metrics"]["recall"]["value"] == pytest.approx(2 / 3)
    assert other["metrics"]["FPR"]["value"] == pytest.approx(1 / 3)


@pytest.mark.parametrize("actual,predicted,undefined", [
    ([0, 0], [0, 0], {"precision", "recall", "F1", "FNR"}),
    ([1, 1], [0, 0], {"precision", "FPR"}),
    ([1, 1], [1, 1], {"FPR"}),
    ([], [], {"precision", "recall", "F1", "FPR", "FNR"}),
])
def test_undefined_rates_are_unavailable_and_defined_zero_is_zero(actual, predicted, undefined):
    metrics = binary_metrics(actual, predicted)["metrics"]
    assert {key for key, m in metrics.items() if m["value"] is None} == undefined
    for m in metrics.values():
        if m["value"] is None:
            assert m["denominator"] == 0 and "denominator is zero" in m["unavailable_reason"]
    if actual == [1, 1] and predicted == [0, 0]:
        assert metrics["recall"]["value"] == 0 and metrics["F1"]["value"] == 0


def test_threshold_ties_endpoints_and_original_result_preservation():
    data, records = sample()
    original = tuple(records)
    assert simulate_threshold(data, records).decisions == (1, 0, 1, 0)
    assert simulate_threshold(data, records, .6).decisions == (1, 0, 0, 0)
    assert simulate_threshold(data, records, 0).decisions == (1, 1, 1, 1)
    assert simulate_threshold(data, records, 1).decisions == (0, 0, 0, 0)
    for threshold in (.1, .5, .6, .9):
        report = simulate_threshold(data, records, threshold).report(data)
        assert report["sample_scope"] == "full_current_uploaded_sample"
        assert report["comparison_rule"] == COMPARISON_RULE
    assert records == original and records[3].binary_prediction == "normal"


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), -1, 1.1, True])
def test_invalid_thresholds(threshold):
    with pytest.raises(ValueError):
        simulate_threshold(*sample(), threshold)


def test_label_error_score_prediction_band_and_disagreement_filters_keep_indices():
    data, records = sample()
    rows = review_rows(data, records)
    assert review_indices(records, rows, actual_binary=[1], order="score") == [0, 3]
    assert review_indices(records, rows, binary_errors=["FP"]) == [2]
    assert review_indices(records, rows, actual_family=["exploits"], predicted_family=["exploits"]) == [3]
    assert review_indices(records, rows, family_errors=["misclassified"]) == [1]
    assert review_indices(records, rows, score_range=(.5, .6)) == [2, 3]
    assert review_indices(records, rows, disagreements_only=True, order="score") == [2, 3, 1]
    assert review_indices(records, rows, bands=["not_alerted"], predictions=["normal"]) == [1, 3]
    assert review_indices(records, rows, actual_binary=[]) == []


def test_review_rejects_misaligned_records():
    data, records = sample()
    with pytest.raises(ValueError, match="alignment"):
        review_rows(data, records[::-1])


def test_frozen_estimator_boundary_and_exact_tie_from_pinned_source(monkeypatch):
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    # Only a synthetic raw margin; no fitting, artifacts, dataset or scoring.
    estimator = HistGradientBoostingClassifier()
    estimator.classes_ = np.array([0, 1])
    monkeypatch.setattr(estimator, "_raw_predict", lambda _: np.array([[-1.0], [0.0], [1.0]]))
    assert estimator.predict(None).tolist() == [0, 0, 1]
