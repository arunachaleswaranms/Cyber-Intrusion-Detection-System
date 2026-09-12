"""Apply the frozen validation-only model-selection rule."""

from __future__ import annotations

import json
import math
from pathlib import Path

from cids.config import config_sha256, load_experiment_config, validate_experiment_config

MODEL_SELECTION_VERSION = "unsw-nb15-model-selection-v1"
DEFAULT_MODEL_SELECTION = (
    Path(__file__).resolve().parents[2] / "configs" / "v2-model-selection-v1.json"
)


class ModelSelectionError(ValueError):
    """Raised when candidate results cannot satisfy the frozen selection rule."""


def _metric_value(metrics: dict, metric: str, model_name: str) -> float:
    value = metrics.get(metric)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ModelSelectionError(f"{model_name} is missing numeric metric {metric!r}")
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ModelSelectionError(f"{model_name} metric {metric!r} is not finite")
    return rendered


def rank_models(task: str, candidates: dict[str, dict], config: dict) -> list[str]:
    validate_experiment_config(config)
    try:
        selection = config["selection"]["tasks"][task]
    except KeyError as exc:
        raise ModelSelectionError(f"unsupported selection task: {task!r}") from exc
    expected = set(selection["candidate_models"])
    actual = set(candidates)
    if actual != expected:
        raise ModelSelectionError(
            f"{task} candidate mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )

    def ranking_key(model_name: str) -> tuple[float, ...]:
        values: list[float] = []
        for rule in selection["ranking"]:
            value = _metric_value(candidates[model_name], rule["metric"], model_name)
            values.append(-value if rule["direction"] == "maximize" else value)
        return tuple(values)

    return sorted(candidates, key=ranking_key)


def validate_model_selection(selection: object, config: dict) -> dict:
    validate_experiment_config(config)
    if not isinstance(selection, dict):
        raise ModelSelectionError("model selection must be an object")
    expected_root = {
        "selection_version",
        "experiment_config_version",
        "experiment_config_sha256",
        "selection_partition",
        "official_test_status",
        "selected",
    }
    if set(selection) != expected_root:
        raise ModelSelectionError("model selection keys do not match the contract")
    if selection["selection_version"] != MODEL_SELECTION_VERSION:
        raise ModelSelectionError("unsupported model selection version")
    if selection["experiment_config_version"] != config["config_version"]:
        raise ModelSelectionError("model selection config version mismatch")
    if selection["experiment_config_sha256"] != config_sha256(config):
        raise ModelSelectionError("model selection config digest mismatch")
    if selection["selection_partition"] != "validation":
        raise ModelSelectionError("models must be selected from validation data")
    if selection["official_test_status"] != "sealed":
        raise ModelSelectionError("model selection must preserve the test seal")
    selected = selection["selected"]
    if not isinstance(selected, dict) or set(selected) != {"binary", "multiclass"}:
        raise ModelSelectionError("model selection must contain both tasks")

    for task, task_selection in selected.items():
        expected_keys = {
            "selected_model",
            "selected_artifact_version",
            "candidate_order",
            "ranking",
            "selected_validation_metrics",
        }
        if not isinstance(task_selection, dict) or set(task_selection) != expected_keys:
            raise ModelSelectionError(f"{task} selection keys do not match")
        task_config = config["selection"]["tasks"][task]
        candidate_order = task_selection["candidate_order"]
        if (
            not isinstance(candidate_order, list)
            or len(candidate_order) != len(set(candidate_order))
            or set(candidate_order) != set(task_config["candidate_models"])
        ):
            raise ModelSelectionError(f"{task} selected candidate set does not match")
        if not candidate_order or task_selection["selected_model"] != candidate_order[0]:
            raise ModelSelectionError(f"{task} selected model is not ranked first")
        artifact_version = task_selection["selected_artifact_version"]
        if not isinstance(artifact_version, str) or not artifact_version:
            raise ModelSelectionError(f"{task} selected artifact version is invalid")
        if task_selection["ranking"] != task_config["ranking"]:
            raise ModelSelectionError(f"{task} ranking rule does not match")
        metric_names = {rule["metric"] for rule in task_config["ranking"]}
        metrics = task_selection["selected_validation_metrics"]
        if not isinstance(metrics, dict) or set(metrics) != metric_names:
            raise ModelSelectionError(f"{task} selected metrics do not match")
        for metric in metrics:
            _metric_value(metrics, metric, task_selection["selected_model"])
    return selection


def load_model_selection(
    path: str | Path = DEFAULT_MODEL_SELECTION,
    *,
    config: dict | None = None,
) -> dict:
    selection_path = Path(path)
    try:
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelSelectionError(f"model selection not found: {selection_path}") from exc
    except json.JSONDecodeError as exc:
        raise ModelSelectionError(f"invalid model selection JSON: {selection_path}") from exc
    experiment_config = load_experiment_config() if config is None else config
    return validate_model_selection(selection, experiment_config)
