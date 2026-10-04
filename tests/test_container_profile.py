"""The container exception never weakens ordinary host exposure checks."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from cids.dashboard import container, healthcheck


@pytest.mark.parametrize("uid,marker,expected", [(10001, True, True), (0, True, False), (501, False, False)])
def test_container_requires_nonroot_and_marker(monkeypatch, uid, marker, expected):
    monkeypatch.setattr(container.os, "geteuid", lambda: uid)
    monkeypatch.setattr(container.Path, "is_file", lambda self: marker)
    assert container.container_context() is expected


def test_container_launcher_refuses_host_before_exec(monkeypatch):
    monkeypatch.setattr(container, "container_context", lambda: False)
    monkeypatch.setattr(container.os, "execv", lambda *_: pytest.fail("must not exec"))
    with pytest.raises(SystemExit, match="non-root"):
        container.main()


def test_container_launcher_execs_with_explicit_controls(monkeypatch):
    monkeypatch.setattr(container, "container_context", lambda: True)
    called = []
    monkeypatch.setattr(container.os, "execv", lambda *args: called.append(args))
    monkeypatch.setenv(container.PROFILE_ENV, "other")
    container.main()
    assert container.os.environ[container.PROFILE_ENV] == container.PROFILE
    executable, args = called[0]
    assert executable == sys.executable
    assert args[args.index("--server.address") + 1] == "0.0.0.0"
    assert args[args.index("--browser.gatherUsageStats") + 1] == "false"
    assert args[args.index("--client.disableDataExport") + 1] == "true"


@pytest.mark.parametrize("address,profile,inside,telemetry,accepted", [
    ("0.0.0.0", None, True, False, False),
    ("0.0.0.0", container.PROFILE, False, False, False),
    ("0.0.0.0", "typo", True, False, False),
    ("0.0.0.0", container.PROFILE, True, False, True),
    ("", container.PROFILE, True, False, False),
    ("192.168.1.2", container.PROFILE, True, False, False),
    ("0.0.0.0", container.PROFILE, True, True, False),
    ("127.0.0.1", None, False, False, True),
])
def test_explicit_profile_is_narrow(address, profile, inside, telemetry, accepted):
    pytest.importorskip("streamlit")
    from cids.dashboard.app import exposure_problems
    assert (not exposure_problems(address, telemetry, launch_profile=profile, container=inside)) is accepted


@pytest.mark.parametrize("status,body,expected", [(200, b"ok", True), (200, b"ok\n", True), (503, b"ok", False), (200, b"ok but corrupted", False)])
def test_health_probe_bounds_and_content(monkeypatch, status, body, expected):
    response = MagicMock()
    response.status = status
    response.read.return_value = body
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = response
    monkeypatch.setattr(healthcheck, "build_opener", lambda *_: opener)
    assert healthcheck.healthy() is expected
    opener.open.assert_called_once_with("http://127.0.0.1:8501/_stcore/health", timeout=3)
    if status == 200:
        response.read.assert_called_once_with(16)
    else:
        response.read.assert_not_called()


def test_health_probe_failure_is_unhealthy(monkeypatch):
    opener = MagicMock()
    opener.open.side_effect = OSError("unavailable")
    monkeypatch.setattr(healthcheck, "build_opener", lambda *_: opener)
    assert not healthcheck.healthy()
