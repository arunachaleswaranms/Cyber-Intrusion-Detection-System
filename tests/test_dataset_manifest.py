import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.datasets.unsw_nb15 import REQUIRED_COLUMNS, SCHEMA_VERSION  # noqa: E402
from cids.datasets.verify_manifest import (  # noqa: E402
    DatasetVerificationError,
    verify_dataset,
)


def write_csv(path, header=REQUIRED_COLUMNS):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(header)
        writer.writerow([0] * len(header))


def file_spec(path, role):
    return {
        "role": role,
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "records": 1,
        "columns": len(REQUIRED_COLUMNS),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def create_manifest(tmp_path, specs):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "dataset": "test",
                "schema_version": SCHEMA_VERSION,
                "files": specs,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_verifies_exact_files(tmp_path):
    train = tmp_path / "train.csv"
    test = tmp_path / "test.csv"
    write_csv(train)
    write_csv(test)
    manifest = create_manifest(
        tmp_path, [file_spec(train, "train"), file_spec(test, "test")]
    )

    results = verify_dataset(tmp_path, manifest)

    assert [result.role for result in results] == ["train", "test"]
    assert all(result.records == 1 for result in results)


def test_rejects_tampered_file(tmp_path):
    dataset = tmp_path / "train.csv"
    write_csv(dataset)
    manifest = create_manifest(tmp_path, [file_spec(dataset, "train")])
    dataset.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(DatasetVerificationError, match="size mismatch"):
        verify_dataset(tmp_path, manifest)


def test_rejects_wrong_header_even_when_integrity_values_match(tmp_path):
    dataset = tmp_path / "train.csv"
    wrong_header = [*REQUIRED_COLUMNS[:-1], "wrong_label"]
    write_csv(dataset, wrong_header)
    manifest = create_manifest(tmp_path, [file_spec(dataset, "train")])

    with pytest.raises(DatasetVerificationError, match="header mismatch"):
        verify_dataset(tmp_path, manifest)


def test_rejects_path_traversal_in_manifest(tmp_path):
    dataset = tmp_path / "train.csv"
    write_csv(dataset)
    spec = file_spec(dataset, "train")
    spec["filename"] = "../train.csv"
    manifest = create_manifest(tmp_path, [spec])

    with pytest.raises(DatasetVerificationError, match="unsafe manifest filename"):
        verify_dataset(tmp_path, manifest)
