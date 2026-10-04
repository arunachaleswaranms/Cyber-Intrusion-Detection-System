"""Correctness and cancellable-runtime tests on constructed/synthetic inputs."""
import copy
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from cids.datasets.unsw_nb15 import FEATURE_COLUMNS
from cids.workbench.config import load_workbench_config
from cids.workbench.explanations import ExplanationGateError, validate_contributions, aggregate_to_source_features
from cids.workbench import explanation_service as service
from cids.workbench import explanation_resources as er
from cids.workbench import model_pack
from test_explanation_resources import resource_fixture
from test_workbench_contracts import payload, valid_frame
from test_workbench_analysis import record, PACK_ID
from cids.workbench.analysis import AnalysisResult
from cids.workbench.contracts import parse_inference_csv


def arrays(task):
    mapping = (*FEATURE_COLUMNS, "proto", "service")
    values = np.zeros((2, 44))
    values[:, 0], values[:, -1] = (-2, 2), (.5, .25)
    if task == "binary":
        classes, bases = (0, 1), np.array([.25, .25])
        predictions = [0, 1]
    else:
        classes, bases = ("exploits", "generic", "normal"), np.ones((2, 3))
        values = np.repeat(values[:, :, None], 3, axis=2)
        values[0, 0, 2] = 4
        values[1, 0, 0] = 4
        predictions = ["normal", "exploits"]
    raw = bases + values.sum(axis=1)
    return classes, values, bases, raw, mapping, predictions


@pytest.mark.parametrize("task", ["binary", "multiclass"])
def test_class_mapping_full_reconstruction_and_42_source_features(task):
    classes, values, bases, raw, mapping, predictions = arrays(task)
    results = validate_contributions(task, classes, values, bases, raw, mapping, predictions, load_workbench_config()["explainability"])
    assert len(results) == 2
    for result in results:
        assert len(result["contributions"]) == 42
        assert abs(result["baseline_output"] + sum(result["contributions"]) - result["model_output"]) < 1e-10
    assert [r["explained_class"] for r in results] == ([1, 1] if task == "binary" else predictions)
    if task == "binary":
        assert results[0]["model_output"] < 0  # Attack attribution for a normal prediction.
    assert aggregate_to_source_features(values, mapping).shape[1] == 42


@pytest.mark.parametrize("task", ["binary", "multiclass"])
@pytest.mark.parametrize("mutation", ["rows", "features", "classes", "bases", "raw_shape", "nan", "inf", "prediction", "additivity", "unknown_mapping", "missing_source"])
def test_contributions_fail_closed_before_display(task, mutation):
    classes, values, bases, raw, mapping, predictions = arrays(task)
    if mutation == "rows":
        values = values[:1]
    elif mutation == "features":
        values = values[:, :-1]
    elif mutation == "classes":
        classes = (1, 0) if task == "binary" else ("normal", "normal", "generic")
    elif mutation == "bases":
        bases = bases[:1]
    elif mutation == "raw_shape":
        raw = raw.reshape(-1, 1)
    elif mutation in ("nan", "inf"):
        values.flat[0] = float(mutation)
    elif mutation == "prediction":
        predictions = [1, 1] if task == "binary" else ["generic", "generic"]
    elif mutation == "additivity":
        raw = raw + .01
    elif mutation == "unknown_mapping":
        mapping = (*mapping[:-1], "unknown")
    elif mutation == "missing_source":
        mapping = tuple("proto" if s == "dur" else s for s in mapping)
    with pytest.raises(ExplanationGateError):
        validate_contributions(task, classes, values, bases, raw, mapping, predictions, load_workbench_config()["explainability"])


def test_all_multiclass_outputs_checked_before_predicted_class_selection():
    classes, values, bases, raw, mapping, predictions = arrays("multiclass")
    raw[0, 0] += .001  # Corrupt an unselected class: still fails.
    with pytest.raises(ExplanationGateError, match="additivity"):
        validate_contributions("multiclass", classes, values, bases, raw, mapping, predictions, load_workbench_config()["explainability"])


def test_aggregation_conservation_is_checked_independently(monkeypatch):
    from cids.workbench import explanations
    original = explanations.aggregate_to_source_features
    def corrupt(*args):
        result = original(*args)
        result[:, 0] += .0001
        return result
    monkeypatch.setattr(explanations, "aggregate_to_source_features", corrupt)
    with pytest.raises(ExplanationGateError, match="aggregation"):
        validate_contributions("binary", *arrays("binary"), load_workbench_config()["explainability"])


WORKER_FIXTURE = Path(__file__).with_name("phase4_worker_fixture.py")


@pytest.mark.parametrize("mode,seconds", [("sleep", .25), ("partial", 5), ("error", 10), ("oversized", 10), ("exit", 10)])
def test_deadline_worker_failure_ipc_bounds_and_cleanup(mode, seconds, monkeypatch):
    created = []
    original = service.subprocess.Popen
    def track(*args, **kwargs):
        process = original(*args, **kwargs)
        created.append(process)
        return process
    monkeypatch.setattr(service.subprocess, "Popen", track)
    start = time.monotonic()
    with pytest.raises(service.ExplanationFailure, match="Analysis remains usable"):
        service._isolated(b"{}", seconds, command=[sys.executable, str(WORKER_FIXTURE), mode])
    assert time.monotonic() - start < seconds + 4
    assert len(created) == 1 and created[0].poll() is not None
    assert created[0].stdin.closed and created[0].stdout.closed


@pytest.mark.parametrize("data,seconds", [(b"x" * (service.MAX_REQUEST_BYTES + 1), 60), (b"{}", 61), (b"{}", 0)])
def test_bounds_checked_before_worker_start(data, seconds, monkeypatch):
    monkeypatch.setattr(service.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not start a worker"))
    with pytest.raises(service.ExplanationFailure):
        service._isolated(data, seconds)


def local_values(record_index=0, record_id="record-000001"):
    return {"record_index": record_index, "record_id": record_id, "explained_class": 1, "baseline_output": -2., "model_output": -1., "contributions": [1.] + [0.] * 41,
            "max_additivity_error": 0., "max_aggregation_error": 0.}


def test_request_passes_selected_rows_only_and_binds_result_identity(resource_fixture, monkeypatch):
    f = resource_fixture
    resources = er.load_resources(f.repo, f.root.name, f.pack)
    data = parse_inference_csv(payload(valid_frame(50)))
    records = tuple(record(id) for id in data.frame.id)
    analysis = AnalysisResult(data.input_sha256, PACK_ID, records, ())
    def isolated(request, seconds):
        request = json.loads(request)
        selected = pd.DataFrame(request["selected_rows"])
        assert selected.id.tolist() == [records[7].record_id, records[3].record_id]
        assert len(selected) == 2 and request["input_sha256"] == data.input_sha256 and seconds == 60
        return [local_values(7, records[7].record_id), local_values(3, records[3].record_id)]
    monkeypatch.setattr(service, "_isolated", isolated)
    results = service.request_explanations(f.repo, data, analysis, resources, "binary", [7, 3])
    assert [(r.record_index, r.record_id) for r in results] == [(7, records[7].record_id), (3, records[3].record_id)]
    assert all(r.resource_id == resources.resource_id and r.input_sha256 == data.input_sha256 and r.explained_class == "attack" for r in results)
    assert all(len(r.contributions) == 42 for r in results)


@pytest.mark.parametrize("mutation", ["short", "wrong_class", "missing_feature", "nonfinite", "additivity", "error_bound", "prediction", "record_id", "record_index"])
def test_parent_rejects_malformed_worker_result(resource_fixture, monkeypatch, mutation):
    f = resource_fixture
    resources = er.load_resources(f.repo, f.root.name, f.pack)
    data = parse_inference_csv(payload(valid_frame()))
    analysis = AnalysisResult(data.input_sha256, PACK_ID, tuple(record(id) for id in data.frame.id), ())
    value = local_values()
    if mutation == "record_id": value["record_id"] = "wrong"
    if mutation == "record_index": value["record_index"] = 1
    if mutation == "wrong_class": value["explained_class"] = 0
    if mutation == "missing_feature": value["contributions"].pop()
    if mutation == "nonfinite": value["contributions"][0] = float("nan")
    if mutation == "additivity": value["baseline_output"] += 1
    if mutation == "error_bound": value["max_aggregation_error"] = .01
    if mutation == "prediction": value.update(model_output=1., baseline_output=0.)
    monkeypatch.setattr(service, "_isolated", lambda *_: [] if mutation == "short" else [value])
    with pytest.raises(service.ExplanationFailure):
        service.request_explanations(f.repo, data, analysis, resources, "binary", [0])


@pytest.mark.parametrize("task", ["binary", "multiclass"])
@pytest.mark.skipif(model_pack.current_runtime() != model_pack.EXPECTED_RUNTIME, reason="Phase 4 representative verified worker requires pinned model runtime")
def test_representative_verified_subprocess_worker_end_to_end(tmp_path, monkeypatch, resource_fixture, task):
    pytest.importorskip("shap", reason="Phase 4 representative SHAP worker requires pinned SHAP")
    from test_workbench_inference import synthetic_artifact, pack_directory
    from cids.workbench.analysis import PACK_ROOT
    from cids.workbench.inference import load_model_pack, infer
    root = tmp_path / PACK_ROOT
    root.mkdir(parents=True)
    directory = pack_directory(root, monkeypatch, {t: synthetic_artifact(t) for t in ("binary", "multiclass")})
    pack = load_model_pack(directory)
    f = resource_fixture
    f.manifest.update({k: json.loads((directory / "manifest.json").read_text())[k] for k in ("model_pack_id", "artifacts", "runtime")})
    f.pack = json.loads((directory / "manifest.json").read_text())
    resource = f.publish()
    resources = er.load_resources(tmp_path, resource.name, f.pack)
    data = parse_inference_csv(payload(valid_frame(2)))
    analysis = AnalysisResult(data.input_sha256, pack.model_pack_id, infer(pack, data), ())
    original = service._isolated
    monkeypatch.setattr(service, "_isolated", lambda data, seconds: original(data, seconds, command=[sys.executable, str(WORKER_FIXTURE), "representative"]))
    values = service.request_explanations(tmp_path, data, analysis, resources, task, [1])
    assert len(values) == 1 and values[0].record_id == data.frame.id.iloc[1]
    assert len(values[0].contributions) == 42 and values[0].max_additivity_error <= 1e-5
    assert values[0].explained_class == ("attack" if task == "binary" else analysis.records[1].family_prediction_raw)


@pytest.mark.skipif(model_pack.current_runtime() != model_pack.EXPECTED_RUNTIME, reason="Phase 4 original-model explanation integration requires pinned model runtime")
def test_optional_original_pack_explains_synthetic_sample_only():
    identifier = os.environ.get("CIDS_PHASE4_ORIGINAL_RESOURCE_ID")
    if not identifier:
        pytest.skip("verified frozen-development resources were not supplied for original-model Phase 4 integration")
    pytest.importorskip("shap", reason="original-model Phase 4 integration requires pinned SHAP")
    from cids.workbench.analysis import configured_pack_dir
    from cids.workbench.inference import load_model_pack, infer
    from cids.workbench.model_pack import preflight_model_pack
    from cids.workbench.synthetic_sample import load_sample
    root = Path(__file__).parents[1]
    pack_id = "e2d4f329b894a1b68b70af377ffc94441e02d024de27e7c351384d3e25692b18"
    directory = configured_pack_dir(root, pack_id)
    if not directory.is_dir():
        pytest.skip("registered original pack is unavailable for Phase 4 integration")
    verified = preflight_model_pack(directory)
    resources = er.load_resources(root, identifier, verified.manifest)
    data = parse_inference_csv(load_sample(root)[0])
    pack = load_model_pack(directory)
    analysis = AnalysisResult(data.input_sha256, pack_id, infer(pack, data), ())
    for task in ("binary", "multiclass"):
        value = service.request_explanations(root, data, analysis, resources, task, [0])[0]
        assert value.record_id == "synthetic-0001" and len(value.contributions) == 42
        assert value.max_additivity_error <= 1e-5 and value.max_aggregation_error <= 1e-10


@pytest.mark.parametrize("classes", [(False, True), (0., 1.)])
def test_binary_class_labels_require_integer_attack_mapping(classes):
    _, values, bases, raw, mapping, predictions = arrays("binary")
    with pytest.raises(ExplanationGateError):
        validate_contributions("binary", classes, values, bases, raw, mapping, predictions, load_workbench_config()["explainability"])


def test_child_startup_error_is_fixed_safe_failure(monkeypatch):
    def fail(*args, **kwargs): raise OSError("PRIVATE STARTUP DETAIL")
    monkeypatch.setattr(service.subprocess, "Popen", fail)
    with pytest.raises(service.ExplanationFailure) as caught:
        service._isolated(b"{}", 1)
    assert str(caught.value) == service.FAILURE_MESSAGE


def test_json_worker_input_preserves_normalized_float_bits(resource_fixture, monkeypatch):
    f = resource_fixture
    resources = er.load_resources(f.repo, f.root.name, f.pack)
    frame = valid_frame(2).assign(dur=[0.12345678901234568, 1.0000000000000002])
    data = parse_inference_csv(payload(frame))
    result = AnalysisResult(data.input_sha256, PACK_ID, tuple(record(id) for id in data.frame.id), ())
    def inspect(request, seconds):
        selected = pd.DataFrame(json.loads(request)["selected_rows"])
        assert float(selected.dur.iloc[0]).hex() == float(data.frame.dur.iloc[1]).hex()
        return [local_values(1, data.frame.id.iloc[1])]
    monkeypatch.setattr(service, "_isolated", inspect)
    service.request_explanations(f.repo, data, result, resources, "binary", [1])


@pytest.mark.parametrize("indices", [list(range(33)), [0, 0], [-1], [50]])
def test_selected_record_bounds_reject_before_worker(resource_fixture, monkeypatch, indices):
    f = resource_fixture
    resources = er.load_resources(f.repo, f.root.name, f.pack)
    data = parse_inference_csv(payload(valid_frame(50)))
    result = AnalysisResult(data.input_sha256, PACK_ID, tuple(record(id) for id in data.frame.id), ())
    monkeypatch.setattr(service, "_isolated", lambda *_: pytest.fail("must not launch worker"))
    with pytest.raises(service.ExplanationFailure):
        service.request_explanations(f.repo, data, result, resources, "binary", indices)


def test_service_can_validate_maximum_32_selected_rows(resource_fixture, monkeypatch):
    f = resource_fixture
    resources = er.load_resources(f.repo, f.root.name, f.pack)
    data = parse_inference_csv(payload(valid_frame(50)))
    result = AnalysisResult(data.input_sha256, PACK_ID, tuple(record(id) for id in data.frame.id), ())
    def bounded(request, seconds):
        decoded = json.loads(request)
        assert len(decoded["selected_rows"]) == 32 and len(request) <= service.MAX_REQUEST_BYTES
        return [local_values(i, data.frame.id.iloc[i]) for i in range(32)]
    monkeypatch.setattr(service, "_isolated", bounded)
    assert len(service.request_explanations(f.repo, data, result, resources, "binary", list(range(32)))) == 32


@pytest.mark.parametrize("background_rows,foreground_rows", [(0, 1), (257, 1), (8, 33)])
def test_calculation_row_limits_fail_before_shap(background_rows, foreground_rows, monkeypatch):
    from cids.workbench import explanations
    monkeypatch.setattr(explanations, "validate_artifact", lambda *_: None)
    monkeypatch.setattr(explanations, "_permutation_values", lambda *_: pytest.fail("must not compute SHAP"))
    with pytest.raises(ExplanationGateError, match="inputs exceed bounds"):
        explanations.explain_records(SimpleNamespace(), valid_frame(max(1, background_rows)).iloc[:background_rows], valid_frame(foreground_rows))
