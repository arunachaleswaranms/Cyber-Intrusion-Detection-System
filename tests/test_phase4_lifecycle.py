"""Ephemeral explanation state, selected identity, failure and export compatibility."""
from dataclasses import replace
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from cids.datasets.unsw_nb15 import FEATURE_COLUMNS
from cids.workbench import explanation_service as service
from cids.workbench.analysis import AnalysisSession
from cids.workbench.contracts import FeatureContribution
from cids.workbench.config import load_workbench_config, workbench_config_sha256
from test_workbench_analysis import scoring, session, Upload, PACK_ID
from test_workbench_contracts import valid_frame, payload


def resource():
    return SimpleNamespace(resource_id="c" * 64, manifest={"tasks": {task: {"background": {"sha256": "d" * 64}} for task in ("binary", "multiclass")}})


def local_result(state, task, index):
    baseline, output = -2., -1.
    explained_class = "attack" if task == "binary" else state.result.records[index].family_prediction_raw
    contributions = tuple(FeatureContribution(name, "bounded", float(i == 0), explained_class, baseline, output)
                          for i, name in enumerate(FEATURE_COLUMNS))
    return service.LocalExplanation(state.result.input_sha256, PACK_ID, resource().resource_id, "d" * 64,
                                    workbench_config_sha256(load_workbench_config()), task, index,
                                    state.result.records[index].record_id, explained_class,
                                    baseline, output, contributions, 0., 0.)


@pytest.fixture
def explanation_state(tmp_path, scoring, monkeypatch):
    state = session(tmp_path)
    state.receive(Upload(payload(valid_frame(4).assign(label=0))))
    state.analyze()
    state.bind_explanation_resource(resource().resource_id)
    state.sync_explanation_resources(resource())
    state.select_explanation_record(0)
    calls = []
    def request(root, data, result, resources, task, indices):
        calls.append((task, indices))
        return tuple(local_result(state, task, i) for i in indices)
    monkeypatch.setattr(service, "request_explanations", request)
    return state, calls


def test_explicit_action_no_work_on_display_simulation_or_export(explanation_state):
    state, calls = explanation_state
    assert state.explanation_status("binary") == "not_requested"
    state.current_result()
    state.simulate(.9)
    state.prepare_export()
    assert calls == []
    before = state.prepared_export
    original = state.result
    state.explain_selected("binary", resource())
    state.explain_selected("multiclass", resource())
    assert calls == [("binary", [0]), ("multiclass", [0])]
    assert state.explanation_status("binary") == state.explanation_status("multiclass") == "available"
    assert state.explanations["binary"].explained_class == "attack"
    assert state.explanations["multiclass"].explained_class == "normal"
    state.sync_explanation_resources(resource())
    state.select_explanation_record(0)
    state.current_result()
    assert calls == [("binary", [0]), ("multiclass", [0])] and state.result is original
    state.prepare_export()
    assert state.prepared_export == before
    document = json.loads(state.prepared_export)
    assert document["export_schema_version"] == "cids-review-export-v1"
    assert all(r["explanation_status"] == "not_requested" for r in document["records"])
    assert "contribution" not in state.prepared_export.decode() and "bounded" not in state.prepared_export.decode()


@pytest.mark.parametrize("transition", ["replace", "remove", "invalid", "clear", "reanalysis", "failed_analysis", "pack", "resource", "tampered_resource", "selection"])
def test_stale_explanation_clearing(explanation_state, monkeypatch, tmp_path, transition):
    state, _ = explanation_state
    state.explain_selected("binary", resource())
    assert state.explanations
    if transition == "replace": state.receive(Upload(payload(valid_frame(3)), "two"))
    if transition == "remove": state.receive(None)
    if transition == "invalid": state.receive(Upload(b"bad", "two"))
    if transition == "clear": state.invalidate()
    if transition == "reanalysis": state.analyze()
    if transition == "failed_analysis":
        from cids.workbench import inference
        monkeypatch.setattr(inference, "infer", lambda *_: (_ for _ in ()).throw(RuntimeError("private")))
        state.analyze()
    if transition == "pack": state.bind(tmp_path, "f" * 64)
    if transition == "resource": state.bind_explanation_resource("f" * 64)
    if transition == "tampered_resource": state.sync_explanation_resources(None)
    if transition == "selection": state.select_explanation_record(1)
    assert not state.explanations
    assert state.explanation_status("binary") != "available"


def test_failure_retains_predictions_review_simulation_and_export(explanation_state, monkeypatch):
    state, _ = explanation_state
    state.simulate(.9)
    state.prepare_export()
    before = state.result, state.simulation, state.prepared_export
    state.explain_selected("binary", resource())
    def fail(*_): raise service.ExplanationFailure("PRIVATE_VALUES")
    monkeypatch.setattr(service, "request_explanations", fail)
    state.explain_selected("binary", resource())
    assert state.explanation_status("binary") == "failed" and not state.explanations
    assert (state.result, state.simulation, state.prepared_export) == before
    state.explain_selected("multiclass", None)
    assert state.explanation_status("multiclass") == "unsupported"


@pytest.mark.parametrize("field,value", [("record_index", 1), ("record_id", "another"), ("input_sha256", "f" * 64),
                                          ("model_pack_id", "f" * 64), ("resource_id", "f" * 64), ("task", "multiclass"), ("policy_sha256", "f" * 64), ("background_sha256", "f" * 64), ("explained_class", "normal")])
def test_result_binding_mismatch_is_never_exposed(explanation_state, monkeypatch, field, value):
    state, _ = explanation_state
    wrong = replace(local_result(state, "binary", 0), **{field: value})
    monkeypatch.setattr(service, "request_explanations", lambda *_: (wrong,))
    state.explain_selected("binary", resource())
    assert state.explanation_status("binary") == "failed" and not state.explanations


def test_cross_session_isolation_and_selection(explanation_state, tmp_path):
    first, calls = explanation_state
    second = session(tmp_path)
    first.explain_selected("binary", resource())
    second.invalidate()
    assert first.explanations and not second.explanations
    first.select_explanation_record(2)
    assert not first.explanations and first.explanation_status("binary") == "not_requested"
    first.explain_selected("binary", resource())
    assert first.explanations["binary"].record_index == 2 and calls[-1] == ("binary", [2])


@pytest.mark.parametrize("failure", [False, True])
def test_selection_changed_during_calculation_cannot_publish_old_result(explanation_state, monkeypatch, failure):
    state, _ = explanation_state
    old = local_result(state, "binary", 0)
    def change(*_):
        state.select_explanation_record(1)
        if failure:
            raise service.ExplanationFailure("private")
        return (old,)
    monkeypatch.setattr(service, "request_explanations", change)
    state.explain_selected("binary", resource())
    assert not state.explanations and state.explanation_selection == 1
    assert state.explanation_status("binary") == "not_requested"
