"""Validate the frozen one-time official-test evaluation protocol."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from cids.config import config_sha256, load_experiment_config
from cids.selection import load_model_selection, selection_sha256

FINAL_PROTOCOL_VERSION = "unsw-nb15-final-evaluation-v1"
FINAL_CONFIRMATION_PHRASE = "EVALUATE_OFFICIAL_TEST_ONCE"
DEFAULT_FINAL_PROTOCOL = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "v2-final-evaluation-v1.json"
)


class FinalProtocolError(ValueError):
    """Raised when the final-evaluation protocol is missing or inconsistent."""


def _exact_keys(value: object, expected: set[str], location: str) -> dict:
    if not isinstance(value, dict):
        raise FinalProtocolError(f"{location} must be an object")
    actual = set(value)
    if actual != expected:
        raise FinalProtocolError(
            f"{location} keys mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    return value


def validate_final_protocol(
    protocol: object,
    *,
    config: dict,
    selection: dict,
) -> dict:
    root = _exact_keys(
        protocol,
        {
            "protocol_version",
            "experiment_config_sha256",
            "model_selection_sha256",
            "final_training",
            "official_test",
            "run_guard",
        },
        "final protocol",
    )
    if root["protocol_version"] != FINAL_PROTOCOL_VERSION:
        raise FinalProtocolError("unsupported final protocol version")
    if root["experiment_config_sha256"] != config_sha256(config):
        raise FinalProtocolError("final protocol config digest mismatch")
    if root["model_selection_sha256"] != selection_sha256(selection, config):
        raise FinalProtocolError("final protocol selection digest mismatch")

    training = _exact_keys(
        root["final_training"],
        {"partition", "preprocessing", "estimator"},
        "final_training",
    )
    expected_training = {
        "partition": "prepared_train_plus_validation",
        "preprocessing": "refit_on_combined_development",
        "estimator": "fresh_selected_model",
    }
    if training != expected_training:
        raise FinalProtocolError("unsupported final training protocol")

    official_test = _exact_keys(
        root["official_test"],
        {"partition", "evaluation_runs", "tasks"},
        "official_test",
    )
    if official_test["partition"] != "immutable_official_test":
        raise FinalProtocolError("official test partition must remain immutable")
    if official_test["evaluation_runs"] != 1:
        raise FinalProtocolError("official test must have exactly one evaluation run")
    tasks = _exact_keys(
        official_test["tasks"], {"binary", "multiclass"}, "official_test.tasks"
    )
    selected_models = {
        task: selection["selected"][task]["selected_model"]
        for task in ("binary", "multiclass")
    }
    if tasks != selected_models:
        raise FinalProtocolError("final protocol models do not match selection")

    guard = _exact_keys(
        root["run_guard"],
        {"confirmation_phrase", "output_directory_must_not_exist"},
        "run_guard",
    )
    if guard["confirmation_phrase"] != FINAL_CONFIRMATION_PHRASE:
        raise FinalProtocolError("final confirmation phrase does not match")
    if guard["output_directory_must_not_exist"] is not True:
        raise FinalProtocolError("final output directory must be new")
    return root


def load_final_protocol(
    path: str | Path = DEFAULT_FINAL_PROTOCOL,
    *,
    config: dict | None = None,
    selection: dict | None = None,
) -> dict:
    protocol_path = Path(path)
    try:
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FinalProtocolError(f"final protocol not found: {protocol_path}") from exc
    except json.JSONDecodeError as exc:
        raise FinalProtocolError(f"invalid final protocol JSON: {protocol_path}") from exc
    experiment_config = load_experiment_config() if config is None else config
    model_selection = (
        load_model_selection(config=experiment_config)
        if selection is None
        else selection
    )
    return validate_final_protocol(
        protocol,
        config=experiment_config,
        selection=model_selection,
    )


def protocol_sha256(protocol: dict, *, config: dict, selection: dict) -> str:
    validate_final_protocol(protocol, config=config, selection=selection)
    canonical = json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_reproduced_selection(
    reproduced: dict,
    recorded: dict,
    *,
    config: dict,
) -> None:
    """Require a clean validation rerun to reproduce the frozen selection."""
    from cids.selection import validate_model_selection

    validate_model_selection(reproduced, config)
    validate_model_selection(recorded, config)
    for task in ("binary", "multiclass"):
        actual = reproduced["selected"][task]
        expected = recorded["selected"][task]
        for key in (
            "selected_model",
            "selected_artifact_version",
            "candidate_order",
            "ranking",
        ):
            if actual[key] != expected[key]:
                raise FinalProtocolError(
                    f"{task} reproduction differs for {key}"
                )
        for metric, expected_value in expected["selected_validation_metrics"].items():
            actual_value = actual["selected_validation_metrics"][metric]
            if not math.isclose(
                float(actual_value),
                float(expected_value),
                rel_tol=1e-9,
                abs_tol=1e-12,
            ):
                raise FinalProtocolError(
                    f"{task} reproduction metric differs: {metric}"
                )
