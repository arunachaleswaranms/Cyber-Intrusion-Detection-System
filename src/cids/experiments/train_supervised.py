"""Train v2.0 supervised baselines without evaluating the official test set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from cids.datasets.split_unsw_nb15 import prepare_splits
from cids.datasets.verify_manifest import DEFAULT_MANIFEST, verify_dataset
from cids.modeling.supervised import (
    SUPPORTED_MODELS,
    save_artifact,
    train_and_validate,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--task", required=True, choices=("binary", "multiclass"))
    parser.add_argument(
        "--models",
        nargs="+",
        choices=SUPPORTED_MODELS,
        default=list(SUPPORTED_MODELS),
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--validation-fraction", type=float, default=0.20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    verified = {item.role: item for item in verify_dataset(args.data_dir, args.manifest)}
    official_train = pd.read_csv(verified["train"].path, encoding="utf-8-sig")
    official_test = pd.read_csv(verified["test"].path, encoding="utf-8-sig")
    splits = prepare_splits(
        official_train,
        official_test,
        task=args.task,
        validation_fraction=args.validation_fraction,
        seed=args.seed,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    models: dict[str, dict] = {}
    for model_name in args.models:
        result = train_and_validate(splits, model_name, seed=args.seed)
        artifact_path = save_artifact(
            result.artifact,
            args.output_dir / f"{model_name}.joblib",
        )
        models[model_name] = {
            "artifact": artifact_path.name,
            "metadata": result.artifact.metadata,
            "validation_metrics": result.validation_metrics,
        }

    report = {
        "task": args.task,
        "selection_partition": "validation",
        "official_test_status": "sealed_not_evaluated",
        "split_report": splits.report,
        "models": models,
    }
    report_path = args.output_dir / "validation_results.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote validation results: {report_path}")
    for model_name, result in models.items():
        metrics = result["validation_metrics"]
        print(
            f"{model_name}: macro_f1={metrics['f1_macro']:.4f}, "
            f"weighted_f1={metrics['f1_weighted']:.4f}, "
            f"latency_ms_per_record={metrics['prediction_ms_per_record']:.6f}"
        )
    print("Official test status: sealed_not_evaluated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
