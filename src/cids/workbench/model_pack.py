"""Manifest validation before any trusted local model is deserialized.

Nothing in this module deserializes an artifact. ``preflight_model_pack`` is
the check later code must pass before calling ``joblib.load``; validating the
deserialized object and its internal metadata is a separate, later step.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

import joblib
import numpy as np
import pandas as pd
import sklearn

from cids.config import EXPERIMENT_CONFIG_VERSION
from cids.datasets.unsw_nb15 import SCHEMA_VERSION
from cids.final_evaluation import FINAL_MODEL_ARTIFACT_VERSION
from cids.preprocessing import PREPROCESSOR_VERSION
from cids.workbench.config import WorkbenchConfigError, load_workbench_config
from cids.workbench.gate_evidence import (
    DEFAULT_GATE_EVIDENCE_DIR,
    EXPECTED_GATE_HASHES,
    GATE_REPORT_FILENAME,
    GATE_TASKS,
    GATE_VERSION,
    load_gate_evidence,
)
from cids.workbench.integrity import EvidenceError

MODEL_PACK_MANIFEST_VERSION = "cids-trusted-model-pack-v1"
MODEL_SELECTION_VERSION = "unsw-nb15-model-selection-v1"
FINAL_PROTOCOL_VERSION = "unsw-nb15-final-evaluation-v1"
DEMO_ARTIFACT_VERSION = "unsw-nb15-workbench-demo-v1"
TRUST_METHOD = "explicit_local_cli"
PROVENANCE_TYPES = {"maintainer_final_v2", "development_demo_v1"}
MANIFEST_FILENAME = "manifest.json"
MAX_MANIFEST_BYTES = 64 * 1024
# App-owned artifact names; never derived from a source filename.
PACK_ARTIFACT_FILENAMES = {
    "binary": "binary.joblib",
    "multiclass": "multiclass.joblib",
}
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
REGISTRATION_POLICY_VERSION = "cids-model-pack-registration-v1"
DEFAULT_REGISTRATION_POLICY = (
    Path(__file__).resolve().parents[3]
    / "configs"
    / "v2.1-model-pack-registration-v1.json"
)
# Canonical digest of the frozen registration policy. Every maintainer_final_v2
# manifest records it as creation_config_sha256.
EXPECTED_REGISTRATION_POLICY_SHA256 = (
    "2daeacfe7236c2adb70c4104b063667db8be9868584d1483094bfefbfb89f533"
)
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
    if parsed.utcoffset() != timedelta(0):
        raise ModelPackError(f"{location} must be in UTC")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: dict) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def compute_model_pack_id(manifest: dict) -> str:
    payload = dict(manifest)
    payload.pop("model_pack_id", None)
    return _canonical_sha256(payload)


def validate_registration_policy(policy: object) -> dict:
    """Check the registration policy against the contracts it must restate."""
    root = _exact_keys(
        policy,
        {
            "policy_version",
            "manifest_version",
            "provenance_type",
            "trust",
            "trust_anchor",
            "pack",
            "deserialization",
        },
        "registration policy",
    )
    if root["policy_version"] != REGISTRATION_POLICY_VERSION:
        raise ModelPackError("unsupported registration policy version")
    if root["manifest_version"] != MODEL_PACK_MANIFEST_VERSION:
        raise ModelPackError("registration policy names another manifest version")
    if root["provenance_type"] != "maintainer_final_v2":
        raise ModelPackError("registration policy names another provenance type")
    if root["deserialization"] != "forbidden_during_registration":
        raise ModelPackError("registration policy must forbid deserialization")

    trust = _exact_keys(
        root["trust"], {"method", "confirmation_phrase"}, "registration policy trust"
    )
    phrase = trust["confirmation_phrase"]
    if trust["method"] != TRUST_METHOD:
        raise ModelPackError("registration policy names another trust method")
    if not isinstance(phrase, str) or not phrase or phrase != phrase.strip():
        raise ModelPackError("registration confirmation phrase is malformed")

    anchor = _exact_keys(
        root["trust_anchor"],
        {"source", "gate_version", "gate_report_sha256", "artifact_digest_field"},
        "registration policy trust_anchor",
    )
    if anchor != {
        "source": "accepted_explanation_gate",
        "gate_version": GATE_VERSION,
        "gate_report_sha256": EXPECTED_GATE_HASHES[GATE_REPORT_FILENAME],
        "artifact_digest_field": "tasks.<task>.artifact_sha256",
    }:
        raise ModelPackError(
            "registration trust anchor does not name the accepted gate evidence"
        )

    pack = _exact_keys(
        root["pack"],
        {
            "default_root",
            "directory_name",
            "manifest_filename",
            "artifact_filenames",
            "max_artifact_bytes",
        },
        "registration policy pack",
    )
    default_root = pack["default_root"]
    if not isinstance(default_root, str):
        raise ModelPackError("registration default pack root must be a string")
    relative = PurePosixPath(default_root)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:1] != ("artifacts",)
    ):
        raise ModelPackError(
            "registration default pack root must stay under the ignored artifacts/"
        )
    if pack["directory_name"] != "model_pack_id":
        raise ModelPackError("pack directories must be named by model_pack_id")
    if pack["manifest_filename"] != MANIFEST_FILENAME:
        raise ModelPackError("registration policy names another manifest filename")
    if pack["artifact_filenames"] != PACK_ARTIFACT_FILENAMES:
        raise ModelPackError("registration policy names other artifact filenames")
    if pack["max_artifact_bytes"] != MAX_ARTIFACT_BYTES:
        raise ModelPackError("registration policy names another artifact size limit")
    return root


def registration_policy_sha256(policy: dict) -> str:
    return _canonical_sha256(validate_registration_policy(policy))


def load_registration_policy(path: str | Path = DEFAULT_REGISTRATION_POLICY) -> dict:
    policy_path = Path(path)
    if policy_path.is_symlink() or not policy_path.is_file():
        raise ModelPackError(
            f"registration policy must be a regular file: {policy_path}"
        )
    try:
        value = json.loads(
            policy_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ModelPackError(
            f"registration policy is invalid JSON: {policy_path}"
        ) from exc
    if registration_policy_sha256(value) != EXPECTED_REGISTRATION_POLICY_SHA256:
        raise ModelPackError("registration policy differs from the pinned v1 policy")
    return value


def load_maintainer_final_digests(
    evidence_dir: str | Path = DEFAULT_GATE_EVIDENCE_DIR,
) -> dict[str, str]:
    """Selected-artifact digests recorded by the accepted, checksum-verified gate."""
    try:
        gate = load_gate_evidence(load_workbench_config(), evidence_dir)
    except (EvidenceError, WorkbenchConfigError, OSError, UnicodeDecodeError) as exc:
        raise ModelPackError(
            f"maintainer_final_v2 trust anchor failed verification: {exc}"
        ) from exc
    digests = {task: gate.tasks[task].artifact_sha256 for task in GATE_TASKS}
    if len(set(digests.values())) != len(digests):
        raise ModelPackError("gate evidence records the same artifact for both tasks")
    return digests


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
    if (
        root["provenance_type"] == "maintainer_final_v2"
        and root["creation_config_sha256"] != EXPECTED_REGISTRATION_POLICY_SHA256
    ):
        raise ModelPackError(
            "creation_config_sha256 does not match the pinned registration policy"
        )

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
        if filename != PACK_ARTIFACT_FILENAMES[task]:
            raise ModelPackError(f"{task} artifact filename is not the app-owned name")
        filenames.add(filename)
        if not _is_sha256(spec["sha256"]):
            raise ModelPackError(f"invalid artifact SHA-256: {task}")
        if (
            not isinstance(spec["size_bytes"], int)
            or isinstance(spec["size_bytes"], bool)
            or not 0 < spec["size_bytes"] <= MAX_ARTIFACT_BYTES
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


def read_manifest_json(path: Path) -> object:
    """Parse a bounded, strict manifest file without validating its contract."""
    if path.is_symlink() or not path.is_file():
        raise ModelPackError("model-pack manifest must be a regular file")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ModelPackError("model-pack manifest exceeds 64 KiB")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ModelPackError("model-pack manifest is invalid JSON") from exc


def _require_pack_dir(pack_dir: str | Path) -> Path:
    requested_root = Path(pack_dir)
    if requested_root.is_symlink() or not requested_root.is_dir():
        raise ModelPackError("model-pack root must be a non-symlink directory")
    return requested_root.resolve()


def _verify_pack(
    root: Path, *, canonical_name: bool, gate_evidence_dir: str | Path
) -> VerifiedModelPack:
    validated = validate_model_pack_manifest(
        read_manifest_json(root / MANIFEST_FILENAME)
    )
    if canonical_name and root.name != validated["model_pack_id"]:
        raise ModelPackError("model-pack directory name must equal its model_pack_id")
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

    if validated["provenance_type"] == "maintainer_final_v2":
        anchored = load_maintainer_final_digests(gate_evidence_dir)
        for task, spec in validated["artifacts"].items():
            if spec["sha256"] != anchored[task]:
                raise ModelPackError(
                    f"{task} artifact is not the selected final artifact recorded "
                    "by the accepted gate evidence"
                )
    return VerifiedModelPack(
        root=root,
        manifest=validated,
        artifact_paths=artifact_paths,
    )


def preflight_model_pack(
    pack_dir: str | Path,
    *,
    gate_evidence_dir: str | Path = DEFAULT_GATE_EVIDENCE_DIR,
) -> VerifiedModelPack:
    """Verify trust metadata, paths, hashes, and runtime without deserializing.

    A ``maintainer_final_v2`` pack must also match the selected-artifact digests
    in the accepted gate evidence, and every pack must live in a directory named
    by its ``model_pack_id``.
    """
    return _verify_pack(
        _require_pack_dir(pack_dir),
        canonical_name=True,
        gate_evidence_dir=gate_evidence_dir,
    )


def verify_staged_model_pack(
    stage_dir: str | Path,
    *,
    gate_evidence_dir: str | Path = DEFAULT_GATE_EVIDENCE_DIR,
) -> VerifiedModelPack:
    """Preflight a registrar's private staging directory before its rename.

    Identical to ``preflight_model_pack`` except that a staging directory is not
    yet named by its ``model_pack_id``. Code that deserializes must call
    ``preflight_model_pack`` instead.
    """
    return _verify_pack(
        _require_pack_dir(stage_dir),
        canonical_name=False,
        gate_evidence_dir=gate_evidence_dir,
    )


def describe_model_pack(verified: VerifiedModelPack) -> list[str]:
    """Human-readable summary of a preflighted pack for command-line output."""
    manifest = verified.manifest
    runtime = manifest["runtime"]
    libraries = ", ".join(
        f"{name.replace('_', '-')} {version}"
        for name, version in sorted(runtime["libraries"].items())
    )
    lines = [
        f"Model pack ID: {manifest['model_pack_id']}",
        f"Pack directory: {verified.root}",
        f"Provenance: {manifest['provenance_type']}",
        (
            f"Trust: {manifest['trust']['method']} acknowledged at "
            f"{manifest['trust']['acknowledged_at_utc']}"
        ),
        f"Created at (UTC): {manifest['created_at_utc']}",
        f"Runtime: Python {runtime['python']}, {libraries}",
        f"Creation config SHA-256: {manifest['creation_config_sha256']}",
    ]
    for task, spec in manifest["artifacts"].items():
        lines.append(
            f"{task}: {spec['filename']}, {spec['size_bytes']} bytes, "
            f"sha256 {spec['sha256']}"
        )
    if manifest["provenance_type"] == "maintainer_final_v2":
        lines.append(
            "Trust anchor: matches the accepted v2.1 explanation-gate evidence"
        )
    return lines
