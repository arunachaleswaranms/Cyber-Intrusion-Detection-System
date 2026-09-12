"""Load and validate the frozen v2.0 experiment configuration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cids.datasets.split_unsw_nb15 import SPLIT_POLICY_VERSION
from cids.datasets.unsw_nb15 import SCHEMA_VERSION
from cids.preprocessing import PREPROCESSOR_VERSION

EXPERIMENT_CONFIG_VERSION = "unsw-nb15-experiment-v1"
DEFAULT_EXPERIMENT_CONFIG = (
    Path(__file__).resolve().parents[2] / "configs" / "v2-baseline-v1.json"
)
SUPERVISED_MODEL_NAMES = {"random_forest", "hist_gradient_boosting"}
ANOMALY_MODEL_NAME = "isolation_forest"


class ExperimentConfigError(ValueError):
    """Raised when the experiment configuration violates its contract."""


def _exact_keys(value: object, expected: set[str], location: str) -> dict:
    if not isinstance(value, dict):
        raise ExperimentConfigError(f"{location} must be an object")
    actual = set(value)
    if actual != expected:
        raise ExperimentConfigError(
            f"{location} keys mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    return value


def validate_experiment_config(config: object) -> dict:
    root = _exact_keys(
        config,
        {
            "config_version",
            "dataset",
            "split",
            "preprocessing",
            "models",
            "selection",
        },
        "config",
    )
    if root["config_version"] != EXPERIMENT_CONFIG_VERSION:
        raise ExperimentConfigError("unsupported config_version")

    dataset = _exact_keys(
        root["dataset"], {"manifest_version", "schema_version"}, "dataset"
    )
    if dataset != {"manifest_version": 1, "schema_version": SCHEMA_VERSION}:
        raise ExperimentConfigError("dataset contract does not match the code")

    split = _exact_keys(
        root["split"],
        {"policy_version", "seed", "validation_fraction"},
        "split",
    )
    if split["policy_version"] != SPLIT_POLICY_VERSION:
        raise ExperimentConfigError("split policy does not match the code")
    if not isinstance(split["seed"], int) or isinstance(split["seed"], bool):
        raise ExperimentConfigError("split seed must be an integer")
    if not 0 < split["validation_fraction"] < 1:
        raise ExperimentConfigError("validation fraction must be between 0 and 1")

    preprocessing = _exact_keys(root["preprocessing"], {"version"}, "preprocessing")
    if preprocessing["version"] != PREPROCESSOR_VERSION:
        raise ExperimentConfigError("preprocessor version does not match the code")

    models = _exact_keys(root["models"], {"supervised", "anomaly"}, "models")
    supervised = models["supervised"]
    if not isinstance(supervised, dict) or set(supervised) != SUPERVISED_MODEL_NAMES:
        raise ExperimentConfigError("supervised model set is not frozen correctly")
    if not all(isinstance(parameters, dict) for parameters in supervised.values()):
        raise ExperimentConfigError("supervised model parameters must be objects")

    anomaly = _exact_keys(
        models["anomaly"],
        {"name", "parameters", "training_scope", "threshold"},
        "models.anomaly",
    )
    if anomaly["name"] != ANOMALY_MODEL_NAME:
        raise ExperimentConfigError("unsupported anomaly model")
    if anomaly["training_scope"] != "normal_only":
        raise ExperimentConfigError("anomaly training scope must be normal_only")
    if not isinstance(anomaly["parameters"], dict):
        raise ExperimentConfigError("anomaly parameters must be an object")
    threshold = _exact_keys(
        anomaly["threshold"],
        {"strategy", "normal_training_quantile"},
        "models.anomaly.threshold",
    )
    if threshold["strategy"] != "normal_training_score_quantile":
        raise ExperimentConfigError("unsupported anomaly threshold strategy")
    if not 0 < threshold["normal_training_quantile"] < 1:
        raise ExperimentConfigError("anomaly threshold quantile must be between 0 and 1")

    selection = _exact_keys(
        root["selection"],
        {
            "official_test_status",
            "partition",
            "tasks",
            "unlock_official_test_after",
        },
        "selection",
    )
    if selection["partition"] != "validation":
        raise ExperimentConfigError("model selection must use validation data")
    if selection["official_test_status"] != "sealed":
        raise ExperimentConfigError("official test must remain sealed")
    tasks = _exact_keys(selection["tasks"], {"binary", "multiclass"}, "selection.tasks")
    expected_candidates = {
        "binary": SUPERVISED_MODEL_NAMES | {ANOMALY_MODEL_NAME},
        "multiclass": SUPERVISED_MODEL_NAMES,
    }
    for task, expected in expected_candidates.items():
        task_config = _exact_keys(
            tasks[task], {"candidate_models", "ranking"}, f"selection.tasks.{task}"
        )
        candidates = task_config["candidate_models"]
        if (
            not isinstance(candidates, list)
            or len(candidates) != len(set(candidates))
            or set(candidates) != expected
        ):
            raise ExperimentConfigError(f"{task} candidate model set is incorrect")
        ranking = task_config["ranking"]
        if not isinstance(ranking, list) or not ranking:
            raise ExperimentConfigError(f"{task} ranking must be a non-empty list")
        ranking_metrics: set[str] = set()
        for rule in ranking:
            checked = _exact_keys(rule, {"metric", "direction"}, f"{task} ranking")
            metric = checked["metric"]
            if not isinstance(metric, str) or not metric or metric in ranking_metrics:
                raise ExperimentConfigError(f"{task} ranking metric is invalid")
            ranking_metrics.add(metric)
            if checked["direction"] not in {"maximize", "minimize"}:
                raise ExperimentConfigError(f"{task} ranking direction is invalid")
    unlock = selection["unlock_official_test_after"]
    if not isinstance(unlock, list) or not unlock or not all(
        isinstance(item, str) and item for item in unlock
    ):
        raise ExperimentConfigError("official-test unlock conditions are invalid")
    return root


def load_experiment_config(
    path: str | Path = DEFAULT_EXPERIMENT_CONFIG,
) -> dict:
    config_path = Path(path)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExperimentConfigError(f"config not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ExperimentConfigError(f"invalid JSON config: {config_path}") from exc
    return validate_experiment_config(config)


def config_sha256(config: dict) -> str:
    validate_experiment_config(config)
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_split_report(config: dict, report: dict) -> None:
    validate_experiment_config(config)
    split = config["split"]
    expected = {
        "split_policy_version": split["policy_version"],
        "seed": split["seed"],
        "validation_fraction": split["validation_fraction"],
    }
    actual = {key: report.get(key) for key in expected}
    if actual != expected:
        raise ExperimentConfigError(
            f"prepared split does not match experiment config: {actual!r}"
        )
