import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("shap")

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.datasets.split_unsw_nb15 import (  # noqa: E402
    prepare_development_splits,
    prepare_splits,
)
from cids.datasets.unsw_nb15 import (  # noqa: E402
    ATTACK_FAMILY_COLUMN,
    BINARY_LABEL_COLUMN,
    FEATURE_COLUMNS,
    ID_COLUMN,
    NUMERIC_FEATURES,
)
from cids.final_evaluation import train_and_evaluate_selected  # noqa: E402
from cids.experiments import run_shap_gate as gate_cli  # noqa: E402
from cids.workbench.config import load_workbench_config  # noqa: E402
from cids.workbench.explanations import (  # noqa: E402
    ExplanationGateError,
    aggregate_to_source_features,
    run_explanation_gate,
    source_feature_mapping,
)


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


def make_splits(task):
    training = [row(index, index) for index in range(1, 21)]
    training.extend(row(index, index, "generic", 1, "udp") for index in range(21, 41))
    training.extend(
        row(index, index, "exploits", 1, "udp") for index in range(41, 61)
    )
    testing = pd.DataFrame(
        [
            row(1, 101),
            row(2, 102),
            row(3, 103, "generic", 1, "udp"),
            row(4, 104, "generic", 1, "udp"),
            row(5, 105, "exploits", 1, "udp"),
            row(6, 106, "exploits", 1, "udp"),
        ]
    )
    return prepare_splits(
        pd.DataFrame(training), testing, task, validation_fraction=0.20
    )


@pytest.mark.parametrize("task", ["binary", "multiclass"])
def test_shap_gate_maps_classes_adds_up_and_aggregates_to_42_features(task):
    splits = make_splits(task)
    artifact = train_and_evaluate_selected(splits).artifact
    config = copy.deepcopy(load_workbench_config())
    config["explainability"]["background_rows"] = 16
    config["explainability"]["explain_rows"] = 4

    result = run_explanation_gate(
        artifact,
        splits.train.head(16),
        splits.validation.head(4),
        config=config,
    )

    assert result.task == task
    assert result.source_feature_count == 42
    assert result.shap_values_shape[0] == 4
    assert result.max_additivity_error <= 1e-5
    assert result.max_aggregation_error <= 1e-10
    if task == "binary":
        assert result.explained_classes == (1,)
        assert len(result.shap_values_shape) == 2
    else:
        assert result.explained_classes == result.class_labels
        assert len(result.shap_values_shape) == 3
    mapping = source_feature_mapping(artifact)
    assert len(mapping) == result.transformed_feature_count
    assert set(mapping) == set(FEATURE_COLUMNS)


def test_aggregation_preserves_each_rows_total_contribution():
    mapping = tuple(FEATURE_COLUMNS)
    values = np.arange(2 * len(mapping), dtype=float).reshape(2, len(mapping))

    aggregated = aggregate_to_source_features(values, mapping)

    np.testing.assert_allclose(aggregated, values)


def test_gate_enforces_explanation_row_bound_before_shap_work():
    splits = make_splits("binary")
    artifact = train_and_evaluate_selected(splits).artifact
    config = copy.deepcopy(load_workbench_config())
    config["explainability"]["background_rows"] = 16

    too_many = pd.concat([splits.validation] * 3, ignore_index=True)
    with pytest.raises(ExplanationGateError, match="row count"):
        run_explanation_gate(
            artifact,
            splits.train.head(16),
            too_many,
            config=config,
        )


@pytest.mark.parametrize("task", ["binary", "multiclass"])
def test_development_split_matches_frozen_cleaning_without_test_targets(task):
    # Reconstruct a fresh source so the comparison includes overlap cleaning.
    source_rows = [row(index, index) for index in range(1, 21)]
    source_rows.extend(
        row(index, index, "generic", 1, "udp") for index in range(21, 41)
    )
    source_rows.extend(
        row(index, index, "exploits", 1, "udp") for index in range(41, 61)
    )
    official_train = pd.DataFrame(source_rows)
    official_test = pd.DataFrame(
        [
            row(1, 101),
            row(2, 102),
            row(3, 103, "generic", 1, "udp"),
            row(4, 104, "generic", 1, "udp"),
            row(5, 105, "exploits", 1, "udp"),
            row(6, 106, "exploits", 1, "udp"),
        ]
    )
    frozen = prepare_splits(official_train, official_test, task, validation_fraction=0.2)
    development = prepare_development_splits(
        official_train,
        official_test.loc[:, FEATURE_COLUMNS],
        task,
        validation_fraction=0.2,
    )

    pd.testing.assert_frame_equal(development.train, frozen.train)
    pd.testing.assert_frame_equal(development.validation, frozen.validation)
    assert development.report["official_test_access"] == (
        "features_only_for_overlap_removal"
    )
    assert "official_test" not in development.report["class_counts"]


def test_shap_cli_requires_explicit_trust_before_any_deserialization(
    monkeypatch, tmp_path
):
    def unexpected_load(_):
        raise AssertionError("artifact deserialization must not be reached")

    monkeypatch.setattr(gate_cli, "load_artifact", unexpected_load)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_shap_gate",
            "--data-dir",
            str(tmp_path),
            "--binary-artifact",
            str(tmp_path / "binary.joblib"),
            "--multiclass-artifact",
            str(tmp_path / "multiclass.joblib"),
            "--output",
            str(tmp_path / "report.json"),
            "--confirm",
            "WRONG",
        ],
    )

    with pytest.raises(gate_cli.ShapGateCliError, match="refusing to deserialize"):
        gate_cli.main()
