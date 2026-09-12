import copy
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.datasets.unsw_nb15 import (  # noqa: E402
    ATTACK_FAMILY_COLUMN,
    BINARY_LABEL_COLUMN,
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
)
from cids.workbench.config import (  # noqa: E402
    WorkbenchConfigError,
    load_workbench_config,
    validate_workbench_config,
    workbench_config_sha256,
)
from cids.workbench.contracts import (  # noqa: E402
    EVENT_TIME_COLUMN,
    InputContractError,
    PredictionContractError,
    PredictionRecord,
    parse_inference_csv,
    queue_band_for,
)


def valid_frame(rows=2):
    values = []
    for index in range(rows):
        row = {column: index + 1 for column in NUMERIC_FEATURES}
        row.update({"proto": "tcp", "service": "-", "state": "FIN"})
        values.append(row)
    return pd.DataFrame(values).loc[:, FEATURE_COLUMNS]


def payload(frame):
    return frame.to_csv(index=False).encode()


def test_accepts_feature_only_csv_and_generates_stable_ids():
    result = parse_inference_csv(payload(valid_frame()))

    assert result.generated_ids is True
    assert result.frame["id"].tolist() == ["record-000001", "record-000002"]
    assert list(result.frame.columns) == ["id", *FEATURE_COLUMNS]
    assert result.has_event_time is False
    assert result.has_binary_labels is False
    assert result.has_family_labels is False
    assert len(result.input_sha256) == 64


def test_accepts_and_normalizes_optional_analysis_metadata():
    frame = valid_frame()
    frame.insert(0, "id", ["a", "b"])
    frame[EVENT_TIME_COLUMN] = ["2026-09-12T10:00:00+05:30", "2026-09-12T04:31:00Z"]
    frame[ATTACK_FAMILY_COLUMN] = ["Normal", "Backdoors"]
    frame[BINARY_LABEL_COLUMN] = [0, 1]

    result = parse_inference_csv(payload(frame))

    assert result.generated_ids is False
    assert result.has_event_time is True
    assert result.has_binary_labels is True
    assert result.has_family_labels is True
    assert result.frame[EVENT_TIME_COLUMN].tolist() == [
        "2026-09-12T04:30:00Z",
        "2026-09-12T04:31:00Z",
    ]
    assert result.frame[ATTACK_FAMILY_COLUMN].tolist() == ["normal", "backdoor"]


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda frame: frame.drop(columns=[FEATURE_COLUMNS[0]]), "missing="),
        (lambda frame: frame.assign(secret="value"), "extra="),
        (lambda frame: frame.assign(proto=""), "proto contains"),
        (lambda frame: frame.assign(dur="not-a-number"), "non-numeric"),
        (lambda frame: frame.assign(dur=float("inf")), "finite"),
        (lambda frame: frame.assign(id=["same", "same"]), "id must be unique"),
        (
            lambda frame: frame.assign(event_time="2026-09-12T10:00:00"),
            "explicit UTC offset",
        ),
    ],
)
def test_rejects_invalid_inference_frames(mutate, match):
    with pytest.raises(InputContractError, match=match):
        parse_inference_csv(payload(mutate(valid_frame())))


def test_rejects_duplicate_headers_before_pandas_can_mangle_them():
    frame = valid_frame(1)
    data = payload(frame).replace(b"dur,proto", b"dur,dur")

    with pytest.raises(InputContractError, match="duplicate CSV columns"):
        parse_inference_csv(data)


def test_rejects_compressed_uploads_and_resource_limit_overruns():
    with pytest.raises(InputContractError, match="compressed"):
        parse_inference_csv(b"\x1f\x8bnot-really-gzip")

    config = copy.deepcopy(load_workbench_config())
    config["input"]["max_upload_bytes"] = 10
    with pytest.raises(InputContractError, match="upload-size"):
        parse_inference_csv(payload(valid_frame()), config=config)

    config = copy.deepcopy(load_workbench_config())
    config["input"]["max_rows"] = 1
    with pytest.raises(InputContractError, match="row limit"):
        parse_inference_csv(payload(valid_frame()), config=config)


def test_rejects_inconsistent_optional_ground_truth():
    frame = valid_frame()
    frame[ATTACK_FAMILY_COLUMN] = ["normal", "generic"]
    frame[BINARY_LABEL_COLUMN] = [1, 0]

    with pytest.raises(InputContractError, match="attack_cat and label disagree"):
        parse_inference_csv(payload(frame))


def test_queue_band_is_deterministic_and_not_named_severity():
    assert queue_band_for("normal", "normal", 0.1) == "not_alerted"
    assert queue_band_for("attack", "normal", 0.99) == "model_disagreement"
    assert queue_band_for("attack", "generic", 0.89) == "review"
    assert queue_band_for("attack", "generic", 0.90) == "higher_score_review"

    with pytest.raises(PredictionContractError, match="between 0 and 1"):
        queue_band_for("normal", "normal", float("nan"))


def test_prediction_contract_rejects_confidence_like_out_of_range_score():
    with pytest.raises(PredictionContractError, match="between 0 and 1"):
        PredictionRecord(
            record_id="record-1",
            event_time_utc=None,
            binary_prediction="attack",
            attack_model_score=1.1,
            family_prediction_raw="generic",
            family_model_score=0.8,
            triage_family="generic",
            queue_band="review",
            explanation_status="not_requested",
            top_contributions=(),
            model_pack_id="0" * 64,
        )


def test_feature_contract_still_has_exactly_three_categorical_features():
    assert CATEGORICAL_FEATURES == ("proto", "service", "state")
    assert len(FEATURE_COLUMNS) == 42


def test_workbench_policy_is_pinned_and_rejects_excessive_explanation_work():
    config = load_workbench_config()
    assert workbench_config_sha256(config) == (
        "59772a2f9ec058c51d58b5e9757dbff276b6f9599f584d99366c9a9c0a8037c9"
    )

    config = copy.deepcopy(config)
    config["explainability"]["max_explain_rows"] = 33
    with pytest.raises(WorkbenchConfigError, match="hard limit"):
        validate_workbench_config(config)
