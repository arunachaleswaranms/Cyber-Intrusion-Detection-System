"""Select v2.0 models from frozen validation reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cids.config import (
    DEFAULT_EXPERIMENT_CONFIG,
    config_sha256,
    load_experiment_config,
)
from cids.selection import (
    MODEL_SELECTION_VERSION,
    ModelSelectionError,
    rank_models,
    validate_model_selection,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary-supervised-report", required=True, type=Path)
    parser.add_argument("--multiclass-supervised-report", required=True, type=Path)
    parser.add_argument("--anomaly-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_EXPERIMENT_CONFIG)
    return parser.parse_args()


def _read_report(path: Path) -> dict:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelSelectionError(f"validation report not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ModelSelectionError(f"invalid validation report: {path}") from exc
    if report.get("official_test_status") != "sealed_not_evaluated":
        raise ModelSelectionError(f"validation report does not preserve test seal: {path}")
    return report


def _verify_config(report: dict, expected_digest: str) -> None:
    if report.get("experiment_config_sha256") != expected_digest:
        raise ModelSelectionError("validation report configuration digest mismatch")


def _candidate(model: dict) -> dict:
    return {
        "artifact_version": model["metadata"]["artifact_version"],
        "metrics": model["validation_metrics"],
    }


def main() -> int:
    args = parse_args()
    config = load_experiment_config(args.config)
    digest = config_sha256(config)
    binary_report = _read_report(args.binary_supervised_report)
    multiclass_report = _read_report(args.multiclass_supervised_report)
    anomaly_report = _read_report(args.anomaly_report)
    for report in (binary_report, multiclass_report, anomaly_report):
        _verify_config(report, digest)
    if binary_report.get("task") != "binary" or anomaly_report.get("task") != "binary":
        raise ModelSelectionError("binary validation reports have incorrect tasks")
    if multiclass_report.get("task") != "multiclass":
        raise ModelSelectionError("multiclass validation report has incorrect task")

    binary_candidates = {
        name: _candidate(model)
        for name, model in binary_report["models"].items()
    }
    anomaly_name = anomaly_report["model"]["metadata"]["model_name"]
    binary_candidates[anomaly_name] = _candidate(anomaly_report["model"])
    multiclass_candidates = {
        name: _candidate(model)
        for name, model in multiclass_report["models"].items()
    }
    candidates_by_task = {
        "binary": binary_candidates,
        "multiclass": multiclass_candidates,
    }

    selected: dict[str, dict] = {}
    for task, candidates in candidates_by_task.items():
        metrics = {name: value["metrics"] for name, value in candidates.items()}
        order = rank_models(task, metrics, config)
        winner = order[0]
        ranking_rules = config["selection"]["tasks"][task]["ranking"]
        selected[task] = {
            "selected_model": winner,
            "selected_artifact_version": candidates[winner]["artifact_version"],
            "candidate_order": order,
            "ranking": ranking_rules,
            "selected_validation_metrics": {
                rule["metric"]: metrics[winner][rule["metric"]]
                for rule in ranking_rules
            },
        }

    output = {
        "selection_version": MODEL_SELECTION_VERSION,
        "experiment_config_version": config["config_version"],
        "experiment_config_sha256": digest,
        "selection_partition": "validation",
        "official_test_status": "sealed",
        "selected": selected,
    }
    validate_model_selection(output, config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote model selection: {args.output}")
    for task, result in selected.items():
        print(f"{task}: {result['selected_model']}")
    print("Official test status: sealed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
