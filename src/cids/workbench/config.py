"""Load and validate the versioned v2.1 workbench policy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

WORKBENCH_CONFIG_VERSION = "cids-workbench-config-v1"
DEFAULT_WORKBENCH_CONFIG = (
    Path(__file__).resolve().parents[3] / "configs" / "v2.1-workbench-v1.json"
)


class WorkbenchConfigError(ValueError):
    """Raised when workbench policy is missing, malformed, or unsupported."""


def _exact_keys(value: object, expected: set[str], location: str) -> dict:
    if not isinstance(value, dict):
        raise WorkbenchConfigError(f"{location} must be an object")
    actual = set(value)
    if actual != expected:
        raise WorkbenchConfigError(
            f"{location} keys mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    return value


def validate_workbench_config(config: object) -> dict:
    root = _exact_keys(
        config,
        {"config_version", "input", "queue", "explainability"},
        "workbench config",
    )
    if root["config_version"] != WORKBENCH_CONFIG_VERSION:
        raise WorkbenchConfigError("unsupported workbench config version")

    input_policy = _exact_keys(
        root["input"],
        {"encoding", "max_rows", "max_upload_bytes", "optional_columns"},
        "input",
    )
    if input_policy["encoding"] != "utf-8":
        raise WorkbenchConfigError("input encoding must be utf-8")
    for key in ("max_rows", "max_upload_bytes"):
        value = input_policy[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise WorkbenchConfigError(f"input {key} must be a positive integer")
    if input_policy["optional_columns"] != [
        "id",
        "event_time",
        "label",
        "attack_cat",
    ]:
        raise WorkbenchConfigError("optional input columns are not frozen correctly")

    queue = _exact_keys(root["queue"], {"higher_score_boundary"}, "queue")
    boundary = queue["higher_score_boundary"]
    if (
        not isinstance(boundary, (int, float))
        or isinstance(boundary, bool)
        or not 0 < boundary < 1
    ):
        raise WorkbenchConfigError("queue score boundary must be between 0 and 1")

    explainability = _exact_keys(
        root["explainability"],
        {
            "shap_version",
            "background_rows",
            "explain_rows",
            "max_explain_rows",
            "max_task_seconds",
            "additivity_abs_tolerance",
            "aggregation_abs_tolerance",
        },
        "explainability",
    )
    if explainability["shap_version"] != "0.52.0":
        raise WorkbenchConfigError("unsupported SHAP version")
    for key in ("background_rows", "explain_rows", "max_explain_rows"):
        value = explainability[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise WorkbenchConfigError(f"explainability {key} must be positive")
    if explainability["background_rows"] > 512:
        raise WorkbenchConfigError("explanation background exceeds hard limit")
    if explainability["max_explain_rows"] > 32:
        raise WorkbenchConfigError("explanation row limit exceeds hard limit")
    if explainability["explain_rows"] > explainability["max_explain_rows"]:
        raise WorkbenchConfigError("default explanation rows exceed maximum")
    for key in (
        "max_task_seconds",
        "additivity_abs_tolerance",
        "aggregation_abs_tolerance",
    ):
        value = explainability[key]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or value <= 0
        ):
            raise WorkbenchConfigError(f"explainability {key} must be positive")
    return root


def load_workbench_config(path: str | Path = DEFAULT_WORKBENCH_CONFIG) -> dict:
    config_path = Path(path)
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkbenchConfigError(f"workbench config not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkbenchConfigError(f"invalid workbench config: {config_path}") from exc
    return validate_workbench_config(value)


def workbench_config_sha256(config: dict) -> str:
    validated = validate_workbench_config(config)
    canonical = json.dumps(validated, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()
