import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from data_preprocessing import (  # noqa: E402
    CATEGORICAL_FEATURES,
    FEATURE_NAMES,
    TARGET,
    build_preprocessor,
    load_dataset,
    split_features_target,
)


def sample_row(protocol="tcp", service="http", flag="SF", label="normal."):
    values = {feature: 0 for feature in FEATURE_NAMES}
    values.update(
        {"protocol_type": protocol, "service": service, "flag": flag, TARGET: label}
    )
    return values


def test_loads_headerless_data_and_normalizes_label(tmp_path):
    path = tmp_path / "sample.csv"
    pd.DataFrame([sample_row()])[[*FEATURE_NAMES, TARGET]].to_csv(
        path, header=False, index=False
    )

    loaded = load_dataset(path)

    assert loaded.loc[0, TARGET] == "normal"
    assert list(loaded.columns) == [*FEATURE_NAMES, TARGET]


def test_unseen_test_categories_do_not_affect_training_encoder():
    train = pd.DataFrame([sample_row(), sample_row(service="smtp")])
    test = pd.DataFrame([sample_row(service="never_seen")])
    X_train, _ = split_features_target(train)
    X_test, _ = split_features_target(test)
    preprocessor = build_preprocessor().fit(X_train)

    transformed = preprocessor.transform(X_test)
    service_index = len(FEATURE_NAMES) - len(CATEGORICAL_FEATURES) + 1

    assert transformed[0, service_index] == -1
