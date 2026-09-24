"""Shared fail-closed primitives for reading pinned, non-executable evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path


class EvidenceError(ValueError):
    """Raised when frozen benchmark evidence fails integrity or semantics."""


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise EvidenceError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def require_regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(f"evidence must be a regular non-symlink file: {path}")


def load_json_object(path: Path) -> dict:
    """Parse strict UTF-8 JSON, rejecting duplicate keys and non-object roots."""
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except FileNotFoundError as exc:
        raise EvidenceError(f"evidence file not found: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"invalid evidence JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"evidence JSON must be an object: {path}")
    return value


def load_pinned_checksums(
    path: Path, expected: Mapping[str, str], *, release: str
) -> dict[str, str]:
    """Parse a SHA256SUMS file and require it to equal the pinned digests."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, UnicodeDecodeError) as exc:
        raise EvidenceError(f"invalid checksum file: {path}") from exc
    for line in lines:
        parts = line.split()
        if len(parts) != 2 or parts[1] not in expected:
            raise EvidenceError("checksum file contains an unsupported entry")
        digest, filename = parts
        if filename in values or len(digest) != 64:
            raise EvidenceError("checksum file is malformed")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise EvidenceError("checksum file contains a non-hex digest") from exc
        values[filename] = digest
    if values != dict(expected):
        raise EvidenceError(f"checksum file does not match the {release} digests")
    return values


def verify_pinned_files(root: Path, expected: Mapping[str, str]) -> None:
    """Hash each pinned file under ``root`` and fail on the first mismatch."""
    for filename, digest in expected.items():
        if sha256_file(root / filename) != digest:
            raise EvidenceError(f"SHA-256 mismatch for frozen evidence: {filename}")
