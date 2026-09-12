import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.config import load_experiment_config  # noqa: E402
from cids.final_protocol import (  # noqa: E402
    FINAL_CONFIRMATION_PHRASE,
    FINAL_PROTOCOL_VERSION,
    REPRODUCTION_METRIC_ABS_TOLERANCE,
    FinalProtocolError,
    load_final_protocol,
    protocol_sha256,
    validate_final_protocol,
    validate_reproduced_selection,
)
from cids.selection import load_model_selection  # noqa: E402


def contracts():
    config = load_experiment_config()
    selection = load_model_selection(config=config)
    protocol = load_final_protocol(config=config, selection=selection)
    return config, selection, protocol


def test_loads_protocol_bound_to_frozen_config_and_selection():
    config, selection, protocol = contracts()

    assert protocol["protocol_version"] == FINAL_PROTOCOL_VERSION
    assert protocol["run_guard"]["confirmation_phrase"] == (
        FINAL_CONFIRMATION_PHRASE
    )
    assert protocol["official_test"]["evaluation_runs"] == 1
    assert protocol["run_guard"]["reproduction_metric_abs_tolerance"] == (
        REPRODUCTION_METRIC_ABS_TOLERANCE
    )
    assert protocol_sha256(protocol, config=config, selection=selection) == (
        "c4fc000d24d27cada9740c1350c3b1e22d710cbd537353f33c9036a980ccb517"
    )


def test_rejects_protocol_model_different_from_recorded_selection():
    config, selection, protocol = contracts()
    changed = copy.deepcopy(protocol)
    changed["official_test"]["tasks"]["binary"] = "random_forest"

    with pytest.raises(FinalProtocolError, match="do not match selection"):
        validate_final_protocol(changed, config=config, selection=selection)


def test_accepts_observed_apple_silicon_reproduction_metrics():
    config, selection, _ = contracts()
    reproduced = copy.deepcopy(selection)
    reproduced["selected"]["binary"]["selected_validation_metrics"] = {
        "balanced_accuracy": 0.9339646433461041,
        "f1_macro": 0.9333309301802998,
        "false_positive_rate": 0.08605081281027938,
    }
    reproduced["selected"]["multiclass"]["selected_validation_metrics"] = {
        "balanced_accuracy": 0.8122015736919435,
        "f1_macro": 0.744975068130632,
        "false_positive_rate_macro": 0.01700784073789189,
    }

    validate_reproduced_selection(reproduced, selection, config=config)


def test_accepts_reproduction_just_inside_metric_tolerance():
    config, selection, _ = contracts()
    reproduced = copy.deepcopy(selection)
    reproduced["selected"]["binary"]["selected_validation_metrics"][
        "f1_macro"
    ] -= REPRODUCTION_METRIC_ABS_TOLERANCE - 1e-6

    validate_reproduced_selection(reproduced, selection, config=config)


def test_rejects_reproduction_just_outside_metric_tolerance():
    config, selection, _ = contracts()
    reproduced = copy.deepcopy(selection)
    reproduced["selected"]["binary"]["selected_validation_metrics"][
        "f1_macro"
    ] -= REPRODUCTION_METRIC_ABS_TOLERANCE + 1e-6

    with pytest.raises(FinalProtocolError, match="differs beyond tolerance"):
        validate_reproduced_selection(reproduced, selection, config=config)


def test_rejects_changed_candidate_order_with_metrics_in_tolerance():
    config, selection, _ = contracts()
    reproduced = copy.deepcopy(selection)
    reproduced["selected"]["binary"]["candidate_order"] = [
        "random_forest",
        "hist_gradient_boosting",
        "isolation_forest",
    ]
    reproduced["selected"]["binary"]["selected_model"] = "random_forest"

    with pytest.raises(FinalProtocolError, match="differs for selected_model"):
        validate_reproduced_selection(reproduced, selection, config=config)


def test_rejects_protocol_with_different_metric_tolerance():
    config, selection, protocol = contracts()
    changed = copy.deepcopy(protocol)
    changed["run_guard"]["reproduction_metric_abs_tolerance"] = 0.01

    with pytest.raises(FinalProtocolError, match="unsupported reproduction"):
        validate_final_protocol(changed, config=config, selection=selection)
