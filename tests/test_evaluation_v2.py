import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.evaluation import EvaluationError, evaluate_classifier  # noqa: E402


class BinaryEstimator:
    classes_ = np.array([0, 1])

    def predict(self, features):
        values = features.toarray() if sparse.issparse(features) else np.asarray(features)
        return (values[:, 0].astype(int) % 2).astype(int)

    def predict_proba(self, features):
        attack = np.where(self.predict(features) == 1, 0.8, 0.2)
        return np.column_stack([1 - attack, attack])


class MulticlassEstimator:
    classes_ = np.array(["normal", "generic", "exploits"])

    def predict(self, features):
        return self.classes_[np.asarray(features)[:, 0].astype(int)]

    def predict_proba(self, features):
        predictions = self.predict(features)
        probabilities = np.full((len(predictions), 3), 0.1)
        for index, prediction in enumerate(predictions):
            probabilities[index, list(self.classes_).index(prediction)] = 0.8
        return probabilities


def test_binary_security_metrics_and_family_detection_rates():
    features = sparse.csr_matrix(np.arange(4).reshape(-1, 1))
    target = np.array([0, 0, 1, 1])
    families = pd.Series(["normal", "normal", "generic", "exploits"])

    results = evaluate_classifier(
        BinaryEstimator(),
        features,
        target,
        task="binary",
        family_labels=families,
    )

    assert results["confusion_matrix"] == [[1, 1], [1, 1]]
    assert results["false_positive_rate"] == 0.5
    assert results["false_negative_rate"] == 0.5
    assert results["per_family_detection_rate"] == {
        "exploits": 1.0,
        "generic": 0.0,
    }
    assert results["prediction_ms_per_record"] >= 0


def test_multiclass_reports_one_vs_rest_rates_and_probability_metrics():
    features = np.array([[0], [1], [2], [0], [2], [1]])
    target = np.array(
        ["normal", "generic", "exploits", "normal", "generic", "exploits"]
    )

    results = evaluate_classifier(
        MulticlassEstimator(),
        features,
        target,
        task="multiclass",
        family_labels=pd.Series(target),
    )

    assert results["labels"] == ["normal", "generic", "exploits"]
    assert set(results["false_positive_rate_by_class"]) == set(results["labels"])
    assert set(results["false_negative_rate_by_class"]) == set(results["labels"])
    assert set(results["per_family_detection_rate"]) == {"generic", "exploits"}
    assert 0 <= results["roc_auc_ovr_macro"] <= 1
    assert 0 <= results["pr_auc_macro"] <= 1


def test_rejects_unsupported_task():
    with pytest.raises(EvaluationError, match="unsupported task"):
        evaluate_classifier(
            BinaryEstimator(),
            np.array([[0], [1]]),
            np.array([0, 1]),
            task="invalid",
            family_labels=pd.Series(["normal", "generic"]),
        )
