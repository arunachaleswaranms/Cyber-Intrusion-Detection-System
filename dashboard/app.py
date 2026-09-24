"""Streamlit entry point for the CIDS v2.1 evidence-first dashboard.

Run from the repository root so the local .streamlit/config.toml applies:

    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from cids.dashboard.app import main  # noqa: E402

main()
