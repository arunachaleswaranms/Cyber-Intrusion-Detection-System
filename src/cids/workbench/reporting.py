"""Turn verified evidence into traceable, stage-labelled view models.

Every value produced here carries the evaluation stage it belongs to and an
RFC 6901 JSON pointer into the committed file it was read from. The value and
its pointer are derived from the same path, so a displayed number cannot drift
from its cited source. Nothing here recomputes an official result; the only
arithmetic is a documented difference between two recorded values, a count
reconstructed from a recorded rate and support, and presentation flags.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from cids.datasets.unsw_nb15 import ATTACK_FAMILIES
from cids.workbench.catalog import MODEL_SELECTION_PATH, OFFICIAL_DIR
from cids.workbench.evidence import RESULT_FILENAME, FrozenEvidence
from cids.workbench.formatting import format_ratio
from cids.workbench.integrity import EvidenceError

OFFICIAL_RESULT_PATH = (OFFICIAL_DIR / RESULT_FILENAME).as_posix()
SELECTION_PATH = MODEL_SELECTION_PATH.as_posix()
TASKS = ("binary", "multiclass")

# Presentation policies, shown verbatim in the UI. They flag results for
# attention; they are not detection thresholds and change no model output.
WEAK_METRIC_BOUND = 0.5
SMALL_SUPPORT_BOUND = 100


@dataclass(frozen=True)
class EvaluationStage:
    key: str
    label: str
    badge: str
    description: str


VALIDATION = EvaluationStage(
    key="validation",
    label="Validation (model selection)",
    badge="VALIDATION",
    description=(
        "Frozen model-selection record. Candidate models were fit on the cleaned "
        "training split and scored on the held-out validation split. These "
        "numbers chose the models before the official test was unsealed."
    ),
)
OFFICIAL_TEST = EvaluationStage(
    key="official_test",
    label="Official held-out test",
    badge="OFFICIAL TEST",
    description=(
        "Single guarded run. The selected models were refit on train plus "
        "validation and scored once on the immutable official UNSW-NB15 test "
        "partition. These are the published v2.0 results."
    ),
)
EXPLANATION_GATE = EvaluationStage(
    key="explanation_gate",
    label="Explanation gate (development data)",
    badge="EXPLANATION GATE",
    description=(
        "Correctness and resource checks of the bounded SHAP method using a "
        "prepared-training background and prepared-validation rows. The report "
        "contains no feature attributions and no official-test data."
    ),
)


@dataclass(frozen=True)
class EvidenceRef:
    path: str
    pointer: str

    def __str__(self) -> str:
        return f"{self.path} → {self.pointer}"


def json_pointer(parts: Sequence[object]) -> str:
    """Build an RFC 6901 pointer from path segments."""
    escaped = (str(part).replace("~", "~0").replace("/", "~1") for part in parts)
    return "/" + "/".join(escaped) if parts else ""


def resolve_pointer(document: object, pointer: str) -> object:
    """Follow an RFC 6901 pointer through nested JSON objects and arrays."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise EvidenceError(f"invalid JSON pointer: {pointer!r}")
    value = document
    for raw in pointer[1:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise KeyError(pointer)
    return value


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    label: str
    description: str
    better: str | None  # "higher", "lower", or None when direction is not implied


def _definition(key: str, label: str, description: str, better: str | None):
    return key, MetricDefinition(key, label, description, better)


METRIC_DEFINITIONS: dict[str, MetricDefinition] = dict(
    [
        _definition(
            "f1_macro",
            "Macro F1",
            "Unweighted mean of per-class F1, so rare classes count equally.",
            "higher",
        ),
        _definition(
            "balanced_accuracy",
            "Balanced accuracy",
            "Unweighted mean of per-class recall.",
            "higher",
        ),
        _definition(
            "accuracy",
            "Accuracy",
            "Share of all records classified correctly; dominated by large classes.",
            "higher",
        ),
        _definition(
            "f1_weighted",
            "Weighted F1",
            "Per-class F1 weighted by support; dominated by large classes.",
            "higher",
        ),
        _definition(
            "false_positive_rate",
            "False-positive rate",
            "Share of normal records classified as attack: FP / (FP + TN).",
            "lower",
        ),
        _definition(
            "false_negative_rate",
            "False-negative rate",
            "Share of attack records classified as normal: FN / (FN + TP).",
            "lower",
        ),
        _definition(
            "false_positive_rate_macro",
            "Macro false-positive rate",
            "Mean one-vs-rest false-positive rate across the ten classes.",
            "lower",
        ),
        _definition(
            "false_negative_rate_macro",
            "Macro false-negative rate",
            "Mean one-vs-rest false-negative rate across the ten classes.",
            "lower",
        ),
        _definition(
            "precision",
            "Attack precision",
            "Share of attack predictions that were attacks: TP / (TP + FP).",
            "higher",
        ),
        _definition(
            "recall",
            "Attack recall",
            "Share of attack records predicted as attack: TP / (TP + FN).",
            "higher",
        ),
        _definition(
            "roc_auc",
            "ROC-AUC",
            "Ranking quality of the uncalibrated attack score across thresholds.",
            "higher",
        ),
        _definition(
            "pr_auc",
            "PR-AUC",
            "Area under the precision-recall curve of the uncalibrated attack score.",
            "higher",
        ),
        _definition(
            "roc_auc_ovr_macro",
            "Macro ROC-AUC (one-vs-rest)",
            "Mean one-vs-rest ROC-AUC of the uncalibrated class scores.",
            "higher",
        ),
        _definition(
            "pr_auc_macro",
            "Macro PR-AUC (one-vs-rest)",
            "Mean one-vs-rest average precision of the uncalibrated class scores.",
            "higher",
        ),
    ]
)

HEADLINE_METRICS = {
    "binary": (
        "f1_macro",
        "balanced_accuracy",
        "false_positive_rate",
        "false_negative_rate",
    ),
    "multiclass": (
        "f1_macro",
        "balanced_accuracy",
        "false_positive_rate_macro",
        "false_negative_rate_macro",
    ),
}
SECONDARY_METRICS = {
    "binary": ("precision", "recall", "roc_auc", "pr_auc", "accuracy", "f1_weighted"),
    "multiclass": ("accuracy", "f1_weighted", "roc_auc_ovr_macro", "pr_auc_macro"),
}

MODEL_DISPLAY_NAMES = {
    "hist_gradient_boosting": "Histogram Gradient Boosting",
    "random_forest": "Random Forest",
    "isolation_forest": "Isolation Forest",
}
TASK_TITLES = {
    "binary": "Binary attack detection",
    "multiclass": "Attack-family classification",
}
BINARY_CLASS_NAMES = {0: "Normal", 1: "Attack"}
FAMILY_DISPLAY_NAMES = {
    "normal": "Normal",
    "analysis": "Analysis",
    "backdoor": "Backdoor",
    "dos": "DoS",
    "exploits": "Exploits",
    "fuzzers": "Fuzzers",
    "generic": "Generic",
    "reconnaissance": "Reconnaissance",
    "shellcode": "Shellcode",
    "worms": "Worms",
}


@dataclass(frozen=True)
class MetricValue:
    definition: MetricDefinition
    value: float | None
    stage: EvaluationStage
    source: EvidenceRef

    @property
    def display(self) -> str:
        return format_ratio(self.value)


def _require_task(task: str) -> None:
    if task not in TASKS:
        raise EvidenceError(f"unknown task: {task!r}")


def _read_metric(
    document: dict,
    parts: tuple[object, ...],
    *,
    key: str,
    stage: EvaluationStage,
    path: str,
) -> MetricValue:
    definition = METRIC_DEFINITIONS.get(key)
    if definition is None:
        raise EvidenceError(f"metric {key!r} has no display definition")
    pointer = json_pointer(parts)
    try:
        raw = resolve_pointer(document, pointer)
    except KeyError:
        raw = None  # Partial evidence: show "not recorded", never a default.
    if raw is not None and (
        not isinstance(raw, (int, float))
        or isinstance(raw, bool)
        or not math.isfinite(raw)
    ):
        raise EvidenceError(f"{path} {pointer} is not a finite number")
    return MetricValue(
        definition=definition,
        value=None if raw is None else float(raw),
        stage=stage,
        source=EvidenceRef(path, pointer),
    )


def official_metric(official: FrozenEvidence, task: str, key: str) -> MetricValue:
    _require_task(task)
    return _read_metric(
        official.report,
        ("tasks", task, "official_test_metrics", key),
        key=key,
        stage=OFFICIAL_TEST,
        path=OFFICIAL_RESULT_PATH,
    )


def validation_metric(selection: dict, task: str, key: str) -> MetricValue:
    _require_task(task)
    return _read_metric(
        selection,
        ("selected", task, "selected_validation_metrics", key),
        key=key,
        stage=VALIDATION,
        path=SELECTION_PATH,
    )


def official_metrics(
    official: FrozenEvidence, task: str, keys: Sequence[str]
) -> list[MetricValue]:
    return [official_metric(official, task, key) for key in keys]


@dataclass(frozen=True)
class StageComparison:
    validation: MetricValue
    official: MetricValue

    @property
    def definition(self) -> MetricDefinition:
        return self.official.definition

    @property
    def delta(self) -> float | None:
        if self.validation.value is None or self.official.value is None:
            return None
        return self.official.value - self.validation.value

    @property
    def direction(self) -> str:
        """Describe the change without implying the stages are equivalent."""
        delta = self.delta
        better = self.definition.better
        if delta is None:
            return "not comparable"
        if abs(delta) < 5e-5 or better is None:
            return "about the same"
        improved = delta > 0 if better == "higher" else delta < 0
        return "better on test" if improved else "worse on test"


def stage_comparisons(
    selection: dict, official: FrozenEvidence, task: str
) -> list[StageComparison]:
    """Pair each selection-ranking metric with its official-test counterpart.

    The metric list comes from the frozen ranking rule itself, so the
    comparison covers exactly the metrics that chose the model.
    """
    _require_task(task)
    try:
        ranking = selection["selected"][task]["ranking"]
    except (KeyError, TypeError) as exc:
        raise EvidenceError(f"model-selection record lacks a {task} ranking") from exc
    return [
        StageComparison(
            validation=validation_metric(selection, task, rule["metric"]),
            official=official_metric(official, task, rule["metric"]),
        )
        for rule in ranking
    ]


def class_display_name(task: str, label: object) -> str:
    _require_task(task)
    names = BINARY_CLASS_NAMES if task == "binary" else FAMILY_DISPLAY_NAMES
    try:
        return names[label]
    except (KeyError, TypeError) as exc:
        raise EvidenceError(f"unexpected {task} class label: {label!r}") from exc


def class_labels(official: FrozenEvidence, task: str) -> tuple:
    """Return the recorded class order after checking it against the taxonomy."""
    _require_task(task)
    labels = official.report["tasks"][task]["official_test_metrics"].get("labels")
    if not isinstance(labels, list) or len(set(map(repr, labels))) != len(labels):
        raise EvidenceError(f"{task} class labels are missing or duplicated")
    expected = set(BINARY_CLASS_NAMES) if task == "binary" else set(ATTACK_FAMILIES)
    unexpected = [label for label in labels if label not in expected]
    if unexpected:
        raise EvidenceError(
            f"unexpected {task} class labels outside the frozen taxonomy:"
            f" {unexpected!r}"
        )
    if set(labels) != expected:
        missing = sorted(map(str, expected - set(labels)))
        raise EvidenceError(f"{task} class labels are incomplete; missing {missing}")
    return tuple(labels)


def weakness_label(precision: float | None, recall: float | None) -> str:
    """Name the kind of weakness using the displayed presentation bound."""
    if precision is None or recall is None:
        return "not recorded"
    missed = recall < WEAK_METRIC_BOUND
    over = precision < WEAK_METRIC_BOUND
    if missed and over:
        return "missed and over-predicted"
    if missed:
        return "mostly missed"
    if over:
        return "over-predicted"
    return ""


def per_class_table(official: FrozenEvidence, task: str) -> pd.DataFrame:
    """Per-class official-test metrics in the recorded label order."""
    labels = class_labels(official, task)
    metrics = official.report["tasks"][task]["official_test_metrics"]
    per_class = metrics.get("per_class")
    if not isinstance(per_class, dict):
        raise EvidenceError(f"{task} per-class metrics are missing")
    unknown = set(per_class) - {str(label) for label in labels}
    if unknown:
        raise EvidenceError(
            f"{task} per-class metrics contain unknown classes {unknown}"
        )
    fpr = metrics.get("false_positive_rate_by_class", {})
    fnr = metrics.get("false_negative_rate_by_class", {})
    rows = []
    for label in labels:
        entry = per_class.get(str(label))
        if not isinstance(entry, dict):
            raise EvidenceError(f"{task} per-class metrics lack class {label!r}")
        row = {
            "label": label,
            "class": class_display_name(task, label),
            "support": entry.get("support"),
            "precision": entry.get("precision"),
            "recall": entry.get("recall"),
            "f1": entry.get("f1"),
        }
        if task == "multiclass":
            row["false_positive_rate"] = fpr.get(label)
            row["false_negative_rate"] = fnr.get(label)
        row["weakness"] = weakness_label(row["precision"], row["recall"])
        support = row["support"]
        row["small_support"] = (
            isinstance(support, int) and support < SMALL_SUPPORT_BOUND
        )
        rows.append(row)
    return pd.DataFrame(rows)


def family_detection_table(official: FrozenEvidence) -> pd.DataFrame:
    """Binary attack detection rate by attack family on the official test.

    Family supports come from the multiclass split report. Both tasks must
    describe the same official-test records (identical ID digests), and each
    rate multiplied by its support must reconstruct a whole record count.
    """
    tasks = official.report["tasks"]
    binary_split = tasks["binary"]["split_report"]
    family_split = tasks["multiclass"]["split_report"]
    if binary_split["id_sha256"]["official_test"] != (
        family_split["id_sha256"]["official_test"]
    ):
        raise EvidenceError("binary and multiclass official-test records differ")
    rates = tasks["binary"]["official_test_metrics"].get("per_family_detection_rate")
    if not isinstance(rates, dict) or not rates:
        raise EvidenceError("binary per-family detection rates are missing")
    supports = family_split["class_counts"]["official_test"]
    attack_families = [family for family in ATTACK_FAMILIES if family != "normal"]
    if set(rates) != set(attack_families):
        raise EvidenceError("binary detection rates do not cover the nine families")
    rows = []
    for family in attack_families:
        rate = rates[family]
        if (
            not isinstance(rate, (int, float))
            or isinstance(rate, bool)
            or not 0 <= rate <= 1
        ):
            raise EvidenceError(f"{family} detection rate is not a ratio")
        support = supports.get(family)
        if not isinstance(support, int) or support <= 0:
            raise EvidenceError(f"official-test support for {family} is missing")
        detected = rate * support
        if abs(detected - round(detected)) > 1e-6:
            raise EvidenceError(
                f"{family} detection rate does not reconstruct a whole record count"
            )
        rows.append(
            {
                "family": family,
                "class": FAMILY_DISPLAY_NAMES[family],
                "support": support,
                "detected": int(round(detected)),
                "missed": support - int(round(detected)),
                "detection_rate": rate,
            }
        )
    return pd.DataFrame(rows)


def partition_table(official: FrozenEvidence, task: str) -> pd.DataFrame:
    """Class counts per partition exactly as recorded by the split report."""
    labels = class_labels(official, task)
    split = official.report["tasks"][task]["split_report"]
    rows = []
    for partition in ("train", "validation", "official_test"):
        try:
            partition_counts = split["class_counts"][partition]
            row = {"partition": partition, "rows": split["prepared_rows"][partition]}
        except (KeyError, TypeError) as exc:
            raise EvidenceError(
                f"{task} split report lacks counts for {partition}"
            ) from exc
        for label in labels:
            row[class_display_name(task, label)] = partition_counts.get(str(label))
        rows.append(row)
    return pd.DataFrame(rows)


def model_display_name(model_name: object) -> str:
    """Readable model name; unknown identifiers are shown verbatim, not hidden."""
    return MODEL_DISPLAY_NAMES.get(model_name, str(model_name))


def weak_classes(table: pd.DataFrame) -> list[str]:
    """Display names of classes whose recorded recall is below the bound."""
    recall = pd.to_numeric(table["recall"], errors="coerce")
    return list(table.loc[recall < WEAK_METRIC_BOUND, "class"])


def unrecorded_classes(table: pd.DataFrame) -> list[str]:
    """Display names of classes whose precision or recall is not recorded."""
    values = table[["precision", "recall"]].apply(pd.to_numeric, errors="coerce")
    return list(table.loc[values.isna().any(axis=1), "class"])
