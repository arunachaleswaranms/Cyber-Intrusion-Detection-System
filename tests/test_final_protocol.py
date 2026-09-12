import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.config import load_experiment_config  # noqa: E402
from cids.final_protocol import (  # noqa: E402
    FINAL_CONFIRMATION_PHRASE,
    FINAL_PROTOCOL_VERSION,
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
    assert len(protocol_sha256(protocol, config=config, selection=selection)) == 64


def test_rejects_protocol_model_different_from_recorded_selection():
    config, selection, protocol = contracts()
    changed = copy.deepcopy(protocol)
    changed["official_test"]["tasks"]["binary"] = "random_forest"

    with pytest.raises(FinalProtocolError, match="do not match selection"):
        validate_final_protocol(changed, config=config, selection=selection)


def test_accepts_reproduced_selection_with_negligible_float_difference():
    config, selection, _ = contracts()
    reproduced = copy.deepcopy(selection)
    reproduced["selected"]["binary"]["selected_validation_metrics"][
        "f1_macro"
    ] += 1e-12

    validate_reproduced_selection(reproduced, selection, config=config)


def test_rejects_reproduction_with_changed_metric():
    config, selection, _ = contracts()
    reproduced = copy.deepcopy(selection)
    reproduced["selected"]["binary"]["selected_validation_metrics"][
        "f1_macro"
    ] -= 0.01

    with pytest.raises(FinalProtocolError, match="reproduction metric differs"):
        validate_reproduced_selection(reproduced, selection, config=config)
