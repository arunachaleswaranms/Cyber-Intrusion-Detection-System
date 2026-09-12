import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.config import load_experiment_config  # noqa: E402
from cids.selection import (  # noqa: E402
    ModelSelectionError,
    load_model_selection,
    rank_models,
    validate_model_selection,
)


def test_loads_recorded_selection_with_both_frozen_winners():
    selection = load_model_selection()

    assert selection["selected"]["binary"]["selected_model"] == (
        "hist_gradient_boosting"
    )
    assert selection["selected"]["multiclass"]["selected_model"] == (
        "hist_gradient_boosting"
    )
    assert selection["official_test_status"] == "sealed"


def test_ranks_binary_models_by_frozen_rule():
    config = load_experiment_config()
    candidates = {
        "random_forest": {
            "f1_macro": 0.92,
            "balanced_accuracy": 0.94,
            "false_positive_rate": 0.05,
        },
        "hist_gradient_boosting": {
            "f1_macro": 0.93,
            "balanced_accuracy": 0.91,
            "false_positive_rate": 0.04,
        },
        "isolation_forest": {
            "f1_macro": 0.50,
            "balanced_accuracy": 0.55,
            "false_positive_rate": 0.03,
        },
    }

    assert rank_models("binary", candidates, config) == [
        "hist_gradient_boosting",
        "random_forest",
        "isolation_forest",
    ]


def test_uses_tie_breakers_in_declared_order():
    config = load_experiment_config()
    candidates = {
        "random_forest": {
            "f1_macro": 0.90,
            "balanced_accuracy": 0.90,
            "false_positive_rate_macro": 0.03,
        },
        "hist_gradient_boosting": {
            "f1_macro": 0.90,
            "balanced_accuracy": 0.91,
            "false_positive_rate_macro": 0.04,
        },
    }

    assert rank_models("multiclass", candidates, config)[0] == (
        "hist_gradient_boosting"
    )


def test_rejects_missing_candidate():
    config = load_experiment_config()

    with pytest.raises(ModelSelectionError, match="candidate mismatch"):
        rank_models("multiclass", {"random_forest": {}}, config)


def test_rejects_selection_that_claims_test_was_opened():
    config = load_experiment_config()
    selection = load_model_selection(config=config)
    selection["official_test_status"] = "evaluated"

    with pytest.raises(ModelSelectionError, match="preserve the test seal"):
        validate_model_selection(selection, config)
