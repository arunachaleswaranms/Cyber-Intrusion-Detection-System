"""Train the v2.0 normal-only anomaly baseline without opening official test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from cids.config import (
    DEFAULT_EXPERIMENT_CONFIG,
    config_sha256,
    load_experiment_config,
)
from cids.datasets.split_unsw_nb15 import prepare_splits
from cids.datasets.verify_manifest import DEFAULT_MANIFEST, verify_dataset
from cids.modeling.anomaly import save_artifact, train_and_validate_anomaly


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--config", type=Path, default=DEFAULT_EXPERIMENT_CONFIG)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_experiment_config(args.config)
    verified = {item.role: item for item in verify_dataset(args.data_dir, args.manifest)}
    official_train = pd.read_csv(verified["train"].path, encoding="utf-8-sig")
    official_test = pd.read_csv(verified["test"].path, encoding="utf-8-sig")
    splits = prepare_splits(
        official_train,
        official_test,
        task="binary",
        validation_fraction=config["split"]["validation_fraction"],
        seed=config["split"]["seed"],
    )
    result = train_and_validate_anomaly(splits, config=config)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = save_artifact(
        result.artifact,
        args.output_dir / "isolation_forest.joblib",
    )
    report = {
        "task": "binary",
        "experiment_config_version": config["config_version"],
        "experiment_config_sha256": config_sha256(config),
        "selection_partition": "validation",
        "official_test_status": "sealed_not_evaluated",
        "split_report": splits.report,
        "model": {
            "artifact": artifact_path.name,
            "metadata": result.artifact.metadata,
            "validation_metrics": result.validation_metrics,
        },
    }
    report_path = args.output_dir / "validation_results.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metrics = result.validation_metrics
    print(f"Wrote validation results: {report_path}")
    print(
        f"isolation_forest: macro_f1={metrics['f1_macro']:.4f}, "
        f"balanced_accuracy={metrics['balanced_accuracy']:.4f}, "
        f"fpr={metrics['false_positive_rate']:.4f}, "
        f"fnr={metrics['false_negative_rate']:.4f}"
    )
    print("Official test status: sealed_not_evaluated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
