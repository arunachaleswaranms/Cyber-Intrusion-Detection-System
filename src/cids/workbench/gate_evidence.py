"""Read and validate the accepted v2.1 Phase 1 explanation-gate evidence.

The gate report records correctness and resource diagnostics for the bounded
SHAP PermutationExplainer. It does not contain feature attributions, so it can
support statements about explanation *feasibility* but not about which
features the models rely on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from cids.datasets.unsw_nb15 import FEATURE_COLUMNS
from cids.workbench.config import validate_workbench_config, workbench_config_sha256
from cids.workbench.integrity import (
    EvidenceError,
    load_json_object,
    load_pinned_checksums,
    require_regular_file,
    verify_pinned_files,
)

DEFAULT_GATE_EVIDENCE_DIR = Path(__file__).resolve().parents[3] / "results" / "v2.1"
GATE_REPORT_FILENAME = "shap-gate-selected-v2.json"
GATE_CHECKSUM_FILENAME = "SHA256SUMS"
EXPECTED_GATE_HASHES = {
    GATE_REPORT_FILENAME: (
        "d6db9aae2368b09b33b22a666d67208e27f28c277a5e613b07aed12e0551f528"
    ),
}
# Mirrors cids.experiments.run_shap_gate.GATE_VERSION, which imports SHAP and
# joblib and therefore must not be imported by evidence mode.
GATE_VERSION = "cids-shap-compatibility-gate-v2"
GATE_TASKS = ("binary", "multiclass")
GATE_TASK_KEYS = {
    "artifact_sha256",
    "background_partition",
    "background_rows",
    "class_labels",
    "elapsed_seconds",
    "explained_classes",
    "explained_rows",
    "explainer_algorithm",
    "foreground_partition",
    "masker",
    "max_additivity_error",
    "max_aggregation_error",
    "model_name",
    "model_output",
    "official_test_used_as_explanation_data",
    "permutation_rounds",
    "shap_values_shape",
    "source_feature_count",
    "task",
    "transformed_feature_count",
}


@dataclass(frozen=True)
class GateTaskEvidence:
    task: str
    model_name: str
    artifact_sha256: str
    class_labels: tuple
    explained_classes: tuple
    explainer_algorithm: str
    model_output: str
    masker: str
    background_partition: str
    background_rows: int
    foreground_partition: str
    explained_rows: int
    permutation_rounds: int
    max_additivity_error: float
    max_aggregation_error: float
    elapsed_seconds: float
    transformed_feature_count: int
    source_feature_count: int


@dataclass(frozen=True)
class ExplanationGateEvidence:
    report: dict
    tasks: dict[str, GateTaskEvidence]
    policy: dict
    sha256: dict[str, str]
    evidence_dir: Path


def _finite_number(value: object, location: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise EvidenceError(f"{location} must be a finite number")
    return float(value)


def _positive_int(value: object, location: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise EvidenceError(f"{location} must be a positive integer")
    return value


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _validate_task(task: str, value: object, policy: dict) -> GateTaskEvidence:
    if not isinstance(value, dict) or set(value) != GATE_TASK_KEYS:
        raise EvidenceError(f"gate {task} result keys do not match the gate contract")
    explain = policy["explainability"]
    if value["task"] != task:
        raise EvidenceError(f"gate {task} task label disagrees")
    if value["official_test_used_as_explanation_data"] is not False:
        raise EvidenceError(f"gate {task} used official-test data for explanations")
    if value["background_partition"] != "prepared_train":
        raise EvidenceError(
            f"gate {task} background is not the prepared training split"
        )
    if value["foreground_partition"] != "prepared_validation":
        raise EvidenceError(f"gate {task} foreground is not the validation split")
    if value["explainer_algorithm"] != explain["algorithm"]:
        raise EvidenceError(f"gate {task} explainer differs from the workbench policy")
    if value["permutation_rounds"] != explain["permutation_rounds"]:
        raise EvidenceError(f"gate {task} permutation rounds differ from the policy")
    if not _is_sha256(value["artifact_sha256"]):
        raise EvidenceError(f"gate {task} artifact digest is malformed")

    background_rows = _positive_int(value["background_rows"], f"gate {task} background")
    explained_rows = _positive_int(
        value["explained_rows"], f"gate {task} explained rows"
    )
    if background_rows != explain["background_rows"]:
        raise EvidenceError(f"gate {task} background size differs from the policy")
    if explained_rows > explain["max_explain_rows"]:
        raise EvidenceError(f"gate {task} explained more rows than the policy allows")

    additivity = _finite_number(
        value["max_additivity_error"], f"gate {task} additivity"
    )
    aggregation = _finite_number(
        value["max_aggregation_error"], f"gate {task} aggregation"
    )
    elapsed = _finite_number(value["elapsed_seconds"], f"gate {task} elapsed time")
    if not 0 <= additivity <= explain["additivity_abs_tolerance"]:
        raise EvidenceError(f"gate {task} additivity error exceeds tolerance")
    if not 0 <= aggregation <= explain["aggregation_abs_tolerance"]:
        raise EvidenceError(f"gate {task} aggregation error exceeds tolerance")
    if not 0 <= elapsed <= explain["max_task_seconds"]:
        raise EvidenceError(f"gate {task} exceeded the per-task time limit")

    source_features = _positive_int(
        value["source_feature_count"], f"gate {task} source features"
    )
    transformed = _positive_int(
        value["transformed_feature_count"], f"gate {task} transformed features"
    )
    if source_features != len(FEATURE_COLUMNS):
        raise EvidenceError(f"gate {task} source feature count is not the frozen 42")
    labels = value["class_labels"]
    explained = value["explained_classes"]
    if not isinstance(labels, list) or not labels:
        raise EvidenceError(f"gate {task} class labels are missing")
    if not isinstance(explained, list) or not set(explained) <= set(labels):
        raise EvidenceError(f"gate {task} explained classes are not model classes")
    shape = value["shap_values_shape"]
    expected_shape = (
        [explained_rows, transformed]
        if len(explained) == 1
        else [explained_rows, transformed, len(explained)]
    )
    if shape != expected_shape:
        raise EvidenceError(f"gate {task} SHAP value shape is inconsistent")

    return GateTaskEvidence(
        task=task,
        model_name=value["model_name"],
        artifact_sha256=value["artifact_sha256"],
        class_labels=tuple(labels),
        explained_classes=tuple(explained),
        explainer_algorithm=value["explainer_algorithm"],
        model_output=value["model_output"],
        masker=value["masker"],
        background_partition=value["background_partition"],
        background_rows=background_rows,
        foreground_partition=value["foreground_partition"],
        explained_rows=explained_rows,
        permutation_rounds=value["permutation_rounds"],
        max_additivity_error=additivity,
        max_aggregation_error=aggregation,
        elapsed_seconds=elapsed,
        transformed_feature_count=transformed,
        source_feature_count=source_features,
    )


def validate_gate_report(report: dict, policy: dict) -> dict[str, GateTaskEvidence]:
    """Check gate semantics against the committed workbench policy."""
    validated_policy = validate_workbench_config(policy)
    if report.get("gate_version") != GATE_VERSION:
        raise EvidenceError("unsupported explanation gate version")
    if report.get("status") != "passed":
        raise EvidenceError("explanation gate did not pass")
    if report.get("official_test_status") != "not_evaluated_by_gate":
        raise EvidenceError("explanation gate reports official-test access")
    if report.get("workbench_config_sha256") != workbench_config_sha256(
        validated_policy
    ):
        raise EvidenceError(
            "gate report was produced under a different workbench policy"
        )
    environment = report.get("environment")
    if not isinstance(environment, dict) or environment.get("shap") != (
        validated_policy["explainability"]["shap_version"]
    ):
        raise EvidenceError("gate environment does not record the pinned SHAP version")
    tasks = report.get("tasks")
    if not isinstance(tasks, dict) or set(tasks) != set(GATE_TASKS):
        raise EvidenceError("gate report must contain both selected tasks")
    return {
        task: _validate_task(task, tasks[task], validated_policy) for task in GATE_TASKS
    }


def load_gate_evidence(
    policy: dict,
    evidence_dir: str | Path = DEFAULT_GATE_EVIDENCE_DIR,
) -> ExplanationGateEvidence:
    root = Path(evidence_dir)
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError(f"evidence directory is unavailable: {root}")
    report_path = root / GATE_REPORT_FILENAME
    checksum_path = root / GATE_CHECKSUM_FILENAME
    for path in (report_path, checksum_path):
        require_regular_file(path)
    checksums = load_pinned_checksums(
        checksum_path, EXPECTED_GATE_HASHES, release="accepted v2.1 gate"
    )
    verify_pinned_files(root, checksums)
    report = load_json_object(report_path)
    tasks = validate_gate_report(report, policy)
    return ExplanationGateEvidence(
        report=report,
        tasks=tasks,
        policy=policy,
        sha256=dict(checksums),
        evidence_dir=root.resolve(),
    )
