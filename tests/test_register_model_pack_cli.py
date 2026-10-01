import copy
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from cids.experiments import preflight_model_pack as preflight_cli  # noqa: E402
from cids.experiments import register_model_pack as register_cli  # noqa: E402
from cids.workbench import model_pack  # noqa: E402
from cids.workbench.model_pack import EXPECTED_RUNTIME  # noqa: E402

PHRASE = "REGISTER_TRUSTED_LOCAL_V2_MODEL_PACK"
SOURCE_BYTES = {"binary": b"cli binary bytes", "multiclass": b"cli family bytes"}


@pytest.fixture
def cli_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(
        model_pack, "current_runtime", lambda: copy.deepcopy(EXPECTED_RUNTIME)
    )
    digests = {}
    paths = {}
    for task, value in SOURCE_BYTES.items():
        paths[task] = tmp_path / f"{task}-hist_gradient_boosting.joblib"
        paths[task].write_bytes(value)
        digests[task] = hashlib.sha256(value).hexdigest()
    monkeypatch.setattr(
        model_pack, "load_maintainer_final_digests", lambda *_args: dict(digests)
    )
    return paths


def arguments(paths, pack_root, confirm=PHRASE):
    return [
        "--binary-artifact",
        str(paths["binary"]),
        "--multiclass-artifact",
        str(paths["multiclass"]),
        "--pack-root",
        str(pack_root),
        "--confirm",
        confirm,
    ]


def test_cli_registers_and_preflights_a_pack(cli_sources, tmp_path, capsys):
    pack_root = tmp_path / "packs"

    assert register_cli.main(arguments(cli_sources, pack_root)) == 0
    output = capsys.readouterr().out
    (pack_dir,) = pack_root.iterdir()

    assert "Model-pack registration: PASSED" in output
    assert f"Model pack ID: {pack_dir.name}" in output
    assert "no artifact was deserialized" in output
    assert "Inference: not available until v2.1 Phase 3B" in output

    assert preflight_cli.main(["--pack-dir", str(pack_dir)]) == 0
    output = capsys.readouterr().out
    assert "Model-pack preflight: PASSED" in output
    assert "Trust anchor: matches the accepted v2.1 explanation-gate evidence" in output


def test_cli_refuses_wrong_confirmation_with_exit_code_two(
    cli_sources, tmp_path, capsys
):
    pack_root = tmp_path / "packs"

    with pytest.raises(SystemExit) as exit_info:
        register_cli.main(arguments(cli_sources, pack_root, confirm="yes"))

    assert exit_info.value.code == 2
    assert "Model-pack registration: REFUSED" in capsys.readouterr().err
    assert not pack_root.exists()


def test_cli_requires_confirmation_argument(cli_sources, tmp_path):
    argv = arguments(cli_sources, tmp_path / "packs")[:-2]

    with pytest.raises(SystemExit) as exit_info:
        register_cli.main(argv)

    assert exit_info.value.code == 2
    assert not (tmp_path / "packs").exists()


def test_preflight_cli_fails_tampered_pack(cli_sources, tmp_path, capsys):
    pack_root = tmp_path / "packs"
    register_cli.main(arguments(cli_sources, pack_root))
    (pack_dir,) = pack_root.iterdir()
    binary = pack_dir / "binary.joblib"
    binary.chmod(0o644)
    binary.write_bytes(b"cli binary byteZ")

    with pytest.raises(SystemExit) as exit_info:
        preflight_cli.main(["--pack-dir", str(pack_dir)])

    assert exit_info.value.code == 2
    error = capsys.readouterr().err
    assert "Model-pack preflight: FAILED" in error
    assert "binary artifact SHA-256 mismatch" in error


@pytest.mark.parametrize(
    "module",
    ["cids.experiments.register_model_pack", "cids.experiments.preflight_model_pack"],
)
def test_cli_modules_run_as_scripts(module):
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        cwd=REPO_ROOT,
        env={"PYTHONPATH": "src", "PATH": ""},
        capture_output=True,
        text=True,
        check=True,
    )

    assert "deserializ" in result.stdout
