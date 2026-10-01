import ast
import copy
import hashlib
import json
import os
import pickle
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import pytest

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from cids.workbench import model_pack, registration  # noqa: E402
from cids.workbench.model_pack import (  # noqa: E402
    DEFAULT_REGISTRATION_POLICY,
    EXPECTED_CONTRACTS_BASE,
    EXPECTED_REGISTRATION_POLICY_SHA256,
    EXPECTED_RUNTIME,
    ModelPackError,
    compute_model_pack_id,
    load_registration_policy,
    preflight_model_pack,
    registration_policy_sha256,
    validate_registration_policy,
)
from cids.workbench.registration import (  # noqa: E402
    STAGING_PREFIX,
    ModelPackRegistrationError,
    build_maintainer_final_manifest,
    default_pack_root,
    register_maintainer_final_pack,
)

PHRASE = "REGISTER_TRUSTED_LOCAL_V2_MODEL_PACK"
FIXED_TIME = datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)
SOURCE_BYTES = {
    "binary": b"stand-in binary artifact bytes",
    "multiclass": b"stand-in multiclass artifact bytes, longer",
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def pinned_host_runtime(monkeypatch):
    monkeypatch.setattr(
        model_pack, "current_runtime", lambda: copy.deepcopy(EXPECTED_RUNTIME)
    )


@pytest.fixture
def sources(tmp_path):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    paths = {}
    for task, value in SOURCE_BYTES.items():
        paths[task] = source_dir / f"{task}-hist_gradient_boosting.joblib"
        paths[task].write_bytes(value)
    return paths


@pytest.fixture
def anchored(monkeypatch):
    """Stand in for the accepted gate's digests with the controlled fake bytes."""
    digests = {task: sha256(value) for task, value in SOURCE_BYTES.items()}
    monkeypatch.setattr(
        model_pack, "load_maintainer_final_digests", lambda *_args: dict(digests)
    )
    return digests


@pytest.fixture
def pack_root(tmp_path):
    return tmp_path / "model-packs"


@pytest.fixture
def ready(pinned_host_runtime, anchored):
    return anchored


def register(sources, pack_root, **overrides):
    options = {
        "confirmation": PHRASE,
        "pack_root": pack_root,
        "clock": lambda: FIXED_TIME,
    }
    options.update(overrides)
    return register_maintainer_final_pack(
        sources["binary"], sources["multiclass"], **options
    )


def entries(path):
    return sorted(item.name for item in path.iterdir()) if path.exists() else []


def test_registers_pack_with_exact_manifest_and_final_preflight(
    sources, pack_root, ready
):
    verified = register(sources, pack_root)

    manifest = verified.manifest
    assert verified.root == pack_root / manifest["model_pack_id"]
    assert entries(pack_root) == [manifest["model_pack_id"]]
    assert entries(verified.root) == [
        "binary.joblib",
        "manifest.json",
        "multiclass.joblib",
    ]
    assert manifest["provenance_type"] == "maintainer_final_v2"
    assert manifest["runtime"] == EXPECTED_RUNTIME
    assert manifest["contracts"] == {
        **EXPECTED_CONTRACTS_BASE,
        "artifact_version": "unsw-nb15-final-supervised-v1",
    }
    assert manifest["creation_config_sha256"] == EXPECTED_REGISTRATION_POLICY_SHA256
    assert manifest["trust"] == {
        "acknowledged": True,
        "method": "explicit_local_cli",
        "acknowledged_at_utc": "2026-10-01T09:30:00+00:00",
    }
    assert manifest["created_at_utc"] == "2026-10-01T09:30:00+00:00"
    for task, value in SOURCE_BYTES.items():
        spec = manifest["artifacts"][task]
        assert spec == {
            "task": task,
            "filename": f"{task}.joblib",
            "sha256": sha256(value),
            "size_bytes": len(value),
        }
        assert verified.artifact_paths[task].read_bytes() == value
        assert stat.S_IMODE(verified.artifact_paths[task].stat().st_mode) == 0o444
    on_disk = json.loads((verified.root / "manifest.json").read_text())
    assert on_disk == manifest
    assert compute_model_pack_id(on_disk) == verified.root.name
    assert preflight_model_pack(verified.root).manifest == manifest


def test_registration_never_deserializes_an_artifact(
    sources, pack_root, ready, monkeypatch
):
    def refuse(*_args, **_kwargs):
        raise AssertionError("registration must not deserialize artifacts")

    monkeypatch.setattr(joblib, "load", refuse)
    monkeypatch.setattr(pickle, "load", refuse)
    monkeypatch.setattr(pickle, "loads", refuse)
    # A real pickle whose loading would be observable must still only be copied.
    payload = pickle.dumps({"loaded": True})
    sources["binary"].write_bytes(payload)
    monkeypatch.setattr(
        model_pack,
        "load_maintainer_final_digests",
        lambda *_args: {**ready, "binary": sha256(payload)},
    )

    verified = register(sources, pack_root)

    assert verified.artifact_paths["binary"].read_bytes() == payload


def test_registration_sources_reference_no_deserializer_or_prediction():
    modules = (
        REPO_ROOT / "src/cids/workbench/registration.py",
        REPO_ROOT / "src/cids/workbench/model_pack.py",
        REPO_ROOT / "src/cids/experiments/register_model_pack.py",
        REPO_ROOT / "src/cids/experiments/preflight_model_pack.py",
    )
    for path in modules:
        tree = ast.parse(path.read_text())
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        deserializers = {
            (node.value.id, node.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        } & {
            (module, name)
            for module in ("joblib", "pickle")
            for name in ("load", "loads", "Unpickler")
        }
        predictions = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in {"predict", "predict_proba"}
        }
        assert not imported & {"pickle", "shap", "streamlit", "skops"}, path
        assert not deserializers and not predictions, path


@pytest.mark.parametrize(
    "confirmation",
    [
        "",
        "register_trusted_local_v2_model_pack",
        f"{PHRASE} ",
        "TRUST_LOCAL_V2_ARTIFACTS",
    ],
)
def test_refuses_missing_or_incorrect_confirmation(
    sources, pack_root, ready, confirmation
):
    with pytest.raises(ModelPackRegistrationError, match="refusing to register"):
        register(sources, pack_root, confirmation=confirmation)
    assert not pack_root.exists()


def test_refuses_missing_source(sources, pack_root, ready):
    sources["multiclass"].unlink()

    with pytest.raises(ModelPackRegistrationError, match="does not exist"):
        register(sources, pack_root)
    assert not pack_root.exists()


def test_refuses_symlinked_source(sources, pack_root, ready, tmp_path):
    link = tmp_path / "linked.joblib"
    link.symlink_to(sources["binary"])

    with pytest.raises(ModelPackRegistrationError, match="binary source .* symlink"):
        register({**sources, "binary": link}, pack_root)
    assert not pack_root.exists()


def test_refuses_source_reached_through_symlinked_directory(
    sources, pack_root, ready, tmp_path
):
    linked_dir = tmp_path / "linked-sources"
    linked_dir.symlink_to(sources["binary"].parent, target_is_directory=True)

    with pytest.raises(ModelPackRegistrationError, match="resolves through a symlink"):
        register({**sources, "binary": linked_dir / sources["binary"].name}, pack_root)


def test_refuses_directory_source(sources, pack_root, ready, tmp_path):
    directory = tmp_path / "not-a-file.joblib"
    directory.mkdir()

    with pytest.raises(ModelPackRegistrationError, match="not a regular file"):
        register({**sources, "multiclass": directory}, pack_root)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires named pipes")
def test_refuses_fifo_source_without_blocking(sources, pack_root, ready, tmp_path):
    fifo = tmp_path / "pipe.joblib"
    os.mkfifo(fifo)

    with pytest.raises(ModelPackRegistrationError, match="not a regular file"):
        register({**sources, "binary": fifo}, pack_root)


def test_refuses_same_file_for_both_tasks(sources, pack_root, ready, tmp_path):
    with pytest.raises(ModelPackRegistrationError, match="same file"):
        register({**sources, "multiclass": sources["binary"]}, pack_root)

    hard_link = tmp_path / "hard-link.joblib"
    os.link(sources["binary"], hard_link)
    with pytest.raises(ModelPackRegistrationError, match="same file"):
        register({**sources, "multiclass": hard_link}, pack_root)
    assert not pack_root.exists()


@pytest.mark.parametrize("task", ["binary", "multiclass"])
def test_refuses_source_digest_not_recorded_by_gate(sources, pack_root, ready, task):
    sources[task].write_bytes(SOURCE_BYTES[task] + b"tampered")

    with pytest.raises(
        ModelPackRegistrationError,
        match=f"{task} source SHA-256 .* does not match the selected artifact",
    ):
        register(sources, pack_root)
    assert not pack_root.exists()


def test_real_gate_anchor_refuses_stand_in_artifacts(
    sources, pack_root, pinned_host_runtime
):
    with pytest.raises(ModelPackRegistrationError, match="binary source SHA-256"):
        register(sources, pack_root)
    assert not pack_root.exists()


@pytest.mark.parametrize(
    "tamper",
    ["report", "checksums", "missing"],
)
def test_refuses_when_gate_evidence_fails_verification(
    sources, pack_root, pinned_host_runtime, evidence_repo, tamper
):
    gate_dir = evidence_repo / "results/v2.1"
    if tamper == "report":
        report = gate_dir / "shap-gate-selected-v2.json"
        report.write_bytes(report.read_bytes().replace(b"4f0364ce", b"4f0364cf"))
    elif tamper == "checksums":
        (gate_dir / "SHA256SUMS").write_text(
            "0" * 64 + "  shap-gate-selected-v2.json\n"
        )
    else:
        shutil.rmtree(gate_dir)

    with pytest.raises(ModelPackError, match="trust anchor failed verification"):
        register(sources, pack_root, gate_evidence_dir=gate_dir)
    assert not pack_root.exists()


def test_refuses_host_runtime_mismatch(sources, pack_root, anchored, monkeypatch):
    host = copy.deepcopy(EXPECTED_RUNTIME)
    host["python"] = "3.12.13"
    monkeypatch.setattr(model_pack, "current_runtime", lambda: host)

    with pytest.raises(ModelPackRegistrationError, match="current runtime"):
        register(sources, pack_root)
    assert not pack_root.exists()


def test_refuses_symlinked_pack_root(sources, ready, tmp_path):
    real = tmp_path / "real-packs"
    real.mkdir(mode=0o700)
    link = tmp_path / "linked-packs"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(ModelPackRegistrationError, match="traverses a symlink"):
        register(sources, link)
    with pytest.raises(ModelPackRegistrationError, match="traverses a symlink"):
        register(sources, link / "nested")
    assert entries(real) == []


def test_refuses_pack_root_that_is_a_file(sources, ready, tmp_path):
    target = tmp_path / "packs-file"
    target.write_text("not a directory")

    with pytest.raises(ModelPackRegistrationError, match="not a directory"):
        register(sources, target)


def test_refuses_pack_root_writable_by_other_users(sources, ready, pack_root):
    pack_root.mkdir()
    pack_root.chmod(0o777)

    with pytest.raises(ModelPackRegistrationError, match="writable by other users"):
        register(sources, pack_root)
    assert entries(pack_root) == []


@pytest.fixture
def disposable_repo(tmp_path, monkeypatch):
    """A stand-in repository root, so a regression cannot write into the real one."""
    repo = tmp_path / "repo"
    (repo / "results").mkdir(parents=True)
    monkeypatch.setattr(registration, "REPO_ROOT", repo)
    return repo


def test_refuses_pack_root_inside_repository_outside_artifacts(
    sources, ready, disposable_repo
):
    target = disposable_repo / "results" / "model-packs"

    with pytest.raises(ModelPackRegistrationError, match="ignored artifacts/"):
        register(sources, target)
    with pytest.raises(ModelPackRegistrationError, match="ignored artifacts/"):
        register(sources, disposable_repo)
    assert entries(disposable_repo) == ["results"]
    assert entries(disposable_repo / "results") == []


def test_accepts_pack_root_under_repository_artifacts(sources, ready, disposable_repo):
    verified = register(sources, disposable_repo / "artifacts" / "v2.1" / "model-packs")

    assert verified.root.parent == disposable_repo / "artifacts/v2.1/model-packs"


def test_refuses_case_variant_repository_path_outside_artifacts(
    sources, ready, disposable_repo
):
    variant = Path(str(disposable_repo).swapcase())
    if not variant.exists() or not os.path.samefile(variant, disposable_repo):
        pytest.skip("requires a case-insensitive filesystem")

    with pytest.raises(ModelPackRegistrationError, match="ignored artifacts/"):
        register(sources, variant / "results" / "model-packs")
    assert entries(disposable_repo / "results") == []


def test_creates_new_pack_root_privately(sources, ready, pack_root):
    register(sources, pack_root / "nested")

    assert stat.S_IMODE((pack_root / "nested").stat().st_mode) == 0o700


def test_refuses_registering_the_same_artifacts_twice(sources, pack_root, ready):
    first = register(sources, pack_root)
    later = FIXED_TIME + timedelta(hours=1)

    with pytest.raises(ModelPackRegistrationError, match="already registered"):
        register(sources, pack_root, clock=lambda: later)
    assert entries(pack_root) == [first.root.name]


def test_refuses_existing_final_pack_name(sources, pack_root, ready):
    manifest = build_maintainer_final_manifest(
        artifacts={
            task: (sha256(value), len(value)) for task, value in SOURCE_BYTES.items()
        },
        acknowledged_at_utc=FIXED_TIME.isoformat(),
        created_at_utc=FIXED_TIME.isoformat(),
        creation_config_sha256=EXPECTED_REGISTRATION_POLICY_SHA256,
    )
    pack_root.mkdir(mode=0o700)
    occupied = pack_root / manifest["model_pack_id"]
    occupied.write_text("occupied")

    with pytest.raises(ModelPackRegistrationError, match="model pack already exists"):
        register(sources, pack_root)
    assert occupied.read_text() == "occupied"
    assert entries(pack_root) == [occupied.name]


@pytest.mark.parametrize(
    "leftover",
    [f"{STAGING_PREFIX}abc123", "a" * 64],
)
def test_refuses_partial_or_conflicting_destination(
    sources, pack_root, ready, leftover
):
    pack_root.mkdir(mode=0o700)
    (pack_root / leftover).mkdir()

    with pytest.raises(
        ModelPackRegistrationError,
        match="interrupted registration|partial or unreadable",
    ):
        register(sources, pack_root)
    assert entries(pack_root) == [leftover]


def test_refuses_symlink_inside_pack_root(sources, pack_root, ready, tmp_path):
    pack_root.mkdir(mode=0o700)
    (pack_root / "elsewhere").symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(ModelPackRegistrationError, match="contains a symlink"):
        register(sources, pack_root)


def test_ignores_unrelated_files_in_pack_root(sources, pack_root, ready):
    pack_root.mkdir(mode=0o700)
    (pack_root / ".DS_Store").write_bytes(b"finder metadata")

    verified = register(sources, pack_root)

    assert entries(pack_root) == sorted([".DS_Store", verified.root.name])


def test_model_pack_id_is_deterministic_and_canonical():
    options = {
        "artifacts": {"binary": ("a" * 64, 10), "multiclass": ("b" * 64, 20)},
        "acknowledged_at_utc": "2026-10-01T09:30:00+00:00",
        "created_at_utc": "2026-10-01T09:30:01+00:00",
        "creation_config_sha256": EXPECTED_REGISTRATION_POLICY_SHA256,
    }
    first = build_maintainer_final_manifest(**options)
    second = build_maintainer_final_manifest(**options)
    reordered = json.loads(json.dumps(first, sort_keys=False))
    reordered = dict(reversed(list(reordered.items())))
    payload = {key: value for key, value in first.items() if key != "model_pack_id"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    assert first["model_pack_id"] == second["model_pack_id"]
    assert first["model_pack_id"] == hashlib.sha256(canonical).hexdigest()
    assert compute_model_pack_id(reordered) == first["model_pack_id"]
    changed = copy.deepcopy(options)
    changed["artifacts"]["binary"] = ("a" * 64, 11)
    assert (
        build_maintainer_final_manifest(**changed)["model_pack_id"]
        != first["model_pack_id"]
    )


def test_creation_config_digest_binds_the_committed_registration_policy(tmp_path):
    policy = load_registration_policy()
    raw = json.loads(DEFAULT_REGISTRATION_POLICY.read_text())
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()

    assert registration_policy_sha256(policy) == EXPECTED_REGISTRATION_POLICY_SHA256
    assert hashlib.sha256(canonical).hexdigest() == EXPECTED_REGISTRATION_POLICY_SHA256
    assert policy["trust"]["confirmation_phrase"] == PHRASE
    assert default_pack_root(policy) == REPO_ROOT / "artifacts/v2.1/model-packs"

    edited = copy.deepcopy(raw)
    edited["trust"]["confirmation_phrase"] = "YES"
    copy_path = tmp_path / "policy.json"
    copy_path.write_text(json.dumps(edited))
    with pytest.raises(ModelPackError, match="differs from the pinned v1 policy"):
        load_registration_policy(copy_path)


@pytest.mark.parametrize(
    ("section", "key", "value", "message"),
    [
        ("trust_anchor", "gate_report_sha256", "0" * 64, "accepted gate evidence"),
        ("pack", "default_root", "results/packs", "ignored artifacts/"),
        ("pack", "default_root", "artifacts/../results", "ignored artifacts/"),
        ("pack", "artifact_filenames", {"binary": "b", "multiclass": "m"}, "filenames"),
        ("trust", "method", "browser_upload", "trust method"),
    ],
)
def test_registration_policy_rejects_contract_drift(section, key, value, message):
    policy = json.loads(DEFAULT_REGISTRATION_POLICY.read_text())
    policy[section][key] = value

    with pytest.raises(ModelPackError, match=message):
        validate_registration_policy(policy)


def test_failure_before_rename_removes_only_this_operations_staging(
    sources, pack_root, ready, monkeypatch, tmp_path
):
    pack_root.mkdir(mode=0o700)
    unrelated = pack_root / "notes.txt"
    unrelated.write_text("keep")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.joblib").write_bytes(b"keep")
    seen = []

    def fail(stage_dir, **_kwargs):
        seen.append(Path(stage_dir))
        raise ModelPackError("injected staging failure")

    monkeypatch.setattr(model_pack, "verify_staged_model_pack", fail)

    with pytest.raises(ModelPackError, match="injected staging failure"):
        register(sources, pack_root)
    assert seen and seen[0].parent == pack_root
    assert seen[0].name.startswith(STAGING_PREFIX)
    assert entries(pack_root) == ["notes.txt"]
    assert unrelated.read_text() == "keep"
    assert (outside / "keep.joblib").read_bytes() == b"keep"


def test_cleanup_never_deletes_unexpected_staging_content(
    sources, pack_root, ready, monkeypatch
):
    def fail(stage_dir, **_kwargs):
        (Path(stage_dir) / "unexpected.txt").write_text("not ours")
        raise ModelPackError("injected staging failure")

    monkeypatch.setattr(model_pack, "verify_staged_model_pack", fail)

    with pytest.raises(ModelPackRegistrationError, match="need manual inspection"):
        register(sources, pack_root)
    (staging,) = pack_root.iterdir()
    assert staging.name.startswith(STAGING_PREFIX)
    assert entries(staging) == ["unexpected.txt"]


def test_failure_after_rename_rolls_back_the_final_pack(
    sources, pack_root, ready, monkeypatch
):
    def fail(pack_dir, **_kwargs):
        assert Path(pack_dir).parent == pack_root
        raise ModelPackError("injected final preflight failure")

    monkeypatch.setattr(model_pack, "preflight_model_pack", fail)

    with pytest.raises(ModelPackError, match="injected final preflight failure"):
        register(sources, pack_root)
    assert entries(pack_root) == []


def test_interrupted_registration_leaves_no_partial_pack(
    sources, pack_root, ready, monkeypatch
):
    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(registration, "_write_new_file", interrupt)

    with pytest.raises(KeyboardInterrupt):
        register(sources, pack_root)
    assert entries(pack_root) == []


def test_lost_race_for_final_name_never_touches_the_winner(
    sources, pack_root, ready, monkeypatch
):
    real_mkdir = os.mkdir

    def competitor_wins(path, *args, **kwargs):
        if Path(path).parent == pack_root and not Path(path).name.startswith("."):
            real_mkdir(path, 0o700)
            (Path(path) / "winner.txt").write_text("other registration")
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(registration.os, "mkdir", competitor_wins)

    with pytest.raises(ModelPackRegistrationError, match="model pack already exists"):
        register(sources, pack_root)
    (winner,) = pack_root.iterdir()
    assert entries(winner) == ["winner.txt"]


def test_interrupt_during_final_preflight_rolls_back(
    sources, pack_root, ready, monkeypatch
):
    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(model_pack, "preflight_model_pack", interrupt)

    with pytest.raises(KeyboardInterrupt):
        register(sources, pack_root)
    assert entries(pack_root) == []


def test_rollback_falls_back_to_removing_own_files_when_rename_back_fails(
    sources, pack_root, ready, monkeypatch
):
    real_rename = os.rename

    def refuse_rename_back(source, destination):
        if Path(destination).name.startswith(STAGING_PREFIX):
            raise OSError("injected rename failure")
        return real_rename(source, destination)

    def fail(*_args, **_kwargs):
        raise ModelPackError("injected final preflight failure")

    monkeypatch.setattr(registration.os, "rename", refuse_rename_back)
    monkeypatch.setattr(model_pack, "preflight_model_pack", fail)

    with pytest.raises(ModelPackError, match="injected final preflight failure"):
        register(sources, pack_root)
    assert entries(pack_root) == []


def test_interrupt_reports_paths_left_for_inspection(
    sources, pack_root, ready, monkeypatch, capsys
):
    def interrupt(stage_dir, **_kwargs):
        (Path(stage_dir) / "unexpected.txt").write_text("not ours")
        raise KeyboardInterrupt

    monkeypatch.setattr(model_pack, "verify_staged_model_pack", interrupt)

    with pytest.raises(KeyboardInterrupt):
        register(sources, pack_root)
    (staging,) = pack_root.iterdir()
    assert str(staging) in capsys.readouterr().err
    assert entries(staging) == ["unexpected.txt"]


def test_source_changed_after_verification_is_refused(
    sources, pack_root, ready, monkeypatch
):
    original = registration._prepare_pack_root

    def change_source_then_prepare(path):
        sources["multiclass"].write_bytes(b"swapped after hashing")
        return original(path)

    monkeypatch.setattr(registration, "_prepare_pack_root", change_source_then_prepare)

    with pytest.raises(ModelPackRegistrationError, match="changed during registration"):
        register(sources, pack_root)
    assert entries(pack_root) == []


def _git_ignores(relative):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", relative],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return result.returncode == 0


@pytest.mark.skipif(
    shutil.which("git") is None or not (REPO_ROOT / ".git").exists(),
    reason="requires a git checkout",
)
def test_generated_packs_and_staging_directories_are_ignored_by_git():
    pack_id = "c" * 64
    for relative in (
        f"artifacts/v2.1/model-packs/{pack_id}/manifest.json",
        f"artifacts/v2.1/model-packs/{pack_id}/binary.joblib",
        f"artifacts/v2.1/model-packs/{pack_id}/multiclass.joblib",
        f"artifacts/v2.1/model-packs/{STAGING_PREFIX}x1y2/manifest.json",
    ):
        assert _git_ignores(relative), relative


def test_registration_services_do_not_import_streamlit_or_shap():
    code = (
        "import sys; sys.path.insert(0, 'src');"
        "import cids.workbench.registration, cids.experiments.register_model_pack;"
        "import cids.experiments.preflight_model_pack;"
        "print(sorted(m for m in ('streamlit', 'shap', 'altair') if m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "[]"


def test_dashboard_sources_do_not_import_registration_or_model_pack():
    for path in (REPO_ROOT / "src/cids/dashboard").rglob("*.py"):
        tree = ast.parse(path.read_text())
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
                modules |= {f"{node.module}.{alias.name}" for alias in node.names}
        assert not any(
            "registration" in name or "model_pack" in name for name in modules
        ), path


def test_dashboard_import_graph_excludes_registration_and_model_pack():
    pytest.importorskip("streamlit")
    pytest.importorskip("altair")
    code = (
        "import sys, pkgutil, importlib; sys.path.insert(0, 'src');"
        "import cids.dashboard as d;"
        "[importlib.import_module(m.name) for m in "
        "pkgutil.walk_packages(d.__path__, 'cids.dashboard.')];"
        "print(sorted(m for m in ('cids.workbench.registration',"
        " 'cids.workbench.model_pack') if m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "[]"
