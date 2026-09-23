import copy
import hashlib
import json
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


SELECTED_GATE_REPORT = (
    Path(__file__).parents[1] / "results" / "v2.1" / "shap-gate-selected-v2.json"
)
SELECTED_GATE_REPORT_SHA256 = (
    "d6db9aae2368b09b33b22a666d67208e27f28c277a5e613b07aed12e0551f528"
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
    assert result.explainer_algorithm == "permutation"
    assert result.permutation_rounds == 1
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


def test_preserved_selected_artifact_gate_evidence_passes_frozen_bounds():
    encoded = SELECTED_GATE_REPORT.read_bytes()
    assert hashlib.sha256(encoded).hexdigest() == SELECTED_GATE_REPORT_SHA256
    report = json.loads(encoded)

    assert report["gate_version"] == "cids-shap-compatibility-gate-v2"
    assert report["status"] == "passed"
    assert report["official_test_status"] == "not_evaluated_by_gate"
    assert report["workbench_config_sha256"] == (
        "05a07e4e2590578d41c6c6a884c1037a2a0595d16e71debecf4508f3c3e11099"
    )
    assert set(report["tasks"]) == {"binary", "multiclass"}

    for task in report["tasks"].values():
        assert task["explainer_algorithm"] == "permutation"
        assert task["background_partition"] == "prepared_train"
        assert task["foreground_partition"] == "prepared_validation"
        assert task["official_test_used_as_explanation_data"] is False
        assert task["source_feature_count"] == 42
        assert task["max_additivity_error"] <= 1e-5
        assert task["max_aggregation_error"] <= 1e-10
        assert task["elapsed_seconds"] <= 60.0
