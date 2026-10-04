"""Phase 3C input/session and identity tests, independent of Streamlit."""
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from cids.workbench.analysis import (AnalysisSession, AnalysisUnavailable, configured_pack_dir,
                                    models_disagree, queue_indices, read_upload, validation_message)
from cids.workbench.contracts import InputContractError, PredictionRecord, parse_inference_csv
from test_workbench_contracts import valid_frame, payload

PACK_ID = "a" * 64


class Upload(io.BytesIO):
    def __init__(self, data, file_id="one"):
        super().__init__(data)
        self.size = len(data)
        self.file_id = file_id


def record(id, binary="normal", family="normal", score=0.1, time=None):
    from cids.workbench.contracts import queue_band_for
    return PredictionRecord(id, time, binary, score, family, 0.6,
                            "not_alerted" if binary == "normal" else "unresolved" if family == "normal" else family,
                            queue_band_for(binary, family, score), "not_requested", (), PACK_ID)


def fake_pack():
    import numpy as np
    artifact = SimpleNamespace(preprocessor=SimpleNamespace(transformer=SimpleNamespace(
        named_transformers_={"categorical": SimpleNamespace(categories_=[np.array(["tcp"]), np.array(["-"]), np.array(["FIN"])])})))
    return SimpleNamespace(model_pack_id=PACK_ID, binary=artifact, multiclass=artifact)


@pytest.fixture
def scoring(monkeypatch):
    from cids.workbench import inference
    calls = []
    def load(directory):
        calls.append("load")
        return fake_pack()
    def infer(pack, data):
        calls.append("infer")
        return tuple(record(id, time=data.frame.iloc[i].get("event_time")) for i, id in enumerate(data.frame.id))
    monkeypatch.setattr(inference, "load_model_pack", load)
    monkeypatch.setattr(inference, "infer", infer)
    return calls


def session(tmp_path):
    state = AnalysisSession()
    state.bind(tmp_path, PACK_ID)
    return state


def test_upload_size_checked_before_read_or_parse():
    class TooLarge:
        size = 10485761
        def seek(self, *_):
            pytest.fail("oversized upload must never be read")
    with pytest.raises(InputContractError):
        read_upload(TooLarge())


def test_actual_read_is_bounded_even_with_false_declared_size():
    class Dishonest(Upload):
        def read(self, count):
            assert count == 10485761
            return super().read(count)
    upload = Dishonest(b"x" * 10485762)
    upload.size = 1
    with pytest.raises(InputContractError):
        read_upload(upload)
    assert upload.tell() == 10485761


def test_receive_display_and_explicit_reanalysis(tmp_path, scoring):
    state = session(tmp_path)
    upload = Upload(payload(valid_frame()))
    state.receive(upload)
    assert state.input_data is not None and state.result is None and scoring == []
    state.analyze()
    result = state.current_result()
    state.receive(upload)
    assert state.current_result() is result and scoring == ["load", "infer"]
    state.analyze()
    assert scoring == ["load", "infer", "load", "infer"]


@pytest.mark.parametrize("transition", ["replace", "same_bytes_replace", "invalid", "remove", "pack", "clear", "failure"])
def test_transitions_discard_previous_analysis(tmp_path, scoring, monkeypatch, transition):
    state = session(tmp_path)
    upload = Upload(payload(valid_frame()))
    state.receive(upload)
    state.analyze()
    assert state.current_result() is not None
    if transition == "replace":
        state.receive(Upload(payload(valid_frame(3)), "two"))
    elif transition == "same_bytes_replace":
        state.receive(Upload(upload.getvalue(), "two"))
    elif transition == "invalid":
        state.receive(Upload(b"bad", "two"))
    elif transition == "remove":
        state.receive(None)
    elif transition == "pack":
        state.bind(tmp_path, "b" * 64)
    elif transition == "clear":
        epoch = state.uploader_epoch
        state.invalidate(reset_uploader=True)
        assert state.uploader_epoch == epoch + 1
    else:
        from cids.workbench import inference
        def fail(_):
            raise RuntimeError("PRIVATE_VALUE")
        monkeypatch.setattr(inference, "load_model_pack", fail)
        state.analyze()
        assert "PRIVATE_VALUE" not in state.error
    assert state.current_result() is None and state.result is None


def test_results_cannot_be_displayed_against_wrong_provenance(tmp_path, scoring):
    state = session(tmp_path)
    state.receive(Upload(payload(valid_frame())))
    state.analyze()
    state.input_data = parse_inference_csv(payload(valid_frame(3)))
    assert state.current_result() is None


def test_sessions_are_isolated(tmp_path, scoring):
    first, second = session(tmp_path), session(tmp_path)
    first.receive(Upload(payload(valid_frame())))
    first.analyze()
    assert second.input_data is None and second.result is None
    second.invalidate()
    assert first.current_result() is not None


def test_out_of_vocabulary_counts_precede_scoring(tmp_path, scoring):
    state = session(tmp_path)
    state.receive(Upload(payload(valid_frame().assign(proto="unknown-sensitive"))))
    def before(warnings):
        assert scoring == ["load"]
        assert [(w.task, w.feature, w.rows) for w in warnings] == [("binary", "proto", 2), ("multiclass", "proto", 2)]
    state.analyze(before_scoring=before)
    assert state.result is not None
    assert "unknown-sensitive" not in repr(state.result.warnings)


def test_stable_filter_sort_and_two_disagreement_directions():
    records = (record("late", "normal", "generic", time="2026-01-02T00:00:00Z"),
               record("early", "attack", "normal", .95, "2026-01-01T00:00:00Z"),
               record("tie", "attack", "generic", .95, "2026-01-01T00:00:00Z"))
    assert [models_disagree(r) for r in records] == [True, True, False]
    assert queue_indices(records, bands=("model_disagreement",)) == [1]
    assert queue_indices(records, disagreements_only=True) == [0, 1]
    assert queue_indices(records, order="timestamp") == [1, 2, 0]
    assert queue_indices(records, order="score") == [1, 2, 0]
    assert [records[i].record_id for i in queue_indices(records, order="timestamp")] == ["early", "tie", "late"]
    assert queue_indices(records, bands=()) == []


@pytest.mark.parametrize("id", [None, "../pack", "https://example.com", "A" * 64, "a" * 63])
def test_binding_refuses_unconfigured_or_arbitrary_paths(tmp_path, id):
    with pytest.raises(AnalysisUnavailable):
        configured_pack_dir(tmp_path, id)


def test_binding_refuses_symlinked_root(tmp_path):
    (tmp_path / "artifacts").symlink_to(tmp_path)
    with pytest.raises(AnalysisUnavailable):
        configured_pack_dir(tmp_path, PACK_ID)


@pytest.mark.parametrize("error", ["event_time is not valid ISO 8601: 'PRIVATE'", "attack_cat and label disagree for IDs ['PRIVATE']", "inference schema mismatch; extra=['PRIVATE']", "unknown attack family: PRIVATE"])
def test_validation_errors_do_not_echo_private_contents(error):
    assert "PRIVATE" not in validation_message(InputContractError(error))


def test_supplied_text_ids_and_strict_body_quoting():
    data = payload(valid_frame(1).assign(id="00017"))
    assert parse_inference_csv(data).frame.id.tolist() == ["00017"]
    data = payload(valid_frame(1)).replace(b",tcp,", b',"tcp"junk,')
    with pytest.raises(InputContractError, match="quoting"):
        parse_inference_csv(data)
    data = payload(valid_frame(1)).rstrip() + b",surplus\n"
    with pytest.raises(InputContractError, match="field count"):
        parse_inference_csv(data)
