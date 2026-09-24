import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.workbench import catalog as catalog_module  # noqa: E402
from cids.workbench.catalog import (  # noqa: E402
    CatalogHealth,
    ComponentStatus,
    load_catalog,
)

DEPENDENTS_OF_OFFICIAL = (
    "experiment_config",
    "model_selection",
    "final_protocol",
    "dataset_manifest",
    "explanation_gate",
)


def _statuses(catalog):
    return {component.key: component.status for component in catalog.components}


def _rewrite_json(path: Path, mutate) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def test_committed_repository_evidence_is_complete_and_bound():
    catalog = load_catalog()

    assert catalog.health is CatalogHealth.COMPLETE
    assert set(_statuses(catalog).values()) == {ComponentStatus.VERIFIED}
    assert catalog.selection["selection_partition"] == "validation"
    assert catalog.component("official_results").required
    assert (
        catalog.relative(catalog.component("model_selection").paths[0])
        == "configs/v2-model-selection-v1.json"
    )


def test_copied_evidence_verifies_without_dataset_or_models(evidence_repo):
    assert not (evidence_repo / "artifacts").exists()
    assert not (evidence_repo / "dataset/unsw-nb15/raw").exists()

    assert load_catalog(evidence_repo).health is CatalogHealth.COMPLETE


def test_missing_gate_evidence_degrades_only_explainability(evidence_repo):
    shutil.rmtree(evidence_repo / "results/v2.1")

    catalog = load_catalog(evidence_repo)
    statuses = _statuses(catalog)

    assert catalog.health is CatalogHealth.DEGRADED
    assert statuses["explanation_gate"] is ComponentStatus.MISSING
    assert statuses["official_results"] is ComponentStatus.VERIFIED
    assert catalog.gate is None and catalog.official is not None
    assert "results/v2.1/shap-gate-selected-v2.json" in (
        catalog.component("explanation_gate").detail
    )


def test_missing_official_evidence_blocks_and_skips_dependents(evidence_repo):
    shutil.rmtree(evidence_repo / "results/v2.0")

    catalog = load_catalog(evidence_repo)
    statuses = _statuses(catalog)

    assert catalog.health is CatalogHealth.BLOCKED
    assert statuses["official_results"] is ComponentStatus.MISSING
    for key in DEPENDENTS_OF_OFFICIAL:
        assert statuses[key] is ComponentStatus.SKIPPED
    assert statuses["workbench_policy"] is ComponentStatus.VERIFIED
    assert catalog.official is None and catalog.selection is None


def test_tampered_official_result_is_an_integrity_failure(evidence_repo):
    path = evidence_repo / "results/v2.0/official-test-results.json"
    path.write_bytes(
        path.read_bytes().replace(b"0.8663107741477272", b"0.9663107741477272")
    )

    catalog = load_catalog(evidence_repo)
    component = catalog.component("official_results")

    assert catalog.health is CatalogHealth.BLOCKED
    assert component.status is ComponentStatus.FAILED
    assert "SHA-256 mismatch" in component.detail


def test_malformed_selection_json_fails_and_skips_protocol(evidence_repo):
    (evidence_repo / "configs/v2-model-selection-v1.json").write_text(
        "{", encoding="utf-8"
    )

    statuses = _statuses(load_catalog(evidence_repo))

    assert statuses["model_selection"] is ComponentStatus.FAILED
    assert statuses["final_protocol"] is ComponentStatus.SKIPPED
    assert statuses["official_results"] is ComponentStatus.VERIFIED


def test_edited_validation_metric_breaks_the_recorded_selection_digest(evidence_repo):
    _rewrite_json(
        evidence_repo / "configs/v2-model-selection-v1.json",
        lambda value: value["selected"]["binary"]["selected_validation_metrics"].update(
            f1_macro=0.99
        ),
    )

    catalog = load_catalog(evidence_repo)
    component = catalog.component("model_selection")

    assert component.status is ComponentStatus.FAILED
    assert "does not match the digest recorded by the official run" in component.detail
    assert catalog.selection is None


def test_edited_experiment_config_is_rejected(evidence_repo):
    _rewrite_json(
        evidence_repo / "configs/v2-baseline-v1.json",
        lambda value: value["split"].update(seed=7),
    )

    statuses = _statuses(load_catalog(evidence_repo))

    assert statuses["experiment_config"] is ComponentStatus.FAILED
    assert statuses["model_selection"] is ComponentStatus.SKIPPED


def test_dataset_manifest_must_match_the_official_run(evidence_repo):
    _rewrite_json(
        evidence_repo / "dataset/unsw-nb15/manifest.json",
        lambda value: value["files"][1].update(records=82_331),
    )

    component = load_catalog(evidence_repo).component("dataset_manifest")

    assert component.status is ComponentStatus.FAILED
    assert "test records differs" in component.detail


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("[]", "must be an object"),
        ('{"manifest_version": 1, "manifest_version": 1}', "duplicate JSON key"),
    ],
)
def test_malformed_manifest_json_fails_instead_of_crashing(
    evidence_repo, content, message
):
    (evidence_repo / "dataset/unsw-nb15/manifest.json").write_text(content)

    component = load_catalog(evidence_repo).component("dataset_manifest")

    assert component.status is ComponentStatus.FAILED
    assert message in component.detail


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["files"].append(1), "must be objects with a role"),
        (
            lambda value: value["files"].append(
                dict(value["files"][1], sha256="0" * 64)
            ),
            "repeats role 'test'",
        ),
    ],
)
def test_manifest_entries_must_be_unique_objects(evidence_repo, mutate, message):
    _rewrite_json(evidence_repo / "dataset/unsw-nb15/manifest.json", mutate)

    component = load_catalog(evidence_repo).component("dataset_manifest")

    assert component.status is ComponentStatus.FAILED
    assert message in component.detail


def test_changed_workbench_policy_invalidates_gate(evidence_repo):
    _rewrite_json(
        evidence_repo / "configs/v2.1-workbench-v2.json",
        lambda value: value["queue"].update(higher_score_boundary=0.8),
    )

    catalog = load_catalog(evidence_repo)
    component = catalog.component("explanation_gate")

    assert catalog.component("workbench_policy").status is ComponentStatus.VERIFIED
    assert component.status is ComponentStatus.FAILED
    assert "different workbench policy" in component.detail


def test_invalid_repository_root_reports_missing_evidence(tmp_path):
    catalog = load_catalog(tmp_path / "does-not-exist")

    assert catalog.health is CatalogHealth.BLOCKED
    assert {c.status for c in catalog.components} <= {
        ComponentStatus.MISSING,
        ComponentStatus.SKIPPED,
    }


def test_evidence_path_that_is_a_directory_fails_instead_of_crashing(evidence_repo):
    path = evidence_repo / "configs/v2.1-workbench-v2.json"
    path.unlink()
    path.mkdir()

    component = load_catalog(evidence_repo).component("workbench_policy")

    assert component.status is ComponentStatus.FAILED
    assert "IsADirectoryError" in component.detail


def test_programming_errors_are_not_reported_as_evidence_status(
    evidence_repo, monkeypatch
):
    def broken_loader(path):
        raise KeyError("bug")

    monkeypatch.setattr(catalog_module, "load_workbench_config", broken_loader)

    with pytest.raises(KeyError):
        load_catalog(evidence_repo)


def test_relative_paths_outside_the_root_are_shown_verbatim(tmp_path):
    catalog = load_catalog()
    outside = tmp_path / "elsewhere.json"

    assert catalog.relative(outside) == str(outside)
