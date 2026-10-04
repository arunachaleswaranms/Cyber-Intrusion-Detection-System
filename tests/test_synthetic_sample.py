"""Committed synthetic sample contract and deterministic arithmetic construction."""
import sys
from pathlib import Path
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from cids.datasets.unsw_nb15 import FEATURE_COLUMNS, NUMERIC_FEATURES
from cids.workbench.synthetic_sample import load_sample, SAMPLE_FILE
from cids.workbench.contracts import parse_inference_csv

ROOT = Path(__file__).parents[1]


def test_sample_is_deterministic_feature_only_and_contract_valid():
    data, frame = load_sample(ROOT)
    rows = []
    for i in range(8):
        row = {name: ((i + 1) * (j + 1)) % 17 for j, name in enumerate(NUMERIC_FEATURES)}
        row.update(id=f"synthetic-{i + 1:04d}", dur=(i + 1) / 10, proto=("tcp", "udp")[i % 2], service="-", state="FIN", is_ftp_login=0, is_sm_ips_ports=0)
        rows.append(row)
    assert data == pd.DataFrame(rows).loc[:, ["id", *FEATURE_COLUMNS]].to_csv(index=False, lineterminator="\n").encode()
    result = parse_inference_csv(data)
    assert not result.has_binary_labels and not result.has_family_labels and not result.has_event_time
    assert list(frame.columns) == ["id", *FEATURE_COLUMNS] and len(frame) == 8


def test_replaced_sample_is_not_previewed(tmp_path):
    target = tmp_path / SAMPLE_FILE
    target.parent.mkdir()
    target.write_bytes(b"not the committed sample")
    with pytest.raises(ValueError):
        load_sample(tmp_path)
