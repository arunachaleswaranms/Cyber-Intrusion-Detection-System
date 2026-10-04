"""Committed non-sensitive arithmetic sample; no model or dataset dependency."""
from pathlib import Path
from cids.workbench.contracts import parse_inference_csv
from cids.workbench.explanation_resources import read_regular_bytes, digest_bytes

SAMPLE_FILE = Path("samples/synthetic-features-v1.csv")
SAMPLE_SHA256 = "4acd413a564334e55d3d892b71aa1c858c7c5b1fa4096bdc7f6f411f419ab87e"


def load_sample(repo_root):
    data = read_regular_bytes(Path(repo_root) / SAMPLE_FILE, 32 * 1024)
    if digest_bytes(data) != SAMPLE_SHA256:
        raise ValueError("synthetic sample identity mismatch")
    parsed = parse_inference_csv(data)
    if len(parsed.frame) != 8 or parsed.has_binary_labels or parsed.has_family_labels or parsed.has_event_time:
        raise ValueError("synthetic sample contract mismatch")
    return data, parsed.frame
