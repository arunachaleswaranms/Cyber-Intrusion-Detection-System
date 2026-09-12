"""Manifest validation before any trusted local model is deserialized."""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from cids.config import EXPERIMENT_CONFIG_VERSION
from cids.datasets.unsw_nb15 import SCHEMA_VERSION
from cids.final_evaluation import FINAL_MODEL_ARTIFACT_VERSION
from cids.preprocessing import PREPROCESSOR_VERSION

MODEL_PACK_MANIFEST_VERSION = "cids-trusted-model-pack-v1"
MODEL_SELECTION_VERSION = "unsw-nb15-model-selection-v1"
FINAL_PROTOCOL_VERSION = "unsw-nb15-final-evaluation-v1"
DEMO_ARTIFACT_VERSION = "unsw-nb15-workbench-demo-v1"
TRUST_METHOD = "explicit_local_cli"
PROVENANCE_TYPES = {"maintainer_final_v2", "development_demo_v1"}
EXPECTED_RUNTIME = {
    "python": "3.12.14",
    "libraries": {
        "joblib": "1.5.3",
        "numpy": "2.3.5",
        "pandas": "2.2.3",
        "scikit_learn": "1.8.0",
    },
}
EXPECTED_CONTRACTS_BASE = {
    "schema_version": SCHEMA_VERSION,
    "preprocessor_version": PREPROCESSOR_VERSION,
    "experiment_config_version": EXPERIMENT_CONFIG_VERSION,
    "experiment_config_sha256": "070c009c139f41bcf34d63c7a5fa1324c819ded7a5884b800cc1bdbfb34234d2",
    "model_selection_version": MODEL_SELECTION_VERSION,
    "model_selection_sha256": "c00c668f4032c9630802200add755359a6bf639c6be41471ab286a3b2299d027",
    "final_protocol_version": FINAL_PROTOCOL_VERSION,
    "final_protocol_sha256": "c4fc000d24d27cada9740c1350c3b1e22d710cbd537353f33c9036a980ccb517",
}


class ModelPackError(ValueError):
    """Raised before loading an untrusted or incompatible model pack."""


@dataclass(frozen=True)
class VerifiedModelPack:
    root: Path
    manifest: dict
    artifact_paths: dict[str, Path]


def current_runtime() -> dict:
    return {
        "python": platform.python_version(),
        "libraries": {
            "joblib": joblib.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
    }


def _exact_keys(value: object, expected: set[str], location: str) -> dict:
    if not isinstance(value, dict):
        raise ModelPackError(f"{location} must be an object")
    actual = set(value)
    if actual != expected:
        raise ModelPackError(
            f"{location} keys mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    return value


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _parse_aware_timestamp(value: object, location: str) -> None:
    if not isinstance(value, str):
        raise ModelPackError(f"{location} must be an ISO 8601 string")
    compatible = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(compatible)
    except ValueError as exc:
        raise ModelPackError(f"{location} must be valid ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ModelPackError(f"{location} must include a UTC offset")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def compute_model_pack_id(manifest: dict) -> str:
    payload = dict(manifest)
    payload.pop("model_pack_id", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_model_pack_manifest(manifest: object) -> dict:
    root = _exact_keys(
        manifest,
        {
            "manifest_version",
            "model_pack_id",
            "provenance_type",
            "created_at_utc",
            "trust",
            "runtime",
            "contracts",
            "artifacts",
            "creation_config_sha256",
        },
        "model-pack manifest",
    )
    if root["manifest_version"] != MODEL_PACK_MANIFEST_VERSION:
        raise ModelPackError("unsupported model-pack manifest version")
    if root["provenance_type"] not in PROVENANCE_TYPES:
        raise ModelPackError("unsupported model-pack provenance")
    _parse_aware_timestamp(root["created_at_utc"], "created_at_utc")
    if not _is_sha256(root["creation_config_sha256"]):
        raise ModelPackError("creation_config_sha256 must be a SHA-256 digest")

    trust = _exact_keys(
        root["trust"],
        {"acknowledged", "method", "acknowledged_at_utc"},
        "trust",
    )
    if trust["acknowledged"] is not True or trust["method"] != TRUST_METHOD:
        raise ModelPackError("model pack lacks explicit local trust acknowledgement")
    _parse_aware_timestamp(trust["acknowledged_at_utc"], "acknowledged_at_utc")

    runtime = _exact_keys(root["runtime"], {"python", "libraries"}, "runtime")
    _exact_keys(
        runtime["libraries"],
        {"joblib", "numpy", "pandas", "scikit_learn"},
        "runtime.libraries",
    )
    if runtime != EXPECTED_RUNTIME:
        raise ModelPackError("model-pack runtime does not match the pinned environment")

    expected_contract_keys = set(EXPECTED_CONTRACTS_BASE) | {"artifact_version"}
    contracts = _exact_keys(root["contracts"], expected_contract_keys, "contracts")
    for key, expected in EXPECTED_CONTRACTS_BASE.items():
        if contracts[key] != expected:
            raise ModelPackError(f"model-pack contract mismatch: {key}")
    expected_artifact_version = (
        FINAL_MODEL_ARTIFACT_VERSION
        if root["provenance_type"] == "maintainer_final_v2"
        else DEMO_ARTIFACT_VERSION
    )
    if contracts["artifact_version"] != expected_artifact_version:
        raise ModelPackError("artifact version does not match model-pack provenance")

    artifacts = _exact_keys(root["artifacts"], {"binary", "multiclass"}, "artifacts")
    filenames: set[str] = set()
    for task in ("binary", "multiclass"):
        spec = _exact_keys(
            artifacts[task],
            {"task", "filename", "sha256", "size_bytes"},
            f"artifacts.{task}",
        )
        if spec["task"] != task:
            raise ModelPackError(f"artifact task mismatch: {task}")
        filename = spec["filename"]
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
            or filename in filenames
        ):
            raise ModelPackError(f"unsafe or duplicate artifact filename: {filename!r}")
        filenames.add(filename)
        if not _is_sha256(spec["sha256"]):
            raise ModelPackError(f"invalid artifact SHA-256: {task}")
        if (
            not isinstance(spec["size_bytes"], int)
            or isinstance(spec["size_bytes"], bool)
            or spec["size_bytes"] <= 0
        ):
            raise ModelPackError(f"invalid artifact size: {task}")

    if root["model_pack_id"] != compute_model_pack_id(root):
        raise ModelPackError("model_pack_id does not match manifest contents")
    return root


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ModelPackError(f"duplicate manifest JSON key: {key!r}")
        value[key] = item
    return value


def preflight_model_pack(pack_dir: str | Path) -> VerifiedModelPack:
    """Verify trust metadata, paths, hashes, and runtime without deserializing."""
    requested_root = Path(pack_dir)
    if requested_root.is_symlink() or not requested_root.is_dir():
        raise ModelPackError("model-pack root must be a non-symlink directory")
    root = requested_root.resolve()
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ModelPackError("model-pack manifest must be a regular file")
    if manifest_path.stat().st_size > 64 * 1024:
        raise ModelPackError("model-pack manifest exceeds 64 KiB")
    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelPackError("model-pack manifest is invalid JSON") from exc
    validated = validate_model_pack_manifest(manifest)
    if current_runtime() != EXPECTED_RUNTIME:
        raise ModelPackError("current runtime does not match the pinned environment")

    artifact_paths: dict[str, Path] = {}
    for task, spec in validated["artifacts"].items():
        path = root / spec["filename"]
        if path.is_symlink() or not path.is_file():
            raise ModelPackError(f"{task} artifact must be a regular file")
        if path.resolve().parent != root:
            raise ModelPackError(f"{task} artifact escapes the model-pack root")
        if path.stat().st_size != spec["size_bytes"]:
            raise ModelPackError(f"{task} artifact size mismatch")
        if _sha256_file(path) != spec["sha256"]:
            raise ModelPackError(f"{task} artifact SHA-256 mismatch")
        artifact_paths[task] = path
    return VerifiedModelPack(
        root=root,
        manifest=validated,
        artifact_paths=artifact_paths,
    )
