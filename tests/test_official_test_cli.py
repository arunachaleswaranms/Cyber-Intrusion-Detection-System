import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.datasets.unsw_nb15 import (  # noqa: E402
    ATTACK_FAMILY_COLUMN,
    BINARY_LABEL_COLUMN,
    ID_COLUMN,
    NUMERIC_FEATURES,
    REQUIRED_COLUMNS,
    SCHEMA_VERSION,
)
from cids.experiments.evaluate_official_test import (  # noqa: E402
    OfficialTestRunError,
    main,
)
from cids.selection import DEFAULT_MODEL_SELECTION  # noqa: E402


def row(row_id, duration, family="normal", label=0, proto="tcp"):
    values = {column: 0 for column in NUMERIC_FEATURES}
    values.update(
        {
            ID_COLUMN: row_id,
            "dur": duration,
            "proto": proto,
            "service": "-",
            "state": "FIN",
            ATTACK_FAMILY_COLUMN: family,
            BINARY_LABEL_COLUMN: label,
        }
    )
    return values


def write_partition(path, rows):
    pd.DataFrame(rows).loc[:, REQUIRED_COLUMNS].to_csv(path, index=False)


def file_spec(path, role):
    with path.open("rb") as stream:
        records = sum(1 for _ in stream) - 1
    return {
        "role": role,
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "records": records,
        "columns": len(REQUIRED_COLUMNS),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def prepare_cli_inputs(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    train = data_dir / "train.csv"
    test = data_dir / "test.csv"
    training_rows = [row(index, index) for index in range(1, 11)]
    training_rows.extend(
        row(index, index, "generic", 1, "udp") for index in range(11, 21)
    )
    training_rows.extend(
        row(index, index, "exploits", 1, "udp") for index in range(21, 31)
    )
    write_partition(train, training_rows)
    write_partition(
        test,
        [
            row(1, 101),
            row(2, 102),
            row(3, 103, "generic", 1, "udp"),
            row(4, 104, "generic", 1, "udp"),
            row(5, 105, "exploits", 1, "udp"),
            row(6, 106, "exploits", 1, "udp"),
        ],
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "dataset": "synthetic-test",
                "schema_version": SCHEMA_VERSION,
                "files": [file_spec(train, "train"), file_spec(test, "test")],
            }
        ),
        encoding="utf-8",
    )
    reproduction = tmp_path / "reproduced-selection.json"
    shutil.copyfile(DEFAULT_MODEL_SELECTION, reproduction)
    return data_dir, manifest, reproduction


def test_cli_requires_exact_confirmation_before_accessing_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_official_test",
            "--data-dir",
            str(tmp_path / "missing-data"),
            "--reproduction-selection",
            str(tmp_path / "missing-selection.json"),
            "--output-dir",
            str(tmp_path / "output"),
            "--confirm",
            "YES",
        ],
    )

    with pytest.raises(OfficialTestRunError, match="confirmation must be exactly"):
        main()


def test_cli_rejects_committed_selection_as_reproduction(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_official_test",
            "--data-dir",
            str(tmp_path / "missing-data"),
            "--reproduction-selection",
            str(DEFAULT_MODEL_SELECTION),
            "--output-dir",
            str(tmp_path / "output"),
            "--confirm",
            "EVALUATE_OFFICIAL_TEST_ONCE",
        ],
    )

    with pytest.raises(OfficialTestRunError, match="clean validation rerun"):
        main()


def test_guarded_cli_writes_both_results_and_refuses_same_output_twice(
    tmp_path, monkeypatch
):
    data_dir, manifest, reproduction = prepare_cli_inputs(tmp_path)
    output = tmp_path / "final-output"
    arguments = [
        "evaluate_official_test",
        "--data-dir",
        str(data_dir),
        "--manifest",
        str(manifest),
        "--reproduction-selection",
        str(reproduction),
        "--output-dir",
        str(output),
        "--confirm",
        "EVALUATE_OFFICIAL_TEST_ONCE",
    ]
    monkeypatch.setattr(sys, "argv", arguments)

    assert main() == 0
    report = json.loads((output / "official_test_results.json").read_text())
    state = json.loads((output / "run_state.json").read_text())
    assert report["official_test_status"] == "evaluated_once"
    assert set(report["tasks"]) == {"binary", "multiclass"}
    assert set(report["dataset_files"]) == {"train", "test"}
    assert report["tasks"]["binary"]["split_report"]["task"] == "binary"
    assert state["status"] == "completed"
    assert (output / "binary-hist_gradient_boosting.joblib").is_file()
    assert (output / "multiclass-hist_gradient_boosting.joblib").is_file()

    with pytest.raises(OfficialTestRunError, match="already exists"):
        main()
