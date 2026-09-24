"""Validate recorded confusion matrices and check report self-consistency.

The consistency checks do not re-evaluate any model. They confirm that the
per-class and aggregate metrics stored in the frozen report are exactly what
its own recorded confusion matrix implies, which would expose a corrupted or
hand-edited report even if its digest were re-pinned.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from cids.datasets.unsw_nb15 import ATTACK_FAMILIES
from cids.workbench.evidence import FrozenEvidence
from cids.workbench.integrity import EvidenceError
from cids.workbench.reporting import TASKS, class_display_name, class_labels

CONSISTENCY_ABS_TOLERANCE = 1e-9


@dataclass(frozen=True)
class ConfusionMatrix:
    """Rows are actual classes and columns are predicted classes."""

    task: str
    labels: tuple
    counts: tuple[tuple[int, ...], ...]

    @property
    def display_labels(self) -> tuple[str, ...]:
        return tuple(class_display_name(self.task, label) for label in self.labels)

    @property
    def total(self) -> int:
        return sum(map(sum, self.counts))

    @property
    def row_totals(self) -> tuple[int, ...]:
        return tuple(sum(row) for row in self.counts)

    @property
    def column_totals(self) -> tuple[int, ...]:
        return tuple(sum(column) for column in zip(*self.counts))

    @property
    def correct(self) -> int:
        return sum(self.counts[i][i] for i in range(len(self.labels)))

    def long_frame(self) -> pd.DataFrame:
        """One row per cell with its share of the actual class (row share)."""
        names = self.display_labels
        rows = []
        for i, actual in enumerate(names):
            row_total = self.row_totals[i]
            for j, predicted in enumerate(names):
                count = self.counts[i][j]
                rows.append(
                    {
                        "actual": actual,
                        "predicted": predicted,
                        "count": count,
                        "share_of_actual": count / row_total if row_total else 0.0,
                        "correct": i == j,
                    }
                )
        return pd.DataFrame(rows)

    def wide_frame(self) -> pd.DataFrame:
        names = list(self.display_labels)
        frame = pd.DataFrame(list(self.counts), index=names, columns=names)
        frame.index.name = "Actual \\ Predicted"
        return frame

    def top_confusions(self, limit: int = 5) -> pd.DataFrame:
        """Largest off-diagonal cells, i.e. where misclassified records went."""
        cells = self.long_frame()
        errors = cells[~cells["correct"] & (cells["count"] > 0)]
        return (
            errors.sort_values(["count", "actual"], ascending=[False, True])
            .head(limit)
            .drop(columns="correct")
            .reset_index(drop=True)
        )


def confusion_matrix(official: FrozenEvidence, task: str) -> ConfusionMatrix:
    labels = class_labels(official, task)
    metrics = official.report["tasks"][task]["official_test_metrics"]
    return build_confusion_matrix(
        task,
        labels,
        metrics.get("confusion_matrix"),
        expected_total=metrics.get("samples"),
    )


def build_confusion_matrix(
    task: str,
    labels: tuple,
    matrix: object,
    *,
    expected_total: object = None,
) -> ConfusionMatrix:
    if not isinstance(matrix, list) or not matrix:
        raise EvidenceError(f"{task} confusion matrix is missing or empty")
    size = len(labels)
    if len(matrix) != size or any(
        not isinstance(row, list) or len(row) != size for row in matrix
    ):
        raise EvidenceError(
            f"{task} confusion matrix must be {size}×{size} to match its labels"
        )
    for row in matrix:
        for cell in row:
            if not isinstance(cell, int) or isinstance(cell, bool) or cell < 0:
                raise EvidenceError(
                    f"{task} confusion matrix cells must be non-negative integers"
                )
    counts = tuple(tuple(row) for row in matrix)
    result = ConfusionMatrix(task=task, labels=tuple(labels), counts=counts)
    if result.total == 0:
        raise EvidenceError(f"{task} confusion matrix contains no records")
    if expected_total is not None and result.total != expected_total:
        raise EvidenceError(
            f"{task} confusion matrix total {result.total} differs from the "
            f"recorded sample count {expected_total}"
        )
    return result


@dataclass(frozen=True)
class BinaryOutcomes:
    """Recorded binary confusion-matrix cells under their standard names."""

    true_negatives: int
    false_positives: int
    false_negatives: int
    true_positives: int

    @property
    def normal_records(self) -> int:
        return self.true_negatives + self.false_positives

    @property
    def attack_records(self) -> int:
        return self.false_negatives + self.true_positives

    @property
    def attack_predictions(self) -> int:
        return self.false_positives + self.true_positives


def binary_outcomes(official: FrozenEvidence) -> BinaryOutcomes:
    matrix = confusion_matrix(official, "binary")
    if matrix.labels != (0, 1):
        raise EvidenceError("binary matrix must be ordered normal (0), attack (1)")
    (tn, fp), (fn, tp) = matrix.counts
    return BinaryOutcomes(tn, fp, fn, tp)


@dataclass(frozen=True)
class ConsistencyCheck:
    scope: str
    name: str
    passed: bool
    detail: str


class _Checker:
    def __init__(self) -> None:
        self.results: list[ConsistencyCheck] = []

    def equal(self, scope: str, name: str, recorded: object, derived: object) -> None:
        passed = recorded == derived
        self.results.append(
            ConsistencyCheck(
                scope, name, passed, f"recorded {recorded!r}; derived {derived!r}"
            )
        )

    def close(self, scope: str, name: str, recorded: object, derived: float) -> None:
        self.all_close(scope, name, [(recorded, derived)])

    def all_close(
        self,
        scope: str,
        name: str,
        pairs: list[tuple[object, float]],
    ) -> None:
        failures = [
            (recorded, derived)
            for recorded, derived in pairs
            if not (
                isinstance(recorded, (int, float))
                and not isinstance(recorded, bool)
                and math.isclose(
                    recorded, derived, rel_tol=0.0, abs_tol=CONSISTENCY_ABS_TOLERANCE
                )
            )
        ]
        if failures:
            detail = (
                f"{len(failures)} of {len(pairs)} values differ; first {failures[0]!r}"
            )
        else:
            worst = max(abs(recorded - derived) for recorded, derived in pairs)
            noun = "value" if len(pairs) == 1 else "values"
            detail = f"{len(pairs)} {noun}; max absolute difference {worst:.2e}"
        self.results.append(ConsistencyCheck(scope, name, not failures, detail))


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    total = precision + recall
    return 2 * precision * recall / total if total else 0.0


def _mapping(value: object, keys, location: str) -> dict:
    """Return ``value`` if it is an object holding every key, else fail closed."""
    if not isinstance(value, dict):
        raise EvidenceError(f"{location} is missing or not an object")
    missing = [key for key in keys if key not in value]
    if missing:
        raise EvidenceError(f"{location} lacks {missing}")
    return value


def _task_structure(official: FrozenEvidence, task: str, labels: tuple) -> tuple:
    """Check every container the task checks read, before any arithmetic."""
    result = _mapping(official.report["tasks"].get(task), (), f"{task} result")
    metrics = _mapping(
        result.get("official_test_metrics"), (), f"{task} official_test_metrics"
    )
    split = _mapping(result.get("split_report"), (), f"{task} split_report")
    names = [str(label) for label in labels]
    per_class = _mapping(metrics.get("per_class"), names, f"{task} per_class")
    for name in names:
        _mapping(
            per_class[name],
            ("support", "precision", "recall", "f1"),
            f"{task} per_class/{name}",
        )
    counts = _mapping(split.get("class_counts"), ("official_test",), f"{task} counts")
    _mapping(counts["official_test"], names, f"{task} official_test counts")
    if task == "multiclass":
        for key in ("false_positive_rate_by_class", "false_negative_rate_by_class"):
            _mapping(metrics.get(key), names, f"{task} {key}")
        families = [name for name in names if name != "normal"]
        _mapping(
            metrics.get("per_family_detection_rate"),
            families,
            f"{task} per_family_detection_rate",
        )
    return metrics, split


def _task_checks(checker: _Checker, official: FrozenEvidence, task: str) -> None:
    matrix = confusion_matrix(official, task)
    labels = matrix.labels
    metrics, split = _task_structure(official, task, labels)
    per_class = {label: metrics["per_class"][str(label)] for label in labels}
    rows, columns = matrix.row_totals, matrix.column_totals
    total = matrix.total
    diagonal = [matrix.counts[i][i] for i in range(len(labels))]
    recall = [_ratio(diagonal[i], rows[i]) for i in range(len(labels))]
    precision = [_ratio(diagonal[i], columns[i]) for i in range(len(labels))]
    f1 = [_f1(p, r) for p, r in zip(precision, recall)]

    def weighted(values: list[float]) -> float:
        return sum(value * row for value, row in zip(values, rows)) / total

    def mean(values: list[float]) -> float:
        return sum(values) / len(values)

    checker.equal(
        task, "Matrix total equals recorded samples", metrics.get("samples"), total
    )
    checker.equal(
        task,
        "Matrix row totals equal per-class support",
        [per_class[label]["support"] for label in labels],
        list(rows),
    )
    checker.equal(
        task,
        "Matrix row totals equal split-report official-test counts",
        [split["class_counts"]["official_test"][str(label)] for label in labels],
        list(rows),
    )
    checker.close(
        task,
        "Accuracy equals matrix trace / total",
        metrics.get("accuracy"),
        matrix.correct / total,
    )
    for name, derived in (("recall", recall), ("precision", precision), ("f1", f1)):
        rule = {
            "recall": "diagonal / row total",
            "precision": "diagonal / column total",
            "f1": "harmonic mean of matrix precision and recall",
        }[name]
        checker.all_close(
            task,
            f"Per-class {name} equals {rule}",
            [(per_class[label][name], derived[i]) for i, label in enumerate(labels)],
        )
    checker.close(
        task,
        "Balanced accuracy equals mean matrix recall",
        metrics.get("balanced_accuracy"),
        mean(recall),
    )
    checker.all_close(
        task,
        "Macro precision, recall and F1 equal means of matrix values",
        [
            (metrics.get("precision_macro"), mean(precision)),
            (metrics.get("recall_macro"), mean(recall)),
            (metrics.get("f1_macro"), mean(f1)),
        ],
    )
    checker.all_close(
        task,
        "Weighted precision, recall and F1 equal support-weighted matrix values",
        [
            (metrics.get("precision_weighted"), weighted(precision)),
            (metrics.get("recall_weighted"), weighted(recall)),
            (metrics.get("f1_weighted"), weighted(f1)),
        ],
    )

    if task == "binary":
        (tn, fp), (fn, tp) = matrix.counts
        attack = labels.index(1)
        checker.all_close(
            task,
            "Attack precision, recall and F1 equal the attack-class matrix values",
            [
                (metrics.get("precision"), precision[attack]),
                (metrics.get("recall"), recall[attack]),
                (metrics.get("f1"), f1[attack]),
            ],
        )
        checker.close(
            task,
            "False-positive rate equals FP / (FP + TN)",
            metrics.get("false_positive_rate"),
            _ratio(fp, fp + tn),
        )
        checker.close(
            task,
            "False-negative rate equals FN / (FN + TP)",
            metrics.get("false_negative_rate"),
            _ratio(fn, fn + tp),
        )
        return

    fpr = [
        _ratio(columns[i] - diagonal[i], total - rows[i]) for i in range(len(labels))
    ]
    fnr = [1.0 - value for value in recall]
    checker.all_close(
        task,
        "One-vs-rest false-positive rates match the matrix",
        [
            (metrics["false_positive_rate_by_class"][label], fpr[i])
            for i, label in enumerate(labels)
        ],
    )
    checker.all_close(
        task,
        "One-vs-rest false-negative rates match the matrix",
        [
            (metrics["false_negative_rate_by_class"][label], fnr[i])
            for i, label in enumerate(labels)
        ],
    )
    checker.all_close(
        task,
        "Macro false-positive and false-negative rates equal one-vs-rest means",
        [
            (metrics.get("false_positive_rate_macro"), mean(fpr)),
            (metrics.get("false_negative_rate_macro"), mean(fnr)),
        ],
    )
    checker.all_close(
        task,
        "Per-family detection rate equals family recall",
        [
            (metrics["per_family_detection_rate"][label], recall[i])
            for i, label in enumerate(labels)
            if label != "normal"
        ],
    )


def _structure_failure(scope: str, exc: EvidenceError) -> ConsistencyCheck:
    return ConsistencyCheck(scope, "Report structure is complete", False, str(exc))


def _cross_task_checks(checker: _Checker, official: FrozenEvidence) -> None:
    tasks = official.report["tasks"]
    ids = {}
    supports = {}
    for task, names in (("binary", ("0", "1")), ("multiclass", ATTACK_FAMILIES)):
        result = _mapping(tasks.get(task), (), f"{task} result")
        split = _mapping(result.get("split_report"), (), f"{task} split_report")
        id_digests = _mapping(split.get("id_sha256"), ("official_test",), f"{task} ids")
        ids[task] = id_digests["official_test"]
        metrics = _mapping(result.get("official_test_metrics"), (), f"{task} metrics")
        per_class = _mapping(metrics.get("per_class"), names, f"{task} per_class")
        supports[task] = {
            name: _mapping(per_class[name], ("support",), f"{task} {name}")["support"]
            for name in names
        }
    checker.equal(
        "cross-task",
        "Both tasks scored the same official-test records",
        ids["binary"],
        ids["multiclass"],
    )
    family = supports["multiclass"]
    checker.equal(
        "cross-task",
        "Binary attack support equals the sum of attack-family supports",
        supports["binary"]["1"],
        sum(value for name, value in family.items() if name != "normal"),
    )
    checker.equal(
        "cross-task",
        "Binary normal support equals multiclass normal support",
        supports["binary"]["0"],
        family["normal"],
    )


def consistency_checks(official: FrozenEvidence) -> list[ConsistencyCheck]:
    """Run every self-consistency check.

    Missing or malformed report structure is reported as a failed check.
    Anything else that raises is a code defect and propagates.
    """
    checker = _Checker()
    for task in TASKS:
        try:
            _task_checks(checker, official, task)
        except EvidenceError as exc:
            checker.results.append(_structure_failure(task, exc))
    try:
        _cross_task_checks(checker, official)
    except EvidenceError as exc:
        checker.results.append(_structure_failure("cross-task", exc))
    return checker.results
