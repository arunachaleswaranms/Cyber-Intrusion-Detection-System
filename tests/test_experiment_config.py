import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.config import (  # noqa: E402
    ExperimentConfigError,
    config_sha256,
    load_experiment_config,
    validate_experiment_config,
    validate_split_report,
)


def test_loads_frozen_config_with_stable_digest():
    first = load_experiment_config()
    second = load_experiment_config()

    assert first["selection"]["official_test_status"] == "sealed"
    assert first["models"]["anomaly"]["training_scope"] == "normal_only"
    assert config_sha256(first) == config_sha256(second)


def test_rejects_unknown_config_keys():
    config = load_experiment_config()
    config["unexpected"] = True

    with pytest.raises(ExperimentConfigError, match="keys mismatch"):
        validate_experiment_config(config)


def test_rejects_unsealed_official_test():
    config = load_experiment_config()
    config["selection"]["official_test_status"] = "open"

    with pytest.raises(ExperimentConfigError, match="must remain sealed"):
        validate_experiment_config(config)


def test_rejects_duplicate_candidate_models():
    config = load_experiment_config()
    config["selection"]["tasks"]["binary"]["candidate_models"].append(
        "isolation_forest"
    )

    with pytest.raises(ExperimentConfigError, match="candidate model set"):
        validate_experiment_config(config)


def test_split_report_must_match_frozen_values():
    config = load_experiment_config()
    report = {
        "split_policy_version": config["split"]["policy_version"],
        "seed": config["split"]["seed"],
        "validation_fraction": config["split"]["validation_fraction"],
    }
    validate_split_report(config, report)
    changed = copy.deepcopy(report)
    changed["seed"] = 7

    with pytest.raises(ExperimentConfigError, match="does not match"):
        validate_split_report(config, changed)
