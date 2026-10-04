#!/usr/bin/env python3
"""Build and verify the local image without mounting private host artifacts.

Requires Docker/Compose. Failures propagate; this never publishes an image.
"""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "cids-workbench:v2.1-local"
PROJECT = "cids-phase5-verify"


def run(*args, capture=False):
    result = subprocess.run(args, cwd=ROOT, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def restricted_args():
    return ["--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=134217728,mode=1777",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--init", "--cpus", "2", "--memory", "2g", "--pids-limit", "128"]


def main():
    os.chdir(ROOT)
    print(run("docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}", capture=True), flush=True)
    # Export the *actual* filtered BuildKit context and check every file against
    # the explicit review allowlist, not a homemade ignore-rule simulator.
    with tempfile.TemporaryDirectory(prefix="cids-context-") as temporary:
        directory = Path(temporary)
        audit = directory / "Dockerfile.audit"
        audit.write_text("FROM scratch\nCOPY . /\n")
        output = directory / "context"
        run("docker", "build", "-f", str(audit), "--output", f"type=local,dest={output}", ".")
        allowed = {line[1:] for line in (ROOT / ".dockerignore").read_text().splitlines()
                   if line.startswith("!") and not line.endswith("/")}
        actual = {str(p.relative_to(output)) for p in output.rglob("*") if p.is_file()}
        assert actual == allowed, f"Context differs from explicit allowlist: {actual ^ allowed}"
        assert all(not p.is_symlink() for p in output.rglob("*"))
        for relative in actual:
            assert (output / relative).read_bytes() == (ROOT / relative).read_bytes()
        print(f"Build context audit passed: {len(actual)} reviewed files, no extras", flush=True)
    run("docker", "build", "-t", IMAGE, ".")
    probe = '''
import errno, importlib.metadata as metadata, os, pathlib, platform
from cids.workbench.model_pack import current_runtime, EXPECTED_RUNTIME
assert os.geteuid() == 10001 and os.getegid() == 10001
assert platform.python_version() == "3.12.14"
assert current_runtime() == EXPECTED_RUNTIME
assert not list(pathlib.Path("/app/artifacts").rglob("*.joblib"))
assert not pathlib.Path("/app/dataset/unsw-nb15/raw").exists()
assert not pathlib.Path("/app/.git").exists()
assert not pathlib.Path("/app/tests").exists()
assert pathlib.Path("/app/samples/synthetic-features-v1.csv").is_file()
for lock in ("requirements-container.txt", "requirements-dashboard.txt", "requirements-workbench.txt", "requirements-reproduction.txt"):
    for line in pathlib.Path("/app", lock).read_text().splitlines():
        if "==" in line and not line.startswith("#"):
            name, version = line.split("==")
            assert metadata.version(name) == version, name
# Exercise EROFS as well as immutable app permissions.
for location in ("/cids-write-probe", "/app/cids-write-probe"):
    try:
        pathlib.Path(location).write_text("fail")
    except OSError as error:
        assert error.errno in (errno.EROFS, errno.EACCES)
    else:
        raise AssertionError("root filesystem was writable")
pathlib.Path("/tmp/cids-write-probe").write_text("ephemeral")
from cids.workbench.catalog import load_catalog
from cids.workbench.synthetic_sample import load_sample
assert load_catalog().official is not None
assert len(load_sample(pathlib.Path("/app"))[0]) > 0
print("Non-root, exact locks, frozen evidence/sample and read-only probes passed")
'''
    run("docker", "run", "--rm", *restricted_args(), "--entrypoint", "python", IMAGE, "-c", probe)
    run("docker", "run", "--rm", *restricted_args(), "--entrypoint", "python", IMAGE, "-m", "pip", "check")
    # Test-only code/anchors enter solely through this read-only test mount.
    suites = sorted({str(p.relative_to(ROOT)) for pattern in (
        "test_workbench*.py", "test_dashboard*.py", "test_phase4*.py",
        "test_explanation_resources.py", "test_prepare_explanation_resources.py",
        "test_synthetic_sample.py", "test_container*.py")
        for p in (ROOT / "tests").glob(pattern)})
    # Never read host __pycache__: cached pytest code retains Mac source paths,
    # defeating inspect.getsource inside Linux/Streamlit AppTest.
    with tempfile.TemporaryDirectory(prefix="cids-container-tests-") as temporary:
        test_dir = Path(temporary)
        # Public synthetic test code only; Linux UID 10001 needs traversal.
        test_dir.chmod(0o755)
        for source in (ROOT / "tests").glob("*.py"):
            (test_dir / source.name).write_bytes(source.read_bytes())
        run("docker", "run", "--rm", *restricted_args(),
            "--mount", f"type=bind,src={test_dir},dst=/app/tests,readonly",
            "--entrypoint", "python", IMAGE, "-m", "pytest", "-q", "-rs",
            "-p", "no:cacheprovider", *suites)
    compose = ["docker", "compose", "-p", PROJECT, "-f", "compose.yaml"]
    # Ignore ambient host pack/resource and UID variables for evidence verification.
    environment = dict(os.environ)
    for key in ("CIDS_MODEL_PACK_ID", "CIDS_EXPLANATION_RESOURCE_ID", "CIDS_UID", "CIDS_GID"):
        environment.pop(key, None)
    def comp(*args, capture=False):
        result = subprocess.run([*compose, *args], cwd=ROOT, env=environment, check=True,
                                text=True, stdout=subprocess.PIPE if capture else None)
        return result.stdout.strip() if capture else None
    try:
        comp("up", "-d", "--wait", "--wait-timeout", "90", "--no-build")
        identifier = comp("ps", "-q", "workbench", capture=True)
        state = json.loads(run("docker", "inspect", identifier, capture=True))[0]
        host = state["HostConfig"]
        assert host["ReadonlyRootfs"] and host["CapDrop"] == ["ALL"]
        assert "no-new-privileges:true" in host["SecurityOpt"]
        assert host["Init"] and host["PidsLimit"] == 128
        assert host["Memory"] == 2 * 1024**3 and host["NanoCpus"] == 2_000_000_000
        assert state["NetworkSettings"]["Ports"]["8501/tcp"] == [{"HostIp": "127.0.0.1", "HostPort": "8501"}]
        assert state["State"]["Health"]["Status"] == "healthy"
        comp("exec", "-T", "workbench", "python", "-m", "cids.dashboard.healthcheck")
        # A real host-side probe proves this published mapping is reachable.
        from urllib.request import ProxyHandler, build_opener
        with build_opener(ProxyHandler({})).open("http://127.0.0.1:8501/_stcore/health", timeout=5) as response:
            assert response.read(16).strip() == b"ok"
        start = time.monotonic()
        comp("stop", "--timeout", "15")
        state = json.loads(run("docker", "inspect", identifier, capture=True))[0]["State"]
        assert state["ExitCode"] == 0 and not state["OOMKilled"]
        assert time.monotonic() - start < 20
        print("Loopback publication, health and graceful shutdown passed", flush=True)
    finally:
        comp("down", "--timeout", "15")


if __name__ == "__main__":
    main()
