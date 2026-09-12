import hashlib
import json
from pathlib import Path


RESULTS_DIR = Path(__file__).parents[1] / "results" / "v2.0"
RESULT_PATH = RESULTS_DIR / "official-test-results.json"
STATE_PATH = RESULTS_DIR / "run-state.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preserved_official_evidence_hashes_match_mac_transfer():
    assert _sha256(RESULT_PATH) == (
        "302f92c7dc83419959c6962fdfe3d5426bfb69aedab79fce8c3298b8b1dfbb9a"
    )
    assert _sha256(STATE_PATH) == (
        "c74d217b83c61818aebdd0c4ba42a737529496da829f370795e8131c26f42574"
    )


def test_official_report_and_completion_state_are_consistent():
    report = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    assert report["official_test_status"] == "evaluated_once"
    assert state["official_test_status"] == "evaluated_once"
    assert state["status"] == "completed"
    assert report["started_at_utc"] == state["started_at_utc"]
    assert report["completed_at_utc"] == state["completed_at_utc"]

    for key in (
        "experiment_config_sha256",
        "model_selection_sha256",
        "reproduction_selection_sha256",
        "final_protocol_sha256",
        "dataset_files",
    ):
        assert report[key] == state[key]

    assert set(report["tasks"]) == {"binary", "multiclass"}
    for task in ("binary", "multiclass"):
        result = report["tasks"][task]
        assert result["metadata"]["model_name"] == "hist_gradient_boosting"
        assert result["metadata"]["official_test_status"] == "evaluated_once"
        assert result["official_test_metrics"]["samples"] == 82_332
