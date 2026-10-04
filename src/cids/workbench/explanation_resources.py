"""Bounded, digest-bound non-executable resources; no model/SHAP import.

Resources are local CLI outputs, anchored by a startup resource digest. They
cannot establish trustworthy provenance for an arbitrary browser upload.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from cids.datasets.unsw_nb15 import ATTACK_FAMILIES, FEATURE_COLUMNS, SCHEMA_VERSION
from cids.workbench.config import load_workbench_config, workbench_config_sha256
from cids.workbench.contracts import parse_inference_csv
from cids.workbench.evidence import load_frozen_evidence
from cids.workbench.integrity import reject_duplicate_keys

RESOURCE_ENV = "CIDS_EXPLANATION_RESOURCE_ID"
RESOURCE_ROOT = Path("artifacts/v2.1/explanation-resources")
VERSION = "cids-explanation-resources-v1"
MAX_MANIFEST_BYTES = 32 * 1024
MAX_BACKGROUND_BYTES = 1024 * 1024
MAX_GLOBAL_BYTES = 32 * 1024
GLOBAL_POLICY = {"method": "source_feature_permutation", "partition": "prepared_validation",
                 "sample_limit": 256, "seed": 42, "repeats": 3,
                 "scoring": "macro_f1_all_estimator_classes_zero_division_0"}


class ResourceError(ValueError):
    """Missing, incompatible or invalid resource (UI uses fixed safe text)."""


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def resource_id(manifest):
    return digest_bytes(canonical({k: v for k, v in manifest.items() if k != "resource_id"}))


def controlled_directory(repo_root, identifier):
    if not isinstance(identifier, str) or re.fullmatch(r"[0-9a-f]{64}", identifier) is None:
        raise ResourceError("one configured resource digest is required")
    root = Path(repo_root).resolve()
    candidate = root
    for part in (*RESOURCE_ROOT.parts, identifier):
        candidate /= part
        if candidate.is_symlink():
            raise ResourceError("symlink in resource path")
    return candidate


def read_regular_bytes(path, maximum, spec=None):
    """Read/hash the same bounded descriptor bytes, rejecting links and FIFOs."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(descriptor)
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ResourceError("resource file is not bounded and regular")
        chunks, remaining = [], maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after, named = os.fstat(descriptor), os.stat(path, follow_symlinks=False)
        for info in (after, named):
            if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != identity:
                raise ResourceError("resource changed during read")
        if len(data) != before.st_size or len(data) > maximum:
            raise ResourceError("resource read exceeds bound")
        if spec is not None and (len(data) != spec["size_bytes"] or digest_bytes(data) != spec["sha256"]):
            raise ResourceError("resource digest mismatch")
        return data
    finally:
        os.close(descriptor)


def strict_json(data):
    value = json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                       parse_constant=lambda _: (_ for _ in ()).throw(ResourceError("nonfinite JSON")))
    if not isinstance(value, dict):
        raise ResourceError("resource JSON must be an object")
    return value


def frozen_provenance(task):
    evidence = load_frozen_evidence()
    split = evidence.report["tasks"][task]["split_report"]
    return {"dataset_files": evidence.report["dataset_files"],
            "schema_version": SCHEMA_VERSION, "split_policy_version": split["split_policy_version"],
            "seed": split["seed"], "validation_fraction": split["validation_fraction"],
            "training_scope": "prepared_train", "training_rows": split["prepared_rows"]["train"],
            "training_id_sha256": split["id_sha256"]["train"],
            "validation_rows": split["prepared_rows"]["validation"],
            "validation_id_sha256": split["id_sha256"]["validation"],
            "sampling": "cids-shap-compatibility-gate-v2_target_stratified_hash_rank"}


@dataclass(frozen=True)
class ExplanationResources:
    resource_id: str
    manifest: dict
    backgrounds: dict
    global_reliance: dict


def _file_spec(spec, filename, maximum):
    if (not isinstance(spec, dict) or set(spec) != {"filename", "sha256", "size_bytes", "rows"}
            or spec["filename"] != filename or type(spec["size_bytes"]) is not int
            or not 0 < spec["size_bytes"] <= maximum or type(spec["rows"]) is not int
            or not 0 < spec["rows"] <= 256 or not isinstance(spec["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", spec["sha256"]) is None):
        raise ResourceError("resource file specification is invalid")


def validate_global(value, task, rows, classes):
    expected = {"task", "policy", "sample_rows", "class_labels", "baseline_score", "features"}
    if (set(value) != expected or value["task"] != task or value["policy"] != GLOBAL_POLICY
            or type(value["sample_rows"]) is not int or value["sample_rows"] != rows
            or canonical(value["class_labels"]) != canonical(list(classes))
            or not isinstance(value["features"], list) or len(value["features"]) != 42):
        raise ResourceError("global reliance provenance mismatch")
    numbers = [value["baseline_score"]]
    for name, entry in zip(FEATURE_COLUMNS, value["features"]):
        if set(entry) != {"feature", "mean_score_decrease", "std_score_decrease"} or entry["feature"] != name:
            raise ResourceError("global reliance feature schema mismatch")
        numbers.extend([entry["mean_score_decrease"], entry["std_score_decrease"]])
        if entry["std_score_decrease"] < 0:
            raise ResourceError("invalid global standard deviation")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in numbers):
        raise ResourceError("global reliance contains nonfinite values")
    if not 0 <= value["baseline_score"] <= 1:
        raise ResourceError("invalid global baseline score")


def load_resources(repo_root, identifier, pack_manifest):
    """Validate all resources before use, without deserialization or SHAP."""
    try:
        from cids.workbench.model_pack import current_runtime, EXPECTED_RUNTIME

        if current_runtime() != EXPECTED_RUNTIME or pack_manifest["runtime"] != EXPECTED_RUNTIME:
            raise ResourceError("resource runtime is incompatible")
        root = controlled_directory(repo_root, identifier)
        manifest = strict_json(read_regular_bytes(root / "manifest.json", MAX_MANIFEST_BYTES))
        if set(manifest) != {"manifest_version", "resource_id", "model_pack_id", "artifacts", "runtime", "schema", "policy_sha256", "tasks"}:
            raise ResourceError("resource manifest fields mismatch")
        policy = load_workbench_config()
        if (manifest["manifest_version"] != VERSION or manifest["resource_id"] != identifier
                or resource_id(manifest) != identifier or manifest["model_pack_id"] != pack_manifest["model_pack_id"]
                or manifest["artifacts"] != pack_manifest["artifacts"] or manifest["runtime"] != pack_manifest["runtime"]
                or manifest["schema"] != list(FEATURE_COLUMNS)
                or manifest["policy_sha256"] != workbench_config_sha256(policy)
                or set(manifest["tasks"]) != {"binary", "multiclass"}):
            raise ResourceError("resource binding is incompatible")
        backgrounds, global_reliance = {}, {}
        for task in ("binary", "multiclass"):
            entry = manifest["tasks"][task]
            if set(entry) != {"provenance", "background", "global", "background_sample_id_sha256", "global_sample_id_sha256"} or entry["provenance"] != frozen_provenance(task):
                raise ResourceError("resource development provenance mismatch")
            for name in ("background_sample_id_sha256", "global_sample_id_sha256"):
                if name == "global_sample_id_sha256" and entry["global"] is None:
                    if entry[name] is not None:
                        raise ResourceError("unexpected global sample")
                elif not isinstance(entry[name], str) or re.fullmatch(r"[0-9a-f]{64}", entry[name]) is None:
                    raise ResourceError("invalid sample identity")
            spec = entry["background"]
            _file_spec(spec, f"{task}-background.csv", MAX_BACKGROUND_BYTES)
            if spec["rows"] > policy["explainability"]["background_rows"]:
                raise ResourceError("background exceeds policy")
            data = read_regular_bytes(root / spec["filename"], MAX_BACKGROUND_BYTES, spec)
            frame = parse_inference_csv(data).frame
            # Optional IDs/labels/event times never belong in runtime resources.
            header = pd.read_csv(io.BytesIO(data), nrows=0).columns.tolist()
            if header != list(FEATURE_COLUMNS) or len(frame) != spec["rows"]:
                raise ResourceError("background feature schema mismatch")
            backgrounds[task] = frame.loc[:, FEATURE_COLUMNS]
            if entry["global"] is not None:
                spec = entry["global"]
                _file_spec(spec, f"{task}-global.json", MAX_GLOBAL_BYTES)
                value = strict_json(read_regular_bytes(root / spec["filename"], MAX_GLOBAL_BYTES, spec))
                classes = (0, 1) if task == "binary" else tuple(sorted(ATTACK_FAMILIES))
                validate_global(value, task, spec["rows"], classes)
                global_reliance[task] = value
        return ExplanationResources(identifier, manifest, backgrounds, global_reliance)
    except ResourceError:
        raise
    except Exception as exc:
        raise ResourceError("explanation resources are unavailable or invalid") from exc
