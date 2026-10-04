"""Explicit Streamlit actions and sample preview; synthetic representative state."""
from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from cids.workbench import explanation_resources as er
from cids.workbench import explanation_service as service
from cids.workbench.synthetic_sample import load_sample, SAMPLE_FILE
from test_dashboard_analysis import available, local_options, run, analyzed, button, select, text
from test_workbench_contracts import payload, valid_frame
from test_phase4_lifecycle import resource, local_result

ROOT = Path(__file__).parents[1]


@pytest.fixture
def resources(monkeypatch, available):
    value = resource()
    value.manifest = {"model_pack_id": "a" * 64, "policy_sha256": "b" * 64,
                      "tasks": {task: {"provenance": {}, "background": {"sha256": "d" * 64}, "background_sample_id_sha256": "b" * 64}
                                for task in ("binary", "multiclass")}}
    monkeypatch.setenv(er.RESOURCE_ENV, value.resource_id)
    monkeypatch.setattr(er, "load_resources", lambda *_: value)
    calls = []
    def request(root, data, result, resources, task, indices):
        calls.append((task, indices))
        state = SimpleNamespace(result=result)
        return tuple(local_result(state, task, i) for i in indices)
    monkeypatch.setattr(service, "request_explanations", request)
    return value, calls


def test_explicit_selected_action_and_no_work_on_reruns_filters_simulation_export(resources):
    value, calls = resources
    app = analyzed(run(), payload(valid_frame(4).assign(label=0)))
    assert calls == [] and "explanation_status: not_requested · task: binary" in text(app)
    original = app.session_state.local_analysis.result
    button(app, "Explain selected record — binary").click().run()
    assert calls == [("binary", [0])] and "explanation_status: available · task: binary" in text(app)
    assert "All 42 source features shown" in text(app) and "omitted contribution: 0" in text(app)
    assert "Raw decision units are separate" in text(app)
    app.run()
    app.slider[0].set_value(.9).run()
    button(app, "Prepare export").click().run()
    assert calls == [("binary", [0])] and app.session_state.local_analysis.result is original
    select(app, "Review order").set_value("Attack model score (uncalibrated), descending").run()
    assert calls == [("binary", [0])]
    assert "explanation_status: available · task: binary" not in text(app)
    select(app, "Record detail").set_value(2).run()
    assert "explanation_status: available · task: binary" not in text(app)
    button(app, "Explain selected record — multiclass").click().run()
    assert calls[-1] == ("multiclass", [2])
    assert not app.exception


def test_resource_tamper_disables_explanations_keeps_analysis(resources, monkeypatch):
    app = analyzed(run(), payload(valid_frame(4)))
    button(app, "Explain selected record — binary").click().run()
    original = app.session_state.local_analysis.result
    def tampered(*_): raise er.ResourceError("PRIVATE PATH")
    monkeypatch.setattr(er, "load_resources", tampered)
    app.run()
    assert "explanation_status: unsupported" in text(app) and "PRIVATE PATH" not in text(app)
    assert not app.session_state.local_analysis.explanations
    assert app.session_state.local_analysis.result is original
    assert button(app, "Explain selected record — binary").disabled
    button(app, "Prepare export").click().run()
    assert app.session_state.local_analysis.prepared_export


def test_worker_failure_message_and_cross_session_isolation(resources, monkeypatch):
    first = analyzed(run(), payload(valid_frame(4)))
    second = run()
    def fail(*_): raise RuntimeError("PRIVATE OBSERVED VALUES")
    monkeypatch.setattr(service, "request_explanations", fail)
    original = first.session_state.local_analysis.result
    button(first, "Explain selected record — binary").click().run()
    assert service.FAILURE_MESSAGE in text(first) and "PRIVATE OBSERVED VALUES" not in text(first)
    assert first.session_state.local_analysis.result is original
    assert not second.session_state.local_analysis.explanations
    assert not first.exception


def sample_page(root):
    from cids.dashboard.app import render_single_page
    render_single_page("sample", root)


def test_clean_clone_sample_preview_and_download_need_no_pack(evidence_repo, monkeypatch, local_options):
    (evidence_repo / "samples").mkdir()
    shutil.copy2(ROOT / SAMPLE_FILE, evidence_repo / SAMPLE_FILE)
    monkeypatch.delenv(er.RESOURCE_ENV, raising=False)
    app = AppTest.from_function(sample_page, args=(evidence_repo,)).run()
    assert not app.exception and not app.dataframe
    assert "non-realistic" in text(app) and "not benchmark evidence" in text(app)
    assert len(app.get("download_button")) == 1
    button(app, "Preview synthetic sample").click().run()
    assert len(app.dataframe[0].value) == 8
    assert "event_time" not in app.dataframe[0].value and "label" not in app.dataframe[0].value
    assert not (evidence_repo / "artifacts").exists()


def test_evidence_mode_with_configured_resource_does_not_read_backgrounds(evidence_repo):
    code = '''
import sys
from pathlib import Path
from streamlit.testing.v1 import AppTest
from cids.dashboard.app import PAGE_KEYS
from cids.workbench import explanation_resources
explanation_resources.load_resources = lambda *_: (_ for _ in ()).throw(AssertionError("resource read on default navigation"))
for key in PAGE_KEYS:
    app = AppTest.from_string("from cids.dashboard.app import render_single_page; render_single_page(%r, %r)" % (key, sys.argv[1]), default_timeout=60).run()
    assert not app.exception
assert "shap" not in sys.modules and "cids.workbench.inference" not in sys.modules
'''
    result = subprocess.run([sys.executable, "-c", code, str(evidence_repo)], cwd=ROOT,
                            env={**os.environ, "PYTHONPATH": "src", er.RESOURCE_ENV: "c" * 64, "CIDS_MODEL_PACK_ID": "a" * 64},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


from test_explanation_resources import resource_fixture
from cids.workbench import model_pack


@pytest.mark.skipif(model_pack.current_runtime() != model_pack.EXPECTED_RUNTIME, reason="Phase 4 verified UI worker requires pinned model runtime")
def test_real_selected_action_uses_isolated_worker_after_streamlit_bootstrap(tmp_path, monkeypatch, resource_fixture):
    pytest.importorskip("shap", reason="Phase 4 verified UI worker requires pinned SHAP")
    import json
    from cids.workbench.analysis import PACK_ROOT, PACK_ENV
    from test_workbench_inference import pack_directory, synthetic_artifact
    from test_phase4_explanations import WORKER_FIXTURE
    pack_root = tmp_path / PACK_ROOT
    pack_root.mkdir(parents=True)
    directory = pack_directory(pack_root, monkeypatch, {t: synthetic_artifact(t) for t in ("binary", "multiclass")})
    manifest = json.loads((directory / "manifest.json").read_bytes())
    f = resource_fixture
    f.manifest.update({k: manifest[k] for k in ("model_pack_id", "artifacts", "runtime")})
    identifier = f.publish().name
    monkeypatch.setenv(PACK_ENV, directory.name)
    monkeypatch.setenv(er.RESOURCE_ENV, identifier)
    original = service._isolated
    calls = []
    def isolate(request, seconds):
        calls.append(json.loads(request)["task"])
        return original(request, seconds, command=[sys.executable, str(WORKER_FIXTURE), "representative"])
    monkeypatch.setattr(service, "_isolated", isolate)
    app = analyzed(run(tmp_path), payload(valid_frame(4)))
    original_analysis = app.session_state.local_analysis.result
    button(app, "Explain selected record — binary").click().run(timeout=60)
    assert "explanation_status: available · task: binary" in text(app)
    assert len(app.session_state.local_analysis.explanations["binary"].contributions) == 42
    button(app, "Explain selected record — multiclass").click().run(timeout=60)
    assert "explanation_status: available · task: multiclass" in text(app)
    app.run()
    assert calls == ["binary", "multiclass"] and app.session_state.local_analysis.result is original_analysis
    assert not app.exception


def test_global_model_reliance_load_is_explicit_and_missing_task_is_honest(resource_fixture, monkeypatch):
    import json
    from cids.workbench import analysis
    from cids.datasets.unsw_nb15 import FEATURE_COLUMNS
    f = resource_fixture
    value = {"task": "binary", "policy": er.GLOBAL_POLICY, "sample_rows": 8, "class_labels": [0, 1],
             "baseline_score": .25, "features": [{"feature": feature, "mean_score_decrease": .1, "std_score_decrease": .01} for feature in FEATURE_COLUMNS]}
    name = "binary-global.json"
    f.files[name] = er.canonical(value)
    f.manifest["tasks"]["binary"].update(global_sample_id_sha256="c" * 64,
                                        **{"global": {"filename": name, "sha256": er.digest_bytes(f.files[name]), "size_bytes": len(f.files[name]), "rows": 8}})
    identifier = f.publish().name
    monkeypatch.setenv(analysis.PACK_ENV, f.pack["model_pack_id"])
    monkeypatch.setenv(er.RESOURCE_ENV, identifier)
    monkeypatch.setattr(analysis, "preflight_binding", lambda *_: SimpleNamespace(manifest=f.pack))
    calls = []
    original = er.load_resources
    def load(*args):
        calls.append("load")
        return original(*args)
    monkeypatch.setattr(er, "load_resources", load)
    app = AppTest.from_string("from cids.dashboard.app import render_single_page; render_single_page('explainability', %r)" % str(f.repo)).run()
    app.run()
    assert calls == [] and "has not been requested" in text(app)
    button(app, "Load configured global model reliance").click().run()
    assert calls == ["load"] and not app.exception
    assert "no offline global evidence was prepared" in text(app)
    assert "in-development reliance" in text(app) and "zero_division=0" in text(app)
    assert len(app.dataframe[-1].value) == 42


def test_global_reliance_refuses_builtin_data_export(resources, monkeypatch):
    from streamlit import config
    config.set_option("client.disableDataExport", False)
    monkeypatch.setattr(er, "load_resources", lambda *_: pytest.fail("must not load resources with built-in export enabled"))
    app = AppTest.from_string("from cids.dashboard.app import render_single_page; render_single_page('explainability')").run()
    assert not app.exception
    assert "built-in table data export must be disabled" in text(app)
    assert "Load configured global model reliance" not in [b.label for b in app.button]


def test_uploaded_record_identity_is_plain_text_in_explanation(resources):
    malicious = "![remote](https://example.invalid/private-image)"
    data = valid_frame(4).assign(id=[malicious, "b", "c", "d"])
    app = analyzed(run(), payload(data))
    button(app, "Explain selected record — binary").click().run()
    assert not app.exception
    assert any(malicious in e.value for e in app.text)
    assert "example.invalid" not in text(app)
