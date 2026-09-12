import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.final_evaluation import FINAL_MODEL_ARTIFACT_VERSION  # noqa: E402
from cids.workbench.model_pack import (  # noqa: E402
    EXPECTED_CONTRACTS_BASE,
    EXPECTED_RUNTIME,
    MODEL_PACK_MANIFEST_VERSION,
    ModelPackError,
    compute_model_pack_id,
    preflight_model_pack,
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def valid_pack(tmp_path):
    root = tmp_path / "model-pack"
    root.mkdir()
    artifact_bytes = {"binary": b"binary-model", "multiclass": b"family-model"}
    artifacts = {}
    for task, value in artifact_bytes.items():
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
        "creation_config_sha256": "0" * 64,
    }
    manifest["model_pack_id"] = compute_model_pack_id(manifest)
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return root, manifest


def rewrite_manifest(root, manifest):
    manifest["model_pack_id"] = compute_model_pack_id(manifest)
    (root / "manifest.json").write_text(json.dumps(manifest))


def test_preflight_verifies_manifest_runtime_paths_sizes_and_hashes(tmp_path):
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


def test_preflight_rejects_tampered_artifact(tmp_path):
    root, _ = valid_pack(tmp_path)
    (root / "binary.joblib").write_bytes(b"changed-model")

    with pytest.raises(ModelPackError, match="size mismatch|SHA-256 mismatch"):
        preflight_model_pack(root)


def test_preflight_rejects_runtime_claim_not_matching_frozen_environment(tmp_path):
    root, manifest = valid_pack(tmp_path)
    manifest["runtime"]["python"] = "3.12.13"
    rewrite_manifest(root, manifest)

    with pytest.raises(ModelPackError, match="pinned environment"):
        preflight_model_pack(root)


def test_preflight_rejects_duplicate_manifest_keys(tmp_path):
    root, _ = valid_pack(tmp_path)
    (root / "manifest.json").write_text(
        '{"manifest_version":"one","manifest_version":"two"}'
    )

    with pytest.raises(ModelPackError, match="duplicate manifest JSON key"):
        preflight_model_pack(root)
