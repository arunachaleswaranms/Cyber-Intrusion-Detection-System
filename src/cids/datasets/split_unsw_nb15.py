"""Create leakage-resistant, deterministic UNSW-NB15 development splits."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from cids.datasets.unsw_nb15 import (
    ATTACK_FAMILY_COLUMN,
    BINARY_LABEL_COLUMN,
    FEATURE_COLUMNS,
    ID_COLUMN,
    SCHEMA_VERSION,
    validate_model_feature_frame,
    validate_prepared_frame,
)

SPLIT_POLICY_VERSION = "unsw-nb15-split-v1"
DEFAULT_RANDOM_SEED = 42
DEFAULT_VALIDATION_FRACTION = 0.20
Task = Literal["binary", "multiclass"]


class SplitPreparationError(ValueError):
    """Raised when safe deterministic splits cannot be constructed."""


@dataclass(frozen=True)
class PreparedSplits:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    report: dict


@dataclass(frozen=True)
class PreparedDevelopmentSplits:
    """Clean train/validation data with a feature-only official-test reference."""

    train: pd.DataFrame
    validation: pd.DataFrame
    report: dict


def target_for_task(task: Task) -> str:
    if task == "binary":
        return BINARY_LABEL_COLUMN
    if task == "multiclass":
        return ATTACK_FAMILY_COLUMN
    raise SplitPreparationError(f"unsupported task: {task!r}")


def _exact_overlap_indices(
    candidate_frame: pd.DataFrame, reference_frame: pd.DataFrame
) -> pd.Index:
    features = list(FEATURE_COLUMNS)
    candidate_hashes = pd.util.hash_pandas_object(
        candidate_frame[features], index=False
    )
    reference_hashes = pd.util.hash_pandas_object(
        reference_frame[features], index=False
    )
    possible = candidate_hashes.isin(set(reference_hashes))
    if not possible.any():
        return pd.Index([], dtype="int64")

    candidates = candidate_frame.loc[possible, features].copy()
    candidates["_candidate_index"] = candidates.index
    confirmed = candidates.merge(
        reference_frame[features].drop_duplicates(),
        on=features,
        how="inner",
        validate="many_to_one",
    )
    return pd.Index(confirmed["_candidate_index"].drop_duplicates())


def _conflicting_group_indices(frame: pd.DataFrame, target: str) -> tuple[pd.Index, int]:
    features = list(FEATURE_COLUMNS)
    duplicate_rows = frame.loc[frame.duplicated(features, keep=False)]
    if duplicate_rows.empty:
        return pd.Index([], dtype="int64"), 0

    target_counts = duplicate_rows.groupby(features, dropna=False)[target].nunique()
    conflicting_features = target_counts.loc[target_counts > 1]
    if conflicting_features.empty:
        return pd.Index([], dtype="int64"), 0

    conflict_keys = conflicting_features.reset_index()[features]
    candidates = frame.reset_index().rename(columns={"index": "_candidate_index"})
    matched = candidates.merge(
        conflict_keys, on=features, how="inner", validate="many_to_one"
    )
    indices = pd.Index(matched["_candidate_index"].drop_duplicates())
    return indices, len(conflict_keys)


def _test_diagnostics(frame: pd.DataFrame, target: str) -> dict:
    features = list(FEATURE_COLUMNS)
    duplicate_rows = frame.loc[frame.duplicated(features, keep=False)]
    conflicting_groups = 0
    if not duplicate_rows.empty:
        conflicting_groups = int(
            (
                duplicate_rows.groupby(features, dropna=False)[target].nunique()
                > 1
            ).sum()
        )
    return {
        "rows": len(frame),
        "redundant_feature_rows": int(frame.duplicated(features).sum()),
        "conflicting_target_groups": conflicting_groups,
    }


def _rank(seed: int, target: object, row_id: object) -> str:
    value = f"{SPLIT_POLICY_VERSION}|{seed}|{target}|{row_id}".encode()
    return hashlib.sha256(value).hexdigest()


def _deterministic_stratified_split(
    frame: pd.DataFrame, target: str, validation_fraction: float, seed: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not 0 < validation_fraction < 1:
        raise SplitPreparationError("validation_fraction must be between 0 and 1")

    validation_indices: list[int] = []
    for target_value, group in frame.groupby(target, sort=True):
        if len(group) < 2:
            raise SplitPreparationError(
                f"target {target_value!r} has fewer than two cleaned records"
            )
        ranked = sorted(
            group.index,
            key=lambda index: _rank(seed, target_value, frame.at[index, ID_COLUMN]),
        )
        validation_size = round(len(group) * validation_fraction)
        validation_size = min(max(validation_size, 1), len(group) - 1)
        validation_indices.extend(ranked[:validation_size])

    validation_index = pd.Index(validation_indices)
    validation = frame.loc[validation_index].sort_values(ID_COLUMN).reset_index(drop=True)
    train = frame.drop(index=validation_index).sort_values(ID_COLUMN).reset_index(drop=True)
    return train, validation


def _id_digest(frame: pd.DataFrame) -> str:
    values = "\n".join(str(value) for value in frame[ID_COLUMN]).encode()
    return hashlib.sha256(values).hexdigest()


def _class_counts(frame: pd.DataFrame, target: str) -> dict[str, int]:
    counts = frame[target].value_counts().sort_index()
    return {str(label): int(count) for label, count in counts.items()}


def prepare_splits(
    official_train: pd.DataFrame,
    official_test: pd.DataFrame,
    task: Task,
    validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
    seed: int = DEFAULT_RANDOM_SEED,
) -> PreparedSplits:
    """Prepare clean development splits while preserving the official test set."""
    target = target_for_task(task)
    train_source = validate_prepared_frame(official_train).reset_index(drop=True)
    test = validate_prepared_frame(official_test).reset_index(drop=True)
    source_train_rows = len(train_source)

    overlap_indices = _exact_overlap_indices(train_source, test)
    cleaned = train_source.drop(index=overlap_indices)

    conflict_indices, conflicting_groups = _conflicting_group_indices(cleaned, target)
    cleaned = cleaned.drop(index=conflict_indices)

    features = list(FEATURE_COLUMNS)
    redundant_mask = cleaned.duplicated(features, keep="first")
    redundant_rows = int(redundant_mask.sum())
    cleaned = cleaned.loc[~redundant_mask].copy()

    train, validation = _deterministic_stratified_split(
        cleaned, target, validation_fraction, seed
    )
    report = {
        "split_policy_version": SPLIT_POLICY_VERSION,
        "schema_version": SCHEMA_VERSION,
        "task": task,
        "target": target,
        "seed": seed,
        "validation_fraction": validation_fraction,
        "source_rows": {"official_train": source_train_rows, "official_test": len(test)},
        "removed_from_training": {
            "official_test_overlap": len(overlap_indices),
            "conflicting_target_groups": conflicting_groups,
            "conflicting_target_rows": len(conflict_indices),
            "redundant_feature_rows": redundant_rows,
        },
        "prepared_rows": {
            "train": len(train),
            "validation": len(validation),
            "official_test": len(test),
        },
        "class_counts": {
            "train": _class_counts(train, target),
            "validation": _class_counts(validation, target),
            "official_test": _class_counts(test, target),
        },
        "id_sha256": {
            "train": _id_digest(train),
            "validation": _id_digest(validation),
            "official_test": _id_digest(test),
        },
        "official_test_diagnostics": _test_diagnostics(test, target),
    }
    return PreparedSplits(train=train, validation=validation, test=test, report=report)


def prepare_development_splits(
    official_train: pd.DataFrame,
    official_test_features: pd.DataFrame,
    task: Task,
    validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
    seed: int = DEFAULT_RANDOM_SEED,
) -> PreparedDevelopmentSplits:
    """Prepare development data without reading official-test IDs or targets."""
    target = target_for_task(task)
    train_source = validate_prepared_frame(official_train).reset_index(drop=True)
    test_reference = validate_model_feature_frame(official_test_features).reset_index(
        drop=True
    )
    source_train_rows = len(train_source)

    overlap_indices = _exact_overlap_indices(train_source, test_reference)
    cleaned = train_source.drop(index=overlap_indices)
    conflict_indices, conflicting_groups = _conflicting_group_indices(cleaned, target)
    cleaned = cleaned.drop(index=conflict_indices)

    features = list(FEATURE_COLUMNS)
    redundant_mask = cleaned.duplicated(features, keep="first")
    redundant_rows = int(redundant_mask.sum())
    cleaned = cleaned.loc[~redundant_mask].copy()
    train, validation = _deterministic_stratified_split(
        cleaned, target, validation_fraction, seed
    )
    report = {
        "split_policy_version": SPLIT_POLICY_VERSION,
        "schema_version": SCHEMA_VERSION,
        "task": task,
        "target": target,
        "seed": seed,
        "validation_fraction": validation_fraction,
        "source_rows": {
            "official_train": source_train_rows,
            "official_test_feature_reference": len(test_reference),
        },
        "removed_from_training": {
            "official_test_feature_overlap": len(overlap_indices),
            "conflicting_target_groups": conflicting_groups,
            "conflicting_target_rows": len(conflict_indices),
            "redundant_feature_rows": redundant_rows,
        },
        "prepared_rows": {"train": len(train), "validation": len(validation)},
        "class_counts": {
            "train": _class_counts(train, target),
            "validation": _class_counts(validation, target),
        },
        "id_sha256": {
            "train": _id_digest(train),
            "validation": _id_digest(validation),
        },
        "official_test_access": "features_only_for_overlap_removal",
    }
    return PreparedDevelopmentSplits(
        train=train,
        validation=validation,
        report=report,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--task", required=True, choices=("binary", "multiclass"))
    parser.add_argument("--validation-fraction", type=float, default=0.20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--report", type=Path, help="Optional JSON report output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    official_train = pd.read_csv(
        args.data_dir / "UNSW_NB15_training-set.csv", encoding="utf-8-sig"
    )
    official_test = pd.read_csv(
        args.data_dir / "UNSW_NB15_testing-set.csv", encoding="utf-8-sig"
    )
    prepared = prepare_splits(
        official_train,
        official_test,
        task=args.task,
        validation_fraction=args.validation_fraction,
        seed=args.seed,
    )
    rendered = json.dumps(prepared.report, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(f"{rendered}\n", encoding="utf-8")
        print(f"Wrote split report: {args.report}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
