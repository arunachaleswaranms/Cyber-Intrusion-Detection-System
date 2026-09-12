"""Read and validate immutable, non-executable v2.0 benchmark evidence."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

DEFAULT_EVIDENCE_DIR = Path(__file__).resolve().parents[3] / "results" / "v2.0"
RESULT_FILENAME = "official-test-results.json"
STATE_FILENAME = "run-state.json"
CHECKSUM_FILENAME = "SHA256SUMS"
EXPECTED_HASHES = {
    RESULT_FILENAME: "302f92c7dc83419959c6962fdfe3d5426bfb69aedab79fce8c3298b8b1dfbb9a",
    STATE_FILENAME: "c74d217b83c61818aebdd0c4ba42a737529496da829f370795e8131c26f42574",
}


class EvidenceError(ValueError):
    """Raised when frozen benchmark evidence fails integrity or semantics."""


@dataclass(frozen=True)
class FrozenEvidence:
    report: dict
    state: dict
    sha256: dict[str, str]
    evidence_dir: Path


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise EvidenceError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(f"evidence must be a regular non-symlink file: {path}")


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except FileNotFoundError as exc:
        raise EvidenceError(f"evidence file not found: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"invalid evidence JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"evidence JSON must be an object: {path}")
    return value


def _load_checksums(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, UnicodeDecodeError) as exc:
        raise EvidenceError(f"invalid checksum file: {path}") from exc
    for line in lines:
        parts = line.split()
        if len(parts) != 2 or parts[1] not in EXPECTED_HASHES:
            raise EvidenceError("checksum file contains an unsupported entry")
        digest, filename = parts
        if filename in values or len(digest) != 64:
            raise EvidenceError("checksum file is malformed")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise EvidenceError("checksum file contains a non-hex digest") from exc
        values[filename] = digest
    if values != EXPECTED_HASHES:
        raise EvidenceError("checksum file does not match the frozen v2.0 digests")
    return values


def _validate_semantics(report: dict, state: dict) -> None:
    if report.get("report_version") != "unsw-nb15-official-test-results-v1":
        raise EvidenceError("unsupported official result version")
    if report.get("official_test_status") != "evaluated_once":
        raise EvidenceError("official result is not the completed one-time run")
    if state.get("status") != "completed" or state.get("official_test_status") != (
        "evaluated_once"
    ):
        raise EvidenceError("official run state is not completed")
    for key in (
        "started_at_utc",
        "completed_at_utc",
        "dataset_files",
        "experiment_config_sha256",
        "model_selection_sha256",
        "reproduction_selection_sha256",
        "final_protocol_sha256",
    ):
        if report.get(key) != state.get(key):
            raise EvidenceError(f"official report and state disagree for {key}")
    tasks = report.get("tasks")
    if not isinstance(tasks, dict) or set(tasks) != {"binary", "multiclass"}:
        raise EvidenceError("official report must contain both frozen tasks")
    for task, result in tasks.items():
        if not isinstance(result, dict):
            raise EvidenceError(f"{task} result must be an object")
        metadata = result.get("metadata")
        metrics = result.get("official_test_metrics")
        if not isinstance(metadata, dict) or not isinstance(metrics, dict):
            raise EvidenceError(f"{task} result metadata or metrics are missing")
        if metadata.get("task") != task:
            raise EvidenceError(f"{task} artifact task metadata disagrees")
        if metadata.get("model_name") != "hist_gradient_boosting":
            raise EvidenceError(f"{task} frozen model is unexpected")
        if metadata.get("official_test_status") != "evaluated_once":
            raise EvidenceError(f"{task} artifact is not from the final run")
        if metrics.get("samples") != 82_332:
            raise EvidenceError(f"{task} official sample count is unexpected")
        for name in ("accuracy", "balanced_accuracy", "f1_macro", "f1_weighted"):
            value = metrics.get(name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise EvidenceError(f"{task} metric {name} is invalid")


def load_frozen_evidence(
    evidence_dir: str | Path = DEFAULT_EVIDENCE_DIR,
) -> FrozenEvidence:
    root = Path(evidence_dir)
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError(f"evidence directory is unavailable: {root}")
    paths = {
        RESULT_FILENAME: root / RESULT_FILENAME,
        STATE_FILENAME: root / STATE_FILENAME,
        CHECKSUM_FILENAME: root / CHECKSUM_FILENAME,
    }
    for path in paths.values():
        _require_regular_file(path)
    checksums = _load_checksums(paths[CHECKSUM_FILENAME])
    for filename, expected in checksums.items():
        actual = _sha256(paths[filename])
        if actual != expected:
            raise EvidenceError(f"SHA-256 mismatch for frozen evidence: {filename}")
    report = _load_json(paths[RESULT_FILENAME])
    state = _load_json(paths[STATE_FILENAME])
    _validate_semantics(report, state)
    return FrozenEvidence(
        report=report,
        state=state,
        sha256=dict(checksums),
        evidence_dir=root.resolve(),
    )
