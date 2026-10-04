"""Explicit Docker-only launch profile; host launches retain loopback guards."""
from __future__ import annotations

import os
from pathlib import Path
import sys

PROFILE_ENV = "CIDS_LAUNCH_PROFILE"
PROFILE = "container-v1"


def container_context() -> bool:
    # This is an explicit deployment profile, not proof of host port mapping.
    return (hasattr(os, "geteuid") and os.geteuid() != 0
            and Path("/.dockerenv").is_file())


def main() -> None:
    if not container_context():
        raise SystemExit("Container launch requires non-root Docker execution.")
    os.environ[PROFILE_ENV] = PROFILE
    os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run",
        "/app/dashboard/app.py", "--server.address", "0.0.0.0",
        "--server.port", "8501", "--browser.gatherUsageStats", "false",
        "--client.disableDataExport", "true", "--server.headless", "true"])


if __name__ == "__main__":
    main()
