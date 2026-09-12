import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.workbench.evidence import (  # noqa: E402
    CHECKSUM_FILENAME,
    DEFAULT_EVIDENCE_DIR,
    EvidenceError,
    RESULT_FILENAME,
    load_frozen_evidence,
)


def test_loads_frozen_evidence_without_dataset_or_model_artifacts():
    evidence = load_frozen_evidence()

    assert evidence.report["official_test_status"] == "evaluated_once"
    assert evidence.state["status"] == "completed"
    assert set(evidence.report["tasks"]) == {"binary", "multiclass"}
    assert evidence.report["tasks"]["binary"]["official_test_metrics"][
        "false_positive_rate"
    ] == pytest.approx(0.26894594594594595)


def test_rejects_tampered_result_before_parsing(tmp_path):
    copied = tmp_path / "v2.0"
    shutil.copytree(DEFAULT_EVIDENCE_DIR, copied)
    with (copied / RESULT_FILENAME).open("ab") as stream:
        stream.write(b"\n")

    with pytest.raises(EvidenceError, match="SHA-256 mismatch"):
        load_frozen_evidence(copied)


def test_rejects_a_rewritten_checksum_file(tmp_path):
    copied = tmp_path / "v2.0"
    shutil.copytree(DEFAULT_EVIDENCE_DIR, copied)
    checksum = copied / CHECKSUM_FILENAME
    checksum.write_text(checksum.read_text().replace("302f", "0000"))

    with pytest.raises(EvidenceError, match="frozen v2.0 digests"):
        load_frozen_evidence(copied)


def test_rejects_symlinked_evidence_file(tmp_path):
    copied = tmp_path / "v2.0"
    shutil.copytree(DEFAULT_EVIDENCE_DIR, copied)
    result = copied / RESULT_FILENAME
    target = copied / "result-copy.json"
    result.rename(target)
    result.symlink_to(target.name)

    with pytest.raises(EvidenceError, match="regular non-symlink"):
        load_frozen_evidence(copied)
