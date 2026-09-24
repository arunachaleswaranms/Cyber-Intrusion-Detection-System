import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
EVIDENCE_PATHS = (
    "results/v2.0",
    "results/v2.1",
    "configs",
    "dataset/unsw-nb15/manifest.json",
)


@pytest.fixture
def evidence_repo(tmp_path: Path) -> Path:
    """A disposable repository root holding copies of all committed evidence."""
    root = tmp_path / "repo"
    for relative in EVIDENCE_PATHS:
        source = REPO_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return root
