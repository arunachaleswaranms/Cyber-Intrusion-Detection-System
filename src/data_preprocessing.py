"""Dataset loading and leakage-safe preprocessing for KDD Cup 1999."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OrdinalEncoder, StandardScaler

FEATURE_NAMES = [
    "duration", "protocol_type", "service", "flag", "src_bytes", "dst_bytes",
    "land", "wrong_fragment", "urgent", "hot", "num_failed_logins",
    "logged_in", "num_compromised", "root_shell", "su_attempted", "num_root",
    "num_file_creations", "num_shells", "num_access_files", "num_outbound_cmds",
    "is_host_login", "is_guest_login", "count", "srv_count", "serror_rate",
    "srv_serror_rate", "rerror_rate", "srv_rerror_rate", "same_srv_rate",
    "diff_srv_rate", "srv_diff_host_rate", "dst_host_count",
    "dst_host_srv_count", "dst_host_same_srv_rate", "dst_host_diff_srv_rate",
    "dst_host_same_src_port_rate", "dst_host_srv_diff_host_rate",
    "dst_host_serror_rate", "dst_host_srv_serror_rate", "dst_host_rerror_rate",
    "dst_host_srv_rerror_rate",
]
CATEGORICAL_FEATURES = ["protocol_type", "service", "flag"]
NUMERICAL_FEATURES = [name for name in FEATURE_NAMES if name not in CATEGORICAL_FEATURES]
TARGET = "label"


def load_dataset(path: str | Path) -> pd.DataFrame:
    """Load a headerless KDD Cup file (plain or gzip-compressed)."""
    dataset_path = Path(path)
    if not dataset_path.is_file():
        raise FileNotFoundError(
            f"Dataset not found: {dataset_path}. See dataset/README.md for download steps."
        )

    frame = pd.read_csv(dataset_path, header=None, names=[*FEATURE_NAMES, TARGET])
    if frame.shape[1] != len(FEATURE_NAMES) + 1:
        raise ValueError(f"Expected 42 columns in {dataset_path}, found {frame.shape[1]}")

    frame[TARGET] = frame[TARGET].astype(str).str.strip().str.removesuffix(".")
    return frame


def split_features_target(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Return model features and labels from a validated dataset."""
    missing = set([*FEATURE_NAMES, TARGET]) - set(frame.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")
    return frame[FEATURE_NAMES], frame[TARGET]


def build_preprocessor() -> ColumnTransformer:
    """Create a transformer that must be fitted on training data only."""
    return ColumnTransformer(
        transformers=[
            ("numeric", StandardScaler(), NUMERICAL_FEATURES),
            (
                "categorical",
                OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                CATEGORICAL_FEATURES,
            ),
        ],
        verbose_feature_names_out=False,
    )
