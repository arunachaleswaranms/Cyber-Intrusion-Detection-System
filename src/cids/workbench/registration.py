"""Register the maintainer's trusted v2.0 final artifacts as a local model pack.

Registration is a deliberate command-line act. It checks two source files
against the selected-artifact digests in the accepted v2.1 gate evidence,
copies them under app-owned names into a private staging directory beside the
pack root, writes the manifest, preflights the result, and only then renames
the staging directory to its ``model_pack_id``. It never deserializes an
artifact: joblib is pickle-based, and a matching digest does not make a pickle
safe. Validating the deserialized object belongs to the later loading step.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import sys
import tempfile
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from cids.final_evaluation import FINAL_MODEL_ARTIFACT_VERSION
from cids.workbench import model_pack
from cids.workbench.gate_evidence import DEFAULT_GATE_EVIDENCE_DIR
from cids.workbench.model_pack import (
    DEFAULT_REGISTRATION_POLICY,
    EXPECTED_CONTRACTS_BASE,
    EXPECTED_RUNTIME,
    MANIFEST_FILENAME,
    MODEL_PACK_MANIFEST_VERSION,
    PACK_ARTIFACT_FILENAMES,
    TRUST_METHOD,
    ModelPackError,
    VerifiedModelPack,
    compute_model_pack_id,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_PREFIX = ".registering-"
TASKS = ("binary", "multiclass")
_CHUNK_BYTES = 1024 * 1024
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


class ModelPackRegistrationError(ModelPackError):
    """Raised when registration is refused; no trusted-looking pack remains."""


@dataclass(frozen=True)
class _Source:
    task: str
    path: Path
    stream: BinaryIO
    identity: tuple[int, int]
    size_bytes: int
    sha256: str


def default_pack_root(policy: dict) -> Path:
    return REPO_ROOT / policy["pack"]["default_root"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(moment: datetime) -> str:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ModelPackRegistrationError("registration clock must be timezone-aware")
    return moment.astimezone(timezone.utc).isoformat()


def _absolute(path: str | Path) -> Path:
    # abspath normalizes without following symlinks, unlike Path.resolve().
    return Path(os.path.abspath(path))


def _hash_stream(stream: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(_CHUNK_BYTES):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _open_source(task: str, path: str | Path, max_bytes: int) -> _Source:
    """Open a source as a regular, non-symlink file and hash its bytes."""
    absolute = _absolute(path)
    try:
        before = os.lstat(absolute)
    except FileNotFoundError as exc:
        raise ModelPackRegistrationError(
            f"{task} source artifact does not exist: {absolute}"
        ) from exc
    if stat.S_ISLNK(before.st_mode):
        raise ModelPackRegistrationError(
            f"{task} source artifact is a symlink: {absolute}"
        )
    if not stat.S_ISREG(before.st_mode):
        raise ModelPackRegistrationError(
            f"{task} source artifact is not a regular file: {absolute}"
        )
    if absolute.resolve() != absolute:
        raise ModelPackRegistrationError(
            f"{task} source artifact path resolves through a symlink: {absolute} "
            f"-> {absolute.resolve()}; pass the resolved path if you trust it"
        )
    descriptor = os.open(absolute, os.O_RDONLY | _O_NOFOLLOW | _O_NONBLOCK)
    stream = os.fdopen(descriptor, "rb")
    try:
        opened = os.fstat(stream.fileno())
        identity = (opened.st_dev, opened.st_ino)
        if not stat.S_ISREG(opened.st_mode) or identity != (
            before.st_dev,
            before.st_ino,
        ):
            raise ModelPackRegistrationError(
                f"{task} source artifact changed while being opened: {absolute}"
            )
        if not 0 < opened.st_size <= max_bytes:
            raise ModelPackRegistrationError(
                f"{task} source artifact size {opened.st_size} is outside "
                f"1..{max_bytes} bytes"
            )
        digest, size = _hash_stream(stream)
        if size != opened.st_size:
            raise ModelPackRegistrationError(
                f"{task} source artifact changed while being read: {absolute}"
            )
    except BaseException:
        stream.close()
        raise
    return _Source(task, absolute, stream, identity, size, digest)


def _outside_ignored_artifacts(root: Path, existing: Path) -> bool:
    """Whether ``root`` is in the repository but not under ``artifacts/``.

    Containment is decided by filesystem identity, not by comparing strings,
    because macOS volumes are usually case-insensitive.
    """
    for ancestor in (existing, *existing.parents):
        if os.path.samefile(ancestor, REPO_ROOT):
            return root.relative_to(ancestor).parts[:1] != ("artifacts",)
    return False


def _prepare_pack_root(pack_root: str | Path) -> Path:
    """Return an existing or new private pack root that no symlink redirects."""
    root = _absolute(pack_root)
    existing = root
    while not os.path.lexists(existing):
        existing = existing.parent
    if existing.resolve() != existing:
        raise ModelPackRegistrationError(
            f"pack root path traverses a symlink: {existing} -> "
            f"{existing.resolve()}; pass the resolved path if you trust it"
        )
    if _outside_ignored_artifacts(root, existing):
        raise ModelPackRegistrationError(
            "a pack root inside the repository must be under the ignored "
            f"artifacts/ directory: {root}"
        )
    if existing != root:
        root.mkdir(mode=0o700, parents=True)
    mode = os.lstat(root).st_mode
    if not stat.S_ISDIR(mode):
        raise ModelPackRegistrationError(f"pack root is not a directory: {root}")
    if root.resolve() != root:
        raise ModelPackRegistrationError(f"pack root path traverses a symlink: {root}")
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ModelPackRegistrationError(
            f"pack root is writable by other users; run chmod go-w {root}"
        )
    return root


def _refuse_conflicts(root: Path, digests: dict[str, str]) -> None:
    """Refuse partial registrations, symlinks, and an existing identical pack."""
    for entry in sorted(root.iterdir()):
        if entry.name.startswith(STAGING_PREFIX):
            raise ModelPackRegistrationError(
                f"pack root contains an interrupted registration: {entry}; "
                "inspect it and remove it manually"
            )
        if entry.is_symlink():
            raise ModelPackRegistrationError(f"pack root contains a symlink: {entry}")
        if not entry.is_dir():
            continue
        try:
            manifest = model_pack.read_manifest_json(entry / MANIFEST_FILENAME)
        except ModelPackError as exc:
            raise ModelPackRegistrationError(
                f"pack root contains a partial or unreadable pack: {entry}; "
                "inspect it and remove it manually"
            ) from exc
        artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else None
        if not isinstance(artifacts, dict) or not all(
            isinstance(artifacts.get(task), dict) for task in TASKS
        ):
            raise ModelPackRegistrationError(
                f"pack root contains a partial or unreadable pack: {entry}; "
                "inspect it and remove it manually"
            )
        if {task: artifacts[task].get("sha256") for task in TASKS} == digests:
            raise ModelPackRegistrationError(
                f"these artifacts are already registered as {entry.name}"
            )


def build_maintainer_final_manifest(
    *,
    artifacts: dict[str, tuple[str, int]],
    acknowledged_at_utc: str,
    created_at_utc: str,
    creation_config_sha256: str,
) -> dict:
    """Build and validate a v1 manifest from ``task -> (sha256, size_bytes)``."""
    manifest = {
        "manifest_version": MODEL_PACK_MANIFEST_VERSION,
        "provenance_type": "maintainer_final_v2",
        "created_at_utc": created_at_utc,
        "trust": {
            "acknowledged": True,
            "method": TRUST_METHOD,
            "acknowledged_at_utc": acknowledged_at_utc,
        },
        "runtime": copy.deepcopy(EXPECTED_RUNTIME),
        "contracts": {
            **EXPECTED_CONTRACTS_BASE,
            "artifact_version": FINAL_MODEL_ARTIFACT_VERSION,
        },
        "artifacts": {
            task: {
                "task": task,
                "filename": PACK_ARTIFACT_FILENAMES[task],
                "sha256": artifacts[task][0],
                "size_bytes": artifacts[task][1],
            }
            for task in TASKS
        },
        "creation_config_sha256": creation_config_sha256,
    }
    manifest["model_pack_id"] = compute_model_pack_id(manifest)
    return model_pack.validate_model_pack_manifest(manifest)


def _write_new_file(path: Path, data: bytes) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.chmod(path, 0o444)


def _copy_verified(source: _Source, destination: Path) -> None:
    """Copy from the already-open source, re-hashing exactly the bytes written."""
    source.stream.seek(0)
    digest = hashlib.sha256()
    size = 0
    descriptor = os.open(
        destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as output:
        while chunk := source.stream.read(_CHUNK_BYTES):
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        output.flush()
        os.fsync(output.fileno())
    if (digest.hexdigest(), size) != (source.sha256, source.size_bytes):
        raise ModelPackRegistrationError(
            f"{source.task} source artifact changed during registration: "
            f"{source.path}"
        )
    os.chmod(destination, 0o444)


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_staging(staging: Path) -> None:
    """Remove only the files registration creates, then the empty directory.

    The manifest goes first, so a partial remainder can never pass preflight.
    """
    for name in (MANIFEST_FILENAME, *PACK_ARTIFACT_FILENAMES.values()):
        candidate = staging / name
        if candidate.is_symlink() or candidate.is_file():
            candidate.unlink()
    staging.rmdir()


def _roll_back(
    staging: Path, final: Path, *, claimed: bool, published: bool
) -> list[Path]:
    """Undo this operation's own paths; return any that need manual inspection."""
    leftovers: list[Path] = []
    if published:
        try:
            os.rename(final, staging)
        except OSError:
            try:
                _remove_staging(final)
            except OSError:
                leftovers.append(final)
            return leftovers
    elif claimed:
        try:
            final.rmdir()
        except OSError:
            leftovers.append(final)
    try:
        _remove_staging(staging)
    except OSError:
        leftovers.append(staging)
    return leftovers


def _publish(
    root: Path,
    sources: dict[str, _Source],
    manifest: dict,
    gate_evidence_dir: str | Path,
) -> VerifiedModelPack:
    final = root / manifest["model_pack_id"]
    staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=root))
    claimed = published = False
    try:
        for task, source in sources.items():
            _copy_verified(source, staging / PACK_ARTIFACT_FILENAMES[task])
        _write_new_file(
            staging / MANIFEST_FILENAME,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        _fsync_directory(staging)
        model_pack.verify_staged_model_pack(
            staging, gate_evidence_dir=gate_evidence_dir
        )
        try:
            # Claim the final name exclusively; the rename then replaces only
            # this empty placeholder, never an existing pack.
            os.mkdir(final, 0o700)
        except FileExistsError as exc:
            raise ModelPackRegistrationError(
                f"model pack already exists: {final}"
            ) from exc
        claimed = True
        os.rename(staging, final)
        published = True
        _fsync_directory(root)
        return model_pack.preflight_model_pack(
            final, gate_evidence_dir=gate_evidence_dir
        )
    except BaseException as exc:
        leftovers = _roll_back(staging, final, claimed=claimed, published=published)
        if leftovers:
            paths = ", ".join(str(path) for path in leftovers)
            message = (
                "registration was rolled back but these paths need manual "
                f"inspection: {paths}"
            )
            if isinstance(exc, Exception):
                raise ModelPackRegistrationError(f"{exc}; {message}") from exc
            print(message, file=sys.stderr)
        raise


def register_maintainer_final_pack(
    binary_artifact: str | Path,
    multiclass_artifact: str | Path,
    *,
    confirmation: str,
    pack_root: str | Path | None = None,
    policy_path: str | Path = DEFAULT_REGISTRATION_POLICY,
    gate_evidence_dir: str | Path = DEFAULT_GATE_EVIDENCE_DIR,
    clock: Callable[[], datetime] = _utc_now,
) -> VerifiedModelPack:
    """Register the selected v2.0 final artifacts without deserializing them."""
    policy = model_pack.load_registration_policy(policy_path)
    if confirmation != policy["trust"]["confirmation_phrase"]:
        raise ModelPackRegistrationError(
            "refusing to register; pass --confirm "
            f"{policy['trust']['confirmation_phrase']} only for artifacts you "
            "created locally and trust"
        )
    acknowledged_at_utc = _utc_iso(clock())
    if model_pack.current_runtime() != EXPECTED_RUNTIME:
        raise ModelPackRegistrationError(
            "current runtime does not match the pinned model environment "
            "(Python 3.12.14 with requirements-workbench.txt)"
        )
    expected = model_pack.load_maintainer_final_digests(gate_evidence_dir)

    with ExitStack() as stack:
        sources: dict[str, _Source] = {}
        for task, path in zip(TASKS, (binary_artifact, multiclass_artifact)):
            source = _open_source(task, path, policy["pack"]["max_artifact_bytes"])
            stack.callback(source.stream.close)
            sources[task] = source
        if sources["binary"].identity == sources["multiclass"].identity:
            raise ModelPackRegistrationError(
                "binary and multiclass inputs are the same file"
            )
        for task, source in sources.items():
            if source.sha256 != expected[task]:
                raise ModelPackRegistrationError(
                    f"{task} source SHA-256 {source.sha256} does not match the "
                    "selected artifact recorded by the accepted gate "
                    f"({expected[task]})"
                )

        root = _prepare_pack_root(
            default_pack_root(policy) if pack_root is None else pack_root
        )
        _refuse_conflicts(root, expected)
        manifest = build_maintainer_final_manifest(
            artifacts={
                task: (source.sha256, source.size_bytes)
                for task, source in sources.items()
            },
            acknowledged_at_utc=acknowledged_at_utc,
            created_at_utc=_utc_iso(clock()),
            creation_config_sha256=model_pack.registration_policy_sha256(policy),
        )
        if os.path.lexists(root / manifest["model_pack_id"]):
            raise ModelPackRegistrationError(
                f"model pack already exists: {root / manifest['model_pack_id']}"
            )
        return _publish(root, sources, manifest, gate_evidence_dir)
