"""Accepted deterministic, target-stratified development sampling (seed 42)."""
import hashlib
import pandas as pd
from cids.datasets.split_unsw_nb15 import target_for_task
from cids.datasets.unsw_nb15 import ID_COLUMN

SAMPLING_NAMESPACE = "cids-shap-compatibility-gate-v2"

class ShapGateCliError(ValueError):
    """Invalid bounded development sample."""


def _rank(task: str, row_id: object) -> str:
    return hashlib.sha256(f"{SAMPLING_NAMESPACE}|{task}|{row_id}".encode()).hexdigest()


def _stratified_sample(frame: pd.DataFrame, task: str, size: int) -> pd.DataFrame:
    target = target_for_task(task)
    if size <= 0 or frame.empty:
        raise ShapGateCliError("SHAP sample requires positive size and non-empty data")
    ranked_groups: dict[object, list[int]] = {}
    for label, group in frame.groupby(target, sort=True):
        ranked_groups[label] = sorted(
            group.index, key=lambda index: _rank(task, frame.at[index, ID_COLUMN])
        )
    chosen = [indices[0] for indices in ranked_groups.values()]
    remaining = [
        index for indices in ranked_groups.values() for index in indices[1:]
    ]
    remaining.sort(key=lambda index: _rank(task, frame.at[index, ID_COLUMN]))
    selected = (chosen + remaining)[: min(size, len(frame))]
    return frame.loc[selected].sort_values(ID_COLUMN).reset_index(drop=True)
