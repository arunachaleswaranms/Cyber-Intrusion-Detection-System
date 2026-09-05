"""Verify local dataset files against a pinned manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cids.datasets.unsw_nb15 import REQUIRED_COLUMNS, SCHEMA_VERSION

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[3] / "dataset" / "unsw-nb15" / "manifest.json"
)


class DatasetVerificationError(ValueError):
    """Raised when a local dataset does not match its manifest."""


@dataclass(frozen=True)
class VerifiedFile:
    role: str
    path: Path
    size_bytes: int
    records: int
    sha256: str


def load_manifest(path: str | Path) -> dict:
    manifest_path = Path(path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DatasetVerificationError(f"manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise DatasetVerificationError(f"invalid JSON manifest: {manifest_path}") from exc

    if manifest.get("manifest_version") != 1:
        raise DatasetVerificationError("unsupported manifest_version")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise DatasetVerificationError(
            f"manifest schema must be {SCHEMA_VERSION!r}"
        )
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise DatasetVerificationError("manifest files must be a non-empty list")
    return manifest


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        try:
            return next(csv.reader(stream))
        except StopIteration as exc:
            raise DatasetVerificationError(f"empty dataset file: {path}") from exc


def count_records(path: Path) -> int:
    with path.open("rb") as stream:
        line_count = sum(1 for _ in stream)
    return max(0, line_count - 1)


def verify_file(data_dir: Path, spec: dict) -> VerifiedFile:
    required_keys = {
        "role", "filename", "size_bytes", "records", "columns", "sha256"
    }
    missing_keys = sorted(required_keys - set(spec))
    if missing_keys:
        raise DatasetVerificationError(f"manifest file entry missing {missing_keys}")

    filename = spec["filename"]
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise DatasetVerificationError(f"unsafe manifest filename: {filename!r}")
    path = data_dir / filename
    if not path.is_file():
        raise DatasetVerificationError(f"dataset file not found: {path}")

    actual_size = path.stat().st_size
    if actual_size != spec["size_bytes"]:
        raise DatasetVerificationError(
            f"size mismatch for {filename}: expected {spec['size_bytes']}, "
            f"found {actual_size}"
        )

    actual_digest = sha256_file(path)
    if actual_digest != spec["sha256"]:
        raise DatasetVerificationError(
            f"SHA-256 mismatch for {filename}: expected {spec['sha256']}, "
            f"found {actual_digest}"
        )

    header = read_header(path)
    if len(header) != spec["columns"]:
        raise DatasetVerificationError(
            f"column-count mismatch for {filename}: expected {spec['columns']}, "
            f"found {len(header)}"
        )
    if header != list(REQUIRED_COLUMNS):
        raise DatasetVerificationError(
            f"header mismatch for {filename} and schema {SCHEMA_VERSION}"
        )

    actual_records = count_records(path)
    if actual_records != spec["records"]:
        raise DatasetVerificationError(
            f"record-count mismatch for {filename}: expected {spec['records']}, "
            f"found {actual_records}"
        )

    return VerifiedFile(
        role=spec["role"],
        path=path,
        size_bytes=actual_size,
        records=actual_records,
        sha256=actual_digest,
    )


def verify_dataset(
    data_dir: str | Path, manifest_path: str | Path = DEFAULT_MANIFEST
) -> list[VerifiedFile]:
    manifest = load_manifest(manifest_path)
    directory = Path(data_dir)
    roles = [spec.get("role") for spec in manifest["files"]]
    if len(set(roles)) != len(roles):
        raise DatasetVerificationError("manifest file roles must be unique")
    return [verify_file(directory, spec) for spec in manifest["files"]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="Directory containing CSV files")
    parser.add_argument(
        "--manifest", default=str(DEFAULT_MANIFEST), help="Dataset manifest path"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        verified = verify_dataset(args.data_dir, args.manifest)
    except DatasetVerificationError as exc:
        print(f"Verification failed: {exc}")
        return 1

    for item in verified:
        print(
            f"Verified {item.role}: {item.path.name} "
            f"({item.records} records, {item.size_bytes} bytes, "
            f"sha256={item.sha256})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
