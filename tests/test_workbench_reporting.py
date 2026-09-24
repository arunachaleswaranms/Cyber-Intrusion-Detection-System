import copy
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.workbench import evidence as evidence_module  # noqa: E402
from cids.workbench.catalog import load_catalog  # noqa: E402
from cids.workbench.confusion import (  # noqa: E402
    binary_outcomes,
    build_confusion_matrix,
    confusion_matrix,
    consistency_checks,
)
from cids.workbench.evidence import load_frozen_evidence  # noqa: E402
from cids.workbench.formatting import (  # noqa: E402
    NOT_RECORDED,
    format_count,
    format_delta,
    format_percent,
    format_ratio,
    format_timestamp,
    short_digest,
)
from cids.workbench.integrity import EvidenceError, sha256_file  # noqa: E402
from cids.workbench.reporting import (  # noqa: E402
    HEADLINE_METRICS,
    OFFICIAL_TEST,
    SECONDARY_METRICS,
    TASKS,
    VALIDATION,
    StageComparison,
    class_labels,
    family_detection_table,
    json_pointer,
    official_metric,
    per_class_table,
    resolve_pointer,
    stage_comparisons,
    unrecorded_classes,
    validation_metric,
    weak_classes,
    weakness_label,
)

REPO_ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture
def official(catalog):
    return replace(catalog.official, report=copy.deepcopy(catalog.official.report))


# Formatting ---------------------------------------------------------------


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True, "0.5"])
def test_missing_or_invalid_values_render_as_not_recorded(value):
    assert format_ratio(value) == NOT_RECORDED
    assert format_percent(value) == NOT_RECORDED
    assert format_delta(value) == NOT_RECORDED


def test_numeric_formatting_is_deterministic():
    assert format_ratio(0.86631077) == "0.8663"
    assert format_percent(0.26894594) == "26.89%"
    assert format_delta(-0.0650609) == "-0.0651"
    assert format_delta(0.1819) == "+0.1819"
    assert format_delta(-0.00001) == "0.0000"
    assert format_count(82332) == "82,332"
    assert format_count(1.5) == NOT_RECORDED
    assert short_digest("a" * 64) == "aaaaaaaaaaaa…"


def test_timestamps_require_an_explicit_offset():
    assert (
        format_timestamp("2026-09-12T08:39:38.040864+00:00")
        == "2026-09-12 08:39:38 UTC"
    )
    assert format_timestamp("2026-09-12T10:39:38+02:00") == "2026-09-12 08:39:38 UTC"
    assert format_timestamp("2026-09-12T08:39:38") == NOT_RECORDED
    assert format_timestamp("yesterday") == NOT_RECORDED


# Traceability -------------------------------------------------------------


def test_json_pointer_escapes_and_round_trips():
    document = {"a/b": {"c~d": [10, 20]}}
    pointer = json_pointer(["a/b", "c~d", 1])

    assert pointer == "/a~1b/c~0d/1"
    assert resolve_pointer(document, pointer) == 20
    with pytest.raises(KeyError):
        resolve_pointer(document, "/a~1b/missing")


@pytest.mark.parametrize("task", TASKS)
def test_every_displayed_official_metric_resolves_to_the_committed_file(catalog, task):
    committed = json.loads(
        (REPO_ROOT / "results/v2.0/official-test-results.json").read_text(
            encoding="utf-8"
        )
    )
    for key in HEADLINE_METRICS[task] + SECONDARY_METRICS[task]:
        metric = official_metric(catalog.official, task, key)

        assert metric.stage is OFFICIAL_TEST
        assert metric.source.path == "results/v2.0/official-test-results.json"
        assert resolve_pointer(committed, metric.source.pointer) == metric.value


def test_validation_metrics_are_labelled_and_sourced_from_the_selection_record(catalog):
    committed = json.loads(
        (REPO_ROOT / "configs/v2-model-selection-v1.json").read_text(encoding="utf-8")
    )
    metric = validation_metric(catalog.selection, "binary", "false_positive_rate")

    assert metric.stage is VALIDATION
    assert metric.source.path == "configs/v2-model-selection-v1.json"
    assert resolve_pointer(committed, metric.source.pointer) == metric.value


def test_display_follows_evidence_not_literals(evidence_repo, monkeypatch):
    """A re-pinned edit changes the displayed value and fails self-consistency."""
    directory = evidence_repo / "results/v2.0"
    path = directory / "official-test-results.json"
    path.write_bytes(path.read_bytes().replace(b"0.8663107741477272", b"0.1234"))
    digest = sha256_file(path)
    sums = directory / "SHA256SUMS"
    sums.write_text(
        sums.read_text().replace(evidence_module.EXPECTED_HASHES[path.name], digest)
    )
    monkeypatch.setitem(evidence_module.EXPECTED_HASHES, path.name, digest)

    edited = load_frozen_evidence(directory)

    assert official_metric(edited, "binary", "f1_macro").display == "0.1234"
    failed = [check.name for check in consistency_checks(edited) if not check.passed]
    assert failed == ["Macro precision, recall and F1 equal means of matrix values"]


# Stage comparison ---------------------------------------------------------


@pytest.mark.parametrize("task", TASKS)
def test_comparison_uses_exactly_the_frozen_ranking_metrics(catalog, task):
    comparisons = stage_comparisons(catalog.selection, catalog.official, task)
    ranking = [
        rule["metric"] for rule in catalog.selection["selected"][task]["ranking"]
    ]

    assert [c.definition.key for c in comparisons] == ranking
    for comparison in comparisons:
        assert comparison.validation.stage is VALIDATION
        assert comparison.official.stage is OFFICIAL_TEST
        assert comparison.delta == pytest.approx(
            comparison.official.value - comparison.validation.value
        )


def test_direction_respects_whether_lower_is_better(catalog):
    by_key = {
        c.definition.key: c
        for c in stage_comparisons(catalog.selection, catalog.official, "binary")
    }

    assert by_key["false_positive_rate"].delta > 0
    assert by_key["false_positive_rate"].direction == "worse on test"
    assert by_key["f1_macro"].direction == "worse on test"
    improved = StageComparison(
        validation=replace(by_key["false_positive_rate"].validation, value=0.3),
        official=by_key["false_positive_rate"].official,
    )
    assert improved.direction == "better on test"


def test_partial_metrics_render_as_not_recorded(official):
    del official.report["tasks"]["binary"]["official_test_metrics"]["roc_auc"]

    metric = official_metric(official, "binary", "roc_auc")

    assert metric.value is None and metric.display == NOT_RECORDED


def test_non_finite_metric_is_rejected(official):
    official.report["tasks"]["binary"]["official_test_metrics"]["f1_macro"] = math.inf

    with pytest.raises(EvidenceError, match="finite"):
        official_metric(official, "binary", "f1_macro")


def test_unknown_task_and_metric_are_rejected(official):
    with pytest.raises(EvidenceError, match="unknown task"):
        official_metric(official, "anomaly", "f1_macro")
    with pytest.raises(EvidenceError, match="no display definition"):
        official_metric(official, "binary", "mystery_metric")


# Labels and per-class tables ---------------------------------------------


def test_unexpected_attack_family_is_rejected(official):
    labels = official.report["tasks"]["multiclass"]["official_test_metrics"]["labels"]
    labels[labels.index("worms")] = "ransomware"

    with pytest.raises(EvidenceError, match="outside the frozen taxonomy.*ransomware"):
        class_labels(official, "multiclass")


def test_incomplete_or_duplicate_labels_are_rejected(official):
    metrics = official.report["tasks"]["binary"]["official_test_metrics"]
    metrics["labels"] = [0, 0]
    with pytest.raises(EvidenceError, match="duplicated"):
        class_labels(official, "binary")
    metrics["labels"] = [1]
    with pytest.raises(EvidenceError, match="incomplete"):
        class_labels(official, "binary")


def test_per_class_table_rejects_unknown_class_entries(official):
    per_class = official.report["tasks"]["multiclass"]["official_test_metrics"][
        "per_class"
    ]
    per_class["ransomware"] = per_class["worms"]

    with pytest.raises(EvidenceError, match="unknown classes"):
        per_class_table(official, "multiclass")


def test_per_class_table_flags_weak_and_small_classes(catalog):
    table = per_class_table(catalog.official, "multiclass").set_index("label")

    assert table.loc["analysis", "weakness"] == "missed and over-predicted"
    assert table.loc["backdoor", "weakness"] == "mostly missed"
    assert table.loc["fuzzers", "weakness"] == "over-predicted"
    assert table.loc["generic", "weakness"] == ""
    assert bool(table.loc["worms", "small_support"])
    assert weak_classes(table.reset_index()) == ["Analysis", "Backdoor", "DoS"]


@pytest.mark.parametrize(
    ("precision", "recall", "expected"),
    [
        (0.9, 0.9, ""),
        (0.9, 0.1, "mostly missed"),
        (0.1, 0.9, "over-predicted"),
        (None, 0.5, "not recorded"),
    ],
)
def test_weakness_label(precision, recall, expected):
    assert weakness_label(precision, recall) == expected


def test_family_detection_reconstructs_whole_counts(catalog):
    table = family_detection_table(catalog.official).set_index("family")

    assert table["support"].sum() == 45_332
    assert table.loc["fuzzers", "missed"] == 450
    assert "normal" not in table.index


def test_family_detection_rejects_non_integral_reconstruction(official):
    rates = official.report["tasks"]["binary"]["official_test_metrics"][
        "per_family_detection_rate"
    ]
    rates["worms"] = 0.5123

    with pytest.raises(EvidenceError, match="whole record count"):
        family_detection_table(official)


def test_family_detection_requires_the_same_official_records(official):
    official.report["tasks"]["binary"]["split_report"]["id_sha256"]["official_test"] = (
        "0" * 64
    )

    with pytest.raises(EvidenceError, match="records differ"):
        family_detection_table(official)


# Confusion matrices -------------------------------------------------------


def test_binary_confusion_matrix_prepares_long_and_wide_frames(catalog):
    matrix = confusion_matrix(catalog.official, "binary")
    cells = matrix.long_frame().set_index(["actual", "predicted"])

    assert matrix.total == 82_332
    assert matrix.display_labels == ("Normal", "Attack")
    assert cells.loc[("Normal", "Attack"), "count"] == 9_951
    assert cells.loc[("Normal", "Attack"), "share_of_actual"] == pytest.approx(
        catalog.official.report["tasks"]["binary"]["official_test_metrics"][
            "false_positive_rate"
        ]
    )
    assert matrix.wide_frame().loc["Attack", "Normal"] == 545


def test_top_confusions_exclude_correct_and_empty_cells(catalog):
    top = confusion_matrix(catalog.official, "multiclass").top_confusions(limit=50)

    assert (top["actual"] != top["predicted"]).all()
    assert (top["count"] > 0).all()
    assert top.iloc[0][["actual", "predicted"]].tolist() == ["Normal", "Fuzzers"]


@pytest.mark.parametrize(
    ("matrix", "message"),
    [
        (None, "missing or empty"),
        ([], "missing or empty"),
        ([[1, 2, 3], [4, 5, 6]], "2×2"),
        ([[1, 2], [3]], "2×2"),
        ([[1, -2], [3, 4]], "non-negative integers"),
        ([[1, True], [3, 4]], "non-negative integers"),
        ([[1.0, 2], [3, 4]], "non-negative integers"),
        ([[0, 0], [0, 0]], "contains no records"),
    ],
)
def test_invalid_confusion_matrices_fail_closed(matrix, message):
    with pytest.raises(EvidenceError, match=message):
        build_confusion_matrix("binary", (0, 1), matrix)


def test_confusion_matrix_total_must_match_samples():
    with pytest.raises(EvidenceError, match="differs from the recorded sample count"):
        build_confusion_matrix("binary", (0, 1), [[1, 2], [3, 4]], expected_total=11)


def test_committed_report_is_internally_consistent(catalog):
    checks = consistency_checks(catalog.official)

    assert len(checks) >= 20
    assert [c.name for c in checks if not c.passed] == []


def test_consistency_detects_a_contradictory_per_class_value(official):
    per_class = official.report["tasks"]["multiclass"]["official_test_metrics"][
        "per_class"
    ]
    per_class["dos"]["recall"] = 0.5

    failed = {c.name for c in consistency_checks(official) if not c.passed}

    assert "Per-class recall equals diagonal / row total" in failed


def test_consistency_derives_f1_instead_of_trusting_recorded_values(official):
    """A matching edit to per-class F1 and macro F1 must still be detected."""
    metrics = official.report["tasks"]["multiclass"]["official_test_metrics"]
    metrics["per_class"]["dos"]["f1"] += 0.1
    metrics["f1_macro"] += 0.01

    failed = {c.name for c in consistency_checks(official) if not c.passed}

    assert "Per-class f1 equals harmonic mean of matrix precision and recall" in failed
    assert "Macro precision, recall and F1 equal means of matrix values" in failed


def test_consistency_does_not_mask_code_defects(official, monkeypatch):
    from cids.workbench import confusion

    def broken(precision, recall):
        raise TypeError("bug in derived metric")

    monkeypatch.setattr(confusion, "_f1", broken)

    with pytest.raises(TypeError, match="bug in derived metric"):
        consistency_checks(official)


def test_unrecorded_class_metrics_are_reported_not_flagged(official):
    per_class = official.report["tasks"]["multiclass"]["official_test_metrics"][
        "per_class"
    ]
    del per_class["analysis"]["recall"]

    table = per_class_table(official, "multiclass")

    assert unrecorded_classes(table) == ["Analysis"]
    assert "Analysis" not in weak_classes(table)


def test_binary_outcomes_name_the_recorded_cells(catalog):
    outcomes = binary_outcomes(catalog.official)

    assert outcomes.false_positives == 9_951
    assert outcomes.false_negatives == 545
    assert outcomes.normal_records == 37_000
    assert outcomes.attack_predictions == 9_951 + 44_787


def test_consistency_reports_missing_structure_instead_of_crashing(official):
    del official.report["tasks"]["binary"]["official_test_metrics"]["per_class"]

    failed = [c for c in consistency_checks(official) if not c.passed]

    assert any(
        c.name == "Report structure is complete" and c.scope == "binary" for c in failed
    )
