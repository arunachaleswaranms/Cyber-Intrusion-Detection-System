import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.final_evaluation import FINAL_MODEL_ARTIFACT_VERSION  # noqa: E402
from cids.workbench import model_pack  # noqa: E402
from cids.workbench.model_pack import (  # noqa: E402
    EXPECTED_CONTRACTS_BASE,
    EXPECTED_REGISTRATION_POLICY_SHA256,
    EXPECTED_RUNTIME,
    MAX_ARTIFACT_BYTES,
    MODEL_PACK_MANIFEST_VERSION,
    ModelPackError,
    compute_model_pack_id,
    load_maintainer_final_digests,
    preflight_model_pack,
    verify_staged_model_pack,
)

ARTIFACT_BYTES = {"binary": b"binary-model", "multiclass": b"family-model"}


@pytest.fixture
def pinned_host_runtime(monkeypatch):
    """Isolate path and hash checks from the interpreter running the suite."""
    monkeypatch.setattr(model_pack, "current_runtime", lambda: copy.deepcopy(EXPECTED_RUNTIME))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def anchored_fake_artifacts(monkeypatch):
    """Stand in for the gate's selected-artifact digests with the fake bytes."""
    digests = {task: sha256(value) for task, value in ARTIFACT_BYTES.items()}
    monkeypatch.setattr(
        model_pack, "load_maintainer_final_digests", lambda *_args: dict(digests)
    )


def valid_pack(tmp_path):
    root = tmp_path / "model-pack"
    root.mkdir()
    artifacts = {}
    for task, value in ARTIFACT_BYTES.items():
        filename = f"{task}.joblib"
        (root / filename).write_bytes(value)
        artifacts[task] = {
            "task": task,
            "filename": filename,
            "sha256": sha256(value),
            "size_bytes": len(value),
        }
    manifest = {
        "manifest_version": MODEL_PACK_MANIFEST_VERSION,
        "model_pack_id": "",
        "provenance_type": "maintainer_final_v2",
        "created_at_utc": "2026-09-12T10:00:00Z",
        "trust": {
            "acknowledged": True,
            "method": "explicit_local_cli",
            "acknowledged_at_utc": "2026-09-12T10:00:00+00:00",
        },
        "runtime": copy.deepcopy(EXPECTED_RUNTIME),
        "contracts": {
            **EXPECTED_CONTRACTS_BASE,
            "artifact_version": FINAL_MODEL_ARTIFACT_VERSION,
        },
        "artifacts": artifacts,
        "creation_config_sha256": EXPECTED_REGISTRATION_POLICY_SHA256,
    }
    manifest["model_pack_id"] = compute_model_pack_id(manifest)
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    # Packs are only valid in a directory named by their model_pack_id.
    named_root = root.rename(tmp_path / manifest["model_pack_id"])
    return named_root, manifest


def rewrite_manifest(root, manifest):
    manifest["model_pack_id"] = compute_model_pack_id(manifest)
    (root / "manifest.json").write_text(json.dumps(manifest))


def test_preflight_verifies_manifest_runtime_paths_sizes_and_hashes(
    tmp_path, pinned_host_runtime, anchored_fake_artifacts
):
    root, manifest = valid_pack(tmp_path)

    verified = preflight_model_pack(root)

    assert verified.manifest["model_pack_id"] == manifest["model_pack_id"]
    assert set(verified.artifact_paths) == {"binary", "multiclass"}


def test_preflight_rejects_missing_explicit_trust(tmp_path):
    root, manifest = valid_pack(tmp_path)
    manifest["trust"]["acknowledged"] = False
    rewrite_manifest(root, manifest)

    with pytest.raises(ModelPackError, match="explicit local trust"):
        preflight_model_pack(root)


def test_preflight_rejects_traversal_even_with_recomputed_manifest_id(tmp_path):
    root, manifest = valid_pack(tmp_path)
    manifest["artifacts"]["binary"]["filename"] = "../binary.joblib"
    rewrite_manifest(root, manifest)

    with pytest.raises(ModelPackError, match="unsafe or duplicate"):
        preflight_model_pack(root)


def test_preflight_rejects_tampered_artifact(tmp_path, pinned_host_runtime):
    root, _ = valid_pack(tmp_path)
    (root / "binary.joblib").write_bytes(b"changed-model")

    with pytest.raises(ModelPackError, match="size mismatch|SHA-256 mismatch"):
        preflight_model_pack(root)


def test_preflight_rejects_runtime_claim_not_matching_frozen_environment(
    tmp_path, pinned_host_runtime
):
    root, manifest = valid_pack(tmp_path)
    manifest["runtime"]["python"] = "3.12.13"
    rewrite_manifest(root, manifest)

    with pytest.raises(ModelPackError, match="model-pack runtime does not match"):
        preflight_model_pack(root)


def test_preflight_rejects_host_runtime_not_matching_frozen_environment(
    tmp_path, monkeypatch
):
    root, _ = valid_pack(tmp_path)
    host = copy.deepcopy(EXPECTED_RUNTIME)
    host["libraries"]["scikit_learn"] = "1.7.2"
    monkeypatch.setattr(model_pack, "current_runtime", lambda: host)

    with pytest.raises(ModelPackError, match="current runtime does not match"):
        preflight_model_pack(root)


def test_preflight_rejects_duplicate_manifest_keys(tmp_path):
    root, _ = valid_pack(tmp_path)
    (root / "manifest.json").write_text(
        '{"manifest_version":"one","manifest_version":"two"}'
    )

    with pytest.raises(ModelPackError, match="duplicate manifest JSON key"):
        preflight_model_pack(root)


def test_committed_gate_evidence_anchors_the_selected_final_artifacts():
    assert load_maintainer_final_digests() == {
        "binary": "4f0364cee99e05d595110ca29a51c0fb7f4c500527dfed426f115ebfc8a84482",
        "multiclass": (
            "ea49309a6e20c448379deef8145bdb103fff59a8825b3d93747f4139fa142308"
        ),
    }


def test_preflight_rejects_maintainer_pack_not_matching_gate_anchor(
    tmp_path, pinned_host_runtime
):
    root, _ = valid_pack(tmp_path)

    with pytest.raises(ModelPackError, match="binary artifact is not the selected"):
        preflight_model_pack(root)


def test_preflight_rejects_maintainer_pack_when_gate_evidence_fails(
    tmp_path, pinned_host_runtime, evidence_repo
):
    root, _ = valid_pack(tmp_path)
    report = evidence_repo / "results/v2.1/shap-gate-selected-v2.json"
    report.write_bytes(report.read_bytes() + b" ")

    with pytest.raises(ModelPackError, match="trust anchor failed verification"):
        preflight_model_pack(root, gate_evidence_dir=evidence_repo / "results/v2.1")


def test_preflight_requires_directory_named_by_model_pack_id(
    tmp_path, pinned_host_runtime, anchored_fake_artifacts
):
    root, _ = valid_pack(tmp_path)
    renamed = root.rename(tmp_path / "copied-pack")

    with pytest.raises(ModelPackError, match="directory name must equal"):
        preflight_model_pack(renamed)
    assert verify_staged_model_pack(renamed).manifest["model_pack_id"] == root.name


def test_preflight_rejects_unpinned_creation_config_for_maintainer_pack(tmp_path):
    root, manifest = valid_pack(tmp_path)
    manifest["creation_config_sha256"] = "0" * 64
    rewrite_manifest(root, manifest)

    with pytest.raises(ModelPackError, match="pinned registration policy"):
        preflight_model_pack(root)


def test_preflight_rejects_non_utc_timestamp(tmp_path):
    root, manifest = valid_pack(tmp_path)
    manifest["created_at_utc"] = "2026-09-12T15:30:00+05:30"
    rewrite_manifest(root, manifest)

    with pytest.raises(ModelPackError, match="created_at_utc must be in UTC"):
        preflight_model_pack(root)


def test_preflight_rejects_non_app_owned_artifact_filename(tmp_path):
    root, manifest = valid_pack(tmp_path)
    (root / "binary.joblib").rename(root / "model.pkl")
    manifest["artifacts"]["binary"]["filename"] = "model.pkl"
    rewrite_manifest(root, manifest)

    with pytest.raises(ModelPackError, match="not the app-owned name"):
        preflight_model_pack(root)


def test_preflight_rejects_artifact_size_above_limit(tmp_path):
    root, manifest = valid_pack(tmp_path)
    manifest["artifacts"]["binary"]["size_bytes"] = MAX_ARTIFACT_BYTES + 1
    rewrite_manifest(root, manifest)

    with pytest.raises(ModelPackError, match="invalid artifact size"):
        preflight_model_pack(root)


def test_preflight_rejects_deeply_nested_manifest_cleanly(tmp_path):
    root, _ = valid_pack(tmp_path)
    (root / "manifest.json").write_text("[" * 60000)

    with pytest.raises(ModelPackError, match="invalid JSON"):
        preflight_model_pack(root)
