import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.workbench.config import load_workbench_config  # noqa: E402
from cids.workbench.gate_evidence import (  # noqa: E402
    DEFAULT_GATE_EVIDENCE_DIR,
    GATE_REPORT_FILENAME,
    GATE_VERSION,
    load_gate_evidence,
    validate_gate_report,
)
from cids.workbench.integrity import EvidenceError  # noqa: E402


@pytest.fixture
def policy():
    return load_workbench_config()


@pytest.fixture
def report():
    path = DEFAULT_GATE_EVIDENCE_DIR / GATE_REPORT_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


def test_loads_accepted_gate_evidence_with_development_only_partitions(policy):
    gate = load_gate_evidence(policy)

    assert set(gate.tasks) == {"binary", "multiclass"}
    for task in gate.tasks.values():
        assert task.background_partition == "prepared_train"
        assert task.foreground_partition == "prepared_validation"
        assert (
            task.max_additivity_error
            <= policy["explainability"]["additivity_abs_tolerance"]
        )
        assert task.source_feature_count == 42
    assert gate.tasks["multiclass"].class_labels[6] == "normal"


def test_gate_version_mirror_matches_the_gate_runner():
    pytest.importorskip("shap")
    from cids.experiments.run_shap_gate import GATE_VERSION as RUNNER_VERSION

    assert GATE_VERSION == RUNNER_VERSION


def test_rejects_tampered_gate_report_before_parsing(evidence_repo, policy):
    path = evidence_repo / "results/v2.1" / GATE_REPORT_FILENAME
    path.write_bytes(path.read_bytes().replace(b'"passed"', b'"failed"'))

    with pytest.raises(EvidenceError, match="SHA-256 mismatch"):
        load_gate_evidence(policy, evidence_repo / "results/v2.1")


def test_rejects_symlinked_gate_report(evidence_repo, policy):
    directory = evidence_repo / "results/v2.1"
    report = directory / GATE_REPORT_FILENAME
    report.rename(directory / "copy.json")
    report.symlink_to("copy.json")

    with pytest.raises(EvidenceError, match="regular non-symlink"):
        load_gate_evidence(policy, directory)


def test_rejects_missing_gate_directory(tmp_path, policy):
    with pytest.raises(EvidenceError, match="directory is unavailable"):
        load_gate_evidence(policy, tmp_path / "absent")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r.update(status="failed"), "did not pass"),
        (lambda r: r.update(gate_version="cids-shap-compatibility-gate-v1"), "version"),
        (
            lambda r: r.update(official_test_status="evaluated_once"),
            "official-test access",
        ),
        (
            lambda r: r.update(workbench_config_sha256="0" * 64),
            "different workbench policy",
        ),
        (lambda r: r["environment"].update(shap="0.51.0"), "pinned SHAP"),
        (lambda r: r["tasks"].pop("multiclass"), "both selected tasks"),
        (
            lambda r: r["tasks"]["binary"].update(
                official_test_used_as_explanation_data=True
            ),
            "used official-test data",
        ),
        (
            lambda r: r["tasks"]["binary"].update(background_partition="official_test"),
            "background is not the prepared training split",
        ),
        (
            lambda r: r["tasks"]["multiclass"].update(
                foreground_partition="official_test"
            ),
            "foreground is not the validation split",
        ),
        (
            lambda r: r["tasks"]["binary"].update(max_additivity_error=0.2),
            "additivity error exceeds tolerance",
        ),
        (
            lambda r: r["tasks"]["binary"].update(max_additivity_error=float("nan")),
            "finite number",
        ),
        (
            lambda r: r["tasks"]["binary"].update(elapsed_seconds=61.0),
            "time limit",
        ),
        (
            lambda r: r["tasks"]["binary"].update(explainer_algorithm="tree"),
            "explainer differs",
        ),
        (
            lambda r: r["tasks"]["binary"].update(background_rows=10_000),
            "background size",
        ),
        (
            lambda r: r["tasks"]["multiclass"].update(shap_values_shape=[10, 68]),
            "shape is inconsistent",
        ),
        (
            lambda r: r["tasks"]["binary"].update(source_feature_count=41),
            "frozen 42",
        ),
        (
            lambda r: r["tasks"]["binary"].update(artifact_sha256="not-a-digest"),
            "digest is malformed",
        ),
        (lambda r: r["tasks"]["binary"].update(extra="field"), "gate contract"),
    ],
)
def test_gate_semantics_fail_closed(report, policy, mutate, message):
    broken = copy.deepcopy(report)
    mutate(broken)

    with pytest.raises(EvidenceError, match=message):
        validate_gate_report(broken, policy)
