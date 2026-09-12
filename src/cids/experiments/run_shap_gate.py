"""Run the v2.1 SHAP gate on explicitly trusted local final artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap
import sklearn

from cids.config import load_experiment_config
from cids.datasets.split_unsw_nb15 import prepare_development_splits, target_for_task
from cids.datasets.unsw_nb15 import FEATURE_COLUMNS, ID_COLUMN
from cids.datasets.verify_manifest import DEFAULT_MANIFEST, verify_dataset
from cids.final_evaluation import FinalModelArtifact, load_artifact
from cids.modeling.supervised import MODEL_ARTIFACT_VERSION
from cids.workbench.config import (
    DEFAULT_WORKBENCH_CONFIG,
    load_workbench_config,
    workbench_config_sha256,
)
from cids.workbench.explanations import run_explanation_gate
from cids.workbench.model_pack import (
    EXPECTED_CONTRACTS_BASE,
    EXPECTED_RUNTIME,
    current_runtime,
)

GATE_VERSION = "cids-shap-compatibility-gate-v1"
CONFIRMATION_PHRASE = "TRUST_LOCAL_V2_ARTIFACTS"


class ShapGateCliError(ValueError):
    """Raised when the real-artifact SHAP gate cannot start safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _rank(task: str, row_id: object) -> str:
    return hashlib.sha256(f"{GATE_VERSION}|{task}|{row_id}".encode()).hexdigest()


def _stratified_sample(frame: pd.DataFrame, task: str, size: int) -> pd.DataFrame:
    target = target_for_task(task)
    if size <= 0 or frame.empty:
        raise ShapGateCliError("SHAP sample requires positive size and non-empty data")
    ranked_groups: dict[object, list[int]] = {}
    for label, group in frame.groupby(target, sort=True):
        ranked_groups[label] = sorted(
            group.index, key=lambda index: _rank(task, frame.at[index, ID_COLUMN])
        )
    chosen = [indices[0] for indices in ranked_groups.values()]
    remaining = [
        index for indices in ranked_groups.values() for index in indices[1:]
    ]
    remaining.sort(key=lambda index: _rank(task, frame.at[index, ID_COLUMN]))
    selected = (chosen + remaining)[: min(size, len(frame))]
    return frame.loc[selected].sort_values(ID_COLUMN).reset_index(drop=True)


def _trusted_artifact_path(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ShapGateCliError(f"artifact must be a regular non-symlink file: {path}")
    return path.resolve()


def _validate_frozen_artifact(artifact: FinalModelArtifact, task: str) -> None:
    metadata = artifact.metadata
    if artifact.task != task or artifact.model_name != "hist_gradient_boosting":
        raise ShapGateCliError(f"{task} artifact is not the frozen selected model")
    expected = {
        "artifact_version": artifact.version,
        "source_artifact_version": MODEL_ARTIFACT_VERSION,
        "schema_version": artifact.schema_version,
        "experiment_config_version": EXPECTED_CONTRACTS_BASE[
            "experiment_config_version"
        ],
        "experiment_config_sha256": EXPECTED_CONTRACTS_BASE[
            "experiment_config_sha256"
        ],
        "model_selection_version": EXPECTED_CONTRACTS_BASE[
            "model_selection_version"
        ],
        "model_selection_sha256": EXPECTED_CONTRACTS_BASE["model_selection_sha256"],
        "final_protocol_version": EXPECTED_CONTRACTS_BASE["final_protocol_version"],
        "final_protocol_sha256": EXPECTED_CONTRACTS_BASE["final_protocol_sha256"],
        "training_scope": "prepared_train_plus_validation",
        "official_test_status": "evaluated_once",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ShapGateCliError(f"{task} artifact metadata mismatch: {key}")
    if metadata.get("library_versions") != EXPECTED_RUNTIME["libraries"]:
        raise ShapGateCliError(f"{task} artifact library versions do not match")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--binary-artifact", required=True, type=Path)
    parser.add_argument("--multiclass-artifact", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--workbench-config", type=Path, default=DEFAULT_WORKBENCH_CONFIG
    )
    parser.add_argument("--confirm", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.confirm != CONFIRMATION_PHRASE:
        raise ShapGateCliError(
            f"refusing to deserialize; pass --confirm {CONFIRMATION_PHRASE} "
            "only for artifacts you created locally"
        )
    if args.output.exists():
        raise ShapGateCliError(f"output already exists: {args.output}")

    config = load_experiment_config()
    workbench_config = load_workbench_config(args.workbench_config)
    runtime = current_runtime()
    if runtime != EXPECTED_RUNTIME:
        raise ShapGateCliError(
            "current runtime does not match the pinned model environment"
        )
    if shap.__version__ != workbench_config["explainability"]["shap_version"]:
        raise ShapGateCliError("installed SHAP version does not match workbench policy")
    verified = {item.role: item for item in verify_dataset(args.data_dir, args.manifest)}
    official_train = pd.read_csv(verified["train"].path, encoding="utf-8-sig")
    official_test_features = pd.read_csv(
        verified["test"].path,
        encoding="utf-8-sig",
        usecols=list(FEATURE_COLUMNS),
    )
    artifact_paths = {
        "binary": _trusted_artifact_path(args.binary_artifact),
        "multiclass": _trusted_artifact_path(args.multiclass_artifact),
    }

    task_reports = {}
    for task in ("binary", "multiclass"):
        artifact = load_artifact(artifact_paths[task])
        _validate_frozen_artifact(artifact, task)
        splits = prepare_development_splits(
            official_train,
            official_test_features,
            task,
            validation_fraction=config["split"]["validation_fraction"],
            seed=config["split"]["seed"],
        )
        background = _stratified_sample(
            splits.train,
            task,
            workbench_config["explainability"]["background_rows"],
        )
        foreground = _stratified_sample(
            splits.validation,
            task,
            workbench_config["explainability"]["explain_rows"],
        )
        gate = run_explanation_gate(
            artifact,
            background,
            foreground,
            config=workbench_config,
        )
        task_reports[task] = {
            **asdict(gate),
            "artifact_sha256": _sha256(artifact_paths[task]),
            "background_partition": "prepared_train",
            "foreground_partition": "prepared_validation",
            "official_test_used_as_explanation_data": False,
        }

    report = {
        "gate_version": GATE_VERSION,
        "status": "passed",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "workbench_config_sha256": workbench_config_sha256(workbench_config),
        "environment": {
            "python": runtime["python"],
            "joblib": joblib.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
            "shap": shap.__version__,
        },
        "tasks": task_reports,
        "official_test_status": "not_evaluated_by_gate",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("SHAP compatibility gate: PASSED")
    for task, result in task_reports.items():
        print(
            f"{task}: shape={tuple(result['shap_values_shape'])}, "
            f"additivity_error={result['max_additivity_error']:.3g}, "
            f"aggregation_error={result['max_aggregation_error']:.3g}, "
            f"elapsed_seconds={result['elapsed_seconds']:.3f}"
        )
    print("Official test status: not_evaluated_by_gate")
    print(f"Wrote gate report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
