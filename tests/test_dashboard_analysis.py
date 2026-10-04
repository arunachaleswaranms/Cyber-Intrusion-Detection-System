"""Phase 3C UI interactions in the pinned dashboard environment."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest
from streamlit import config

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from cids.workbench import analysis, inference, model_pack
from test_workbench_analysis import PACK_ID, fake_pack, record
from test_workbench_contracts import valid_frame, payload

ROOT = Path(__file__).parents[1]


def page(root):
    from cids.dashboard.app import render_single_page
    render_single_page("analysis", root)


def text(app):
    return "\n".join(str(e.value) for kind in ("caption", "markdown", "info", "warning", "error", "title") for e in getattr(app, kind))


def button(app, label):
    return next(b for b in app.button if b.label == label)


def select(app, label):
    return next(b for b in app.selectbox if b.label == label)


@pytest.fixture(autouse=True)
def local_options(monkeypatch):
    monkeypatch.delenv(analysis.PACK_ENV, raising=False)
    saved = {key: config.get_option(key) for key in ("server.address", "browser.gatherUsageStats", "client.disableDataExport")}
    config.set_option("server.address", "127.0.0.1")
    config.set_option("browser.gatherUsageStats", False)
    config.set_option("client.disableDataExport", True)
    yield
    for key, value in saved.items():
        config.set_option(key, value)


def run(root=ROOT):
    app = AppTest.from_function(page, args=(root,), default_timeout=60).run()
    assert not app.exception, [e.value for e in app.exception]
    return app


@pytest.fixture
def available(monkeypatch):
    monkeypatch.setenv(analysis.PACK_ENV, PACK_ID)
    manifest = {key: {} for key in ("runtime", "contracts", "artifacts")}
    manifest.update(model_pack_id=PACK_ID, provenance_type="maintainer_final_v2",
                    created_at_utc="2026-10-04T00:00:00Z", creation_config_sha256="b" * 64)
    monkeypatch.setattr(analysis, "preflight_binding", lambda *_: SimpleNamespace(manifest=manifest))
    from cids.dashboard.views import analysis as view
    monkeypatch.setattr(view, "preflight_binding", lambda *_: SimpleNamespace(manifest=manifest))
    calls = []
    def load(_):
        calls.append("load")
        return fake_pack()
    def infer(pack, data):
        calls.append("infer")
        outputs = [("normal", "generic", .1), ("attack", "normal", .95), ("attack", "generic", .95), ("attack", "generic", .8)]
        return tuple(record(str(row.id), *outputs[i % 4], time=row.get("event_time")) for i, row in data.frame.iterrows())
    monkeypatch.setattr(inference, "load_model_pack", load)
    monkeypatch.setattr(inference, "infer", infer)
    return calls


def upload(app, data):
    app.file_uploader[0].set_value(("../../private.csv", data, "text/csv")).run()
    assert not app.exception
    return app


def analyzed(app, data):
    upload(app, data)
    button(app, "Analyze CSV").click().run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def test_unconfigured_analysis_has_no_model_controls_or_upload():
    app = run()
    assert "no registered pack is configured" in text(app)
    assert not app.file_uploader and not app.text_input and not app.selectbox


@pytest.mark.parametrize("pack_id", ["../untrusted", "f" * 64])
def test_invalid_or_missing_pack_degrades_cleanly(monkeypatch, tmp_path, pack_id):
    monkeypatch.setenv(analysis.PACK_ENV, pack_id)
    app = run(tmp_path)
    assert "Analysis unavailable" in text(app) and not app.file_uploader


def test_runtime_failure_is_clean(monkeypatch):
    def fail(_):
        raise model_pack.ModelPackError("runtime is PRIVATE")
    monkeypatch.setenv(analysis.PACK_ENV, PACK_ID)
    monkeypatch.setattr(model_pack, "preflight_model_pack", fail)
    app = run()
    assert "runtime failed verification" in text(app) and "PRIVATE" not in text(app)


def test_explicit_action_and_display_reruns(available):
    app = run()
    assert button(app, "Analyze CSV").disabled
    upload(app, payload(valid_frame(4)))
    assert available == [] and not app.dataframe
    button(app, "Analyze CSV").click().run()
    assert available == ["load", "infer"]
    app.run()
    app.multiselect[0].set_value(["review"]).run()
    assert available == ["load", "infer"]
    assert "Matching records: 1 of 4" in text(app)
    assert app.dataframe[2].value["Record ID"].tolist() == ["record-000004"]
    button(app, "Analyze CSV").click().run()
    assert available == ["load", "infer", "load", "infer"]


def test_outputs_labels_filters_and_detail_alignment(available):
    frame = valid_frame(4).assign(id=["001", "002", "003", "004"], event_time=[
        "2026-01-04T05:30:00+05:30", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"])
    app = analyzed(run(), payload(frame))
    select(app, "Review order").set_value("Timestamp (UTC), ascending").run()
    table = app.dataframe[2].value
    assert table["Record ID"].tolist() == ["002", "003", "004", "001"]
    assert table["Independent raw attack-family prediction"].tolist() == ["normal", "generic", "generic", "generic"]
    assert "Attack model score (uncalibrated)" in table and "Family model score (uncalibrated)" in table
    assert table["Timestamp (UTC)"].iloc[-1] == "2026-01-04T00:00:00Z"
    select(app, "Record detail").set_value(0).run()
    assert app.dataframe[3].value["Record ID"].tolist() == ["001"]
    assert app.dataframe[4].value.iloc[0]["Value"] == str(frame.iloc[0]["dur"])
    app.checkbox[0].check().run()
    assert "Matching records: 2 of 4" in text(app)
    assert "binary attack + raw family normal only" in text(app)
    assert "Timestamp view" in text(app)
    assert not app.slider and not app.get("download_button")
    assert not app.text_input and not app.number_input
    assert [u.label for u in app.file_uploader] == ["Feature CSV"]
    assert "explanation_status: not_requested" in text(app)


def test_sequence_wording_and_warning_before_scoring(available, monkeypatch):
    original = inference.infer
    def score(pack, data):
        # The adapter's before_scoring callback must have emitted the warning.
        assert data.frame.proto.eq("unknown").all()
        return original(pack, data)
    monkeypatch.setattr(inference, "infer", score)
    app = analyzed(run(), payload(valid_frame(4).assign(proto="unknown")))
    assert "Record sequence: original CSV row order" in text(app)
    assert "Timestamp view" not in text(app) and "timeline" not in text(app).lower()
    assert "Out-of-vocabulary" in text(app)
    warnings = app.dataframe[0].value
    assert warnings.rows.tolist() == [4, 4]
    assert warnings.task.tolist() == ["binary", "multiclass"]


@pytest.mark.parametrize("data", [b"invalid", b"\x1f\x8bbad", b"x" * 10485761,
                                  payload(valid_frame().assign(event_time="PRIVATE_SECRET")),
                                  payload(valid_frame().assign(attack_cat="PRIVATE_SECRET")),
                                  payload(valid_frame().assign(attack_cat="normal", label=1))],
                         ids=["bad-header", "compressed", "oversized", "timestamp", "family", "labels"])
def test_invalid_upload_clears_results_without_scoring(available, data):
    app = analyzed(run(), payload(valid_frame(4)))
    assert app.dataframe
    upload(app, data)
    assert not app.dataframe and available == ["load", "infer"]
    assert "PRIVATE_SECRET" not in text(app)
    assert app.error or app.file_uploader[0].value is None
    assert button(app, "Analyze CSV").disabled


@pytest.mark.parametrize("transition", ["replacement", "removal", "clear", "failure", "pack"])
def test_ui_transitions_remove_counts_selections_and_results(available, monkeypatch, transition):
    app = analyzed(run(), payload(valid_frame(4)))
    if transition == "replacement":
        upload(app, payload(valid_frame(2)))
    elif transition == "removal":
        app.file_uploader[0].clear().run()
    elif transition == "clear":
        button(app, "Clear analysis").click().run()
        assert app.file_uploader[0].value is None
        assert button(app, "Analyze CSV").disabled
    elif transition == "pack":
        monkeypatch.delenv(analysis.PACK_ENV)
        # Restore adapter so disabled configuration is actually checked.
        from cids.dashboard.views import analysis as view
        def unavailable(*_):
            raise analysis.AnalysisUnavailable("Analysis unavailable")
        monkeypatch.setattr(view, "preflight_binding", unavailable)
        app.run()
    else:
        def fail(*_):
            raise RuntimeError("PRIVATE_SECRET")
        monkeypatch.setattr(inference, "infer", fail)
        button(app, "Analyze CSV").click().run()
        assert "Analysis failed" in text(app) and "PRIVATE_SECRET" not in text(app)
    assert not app.exception
    assert not app.dataframe and not app.metric
    assert "Record detail" not in [s.label for s in app.selectbox]


def test_two_apptest_sessions_are_isolated(available):
    first = analyzed(run(), payload(valid_frame(4)))
    second = run()
    assert not second.dataframe and second.file_uploader[0].value is None
    button(second, "Clear analysis").click().run()
    first.run()
    assert first.dataframe and available == ["load", "infer"]


def test_queue_and_detail_rendering_are_bounded(available):
    app = analyzed(run(), payload(valid_frame(201)))
    assert len(app.dataframe[2].value) == 200
    select(app, "Record page").set_value(2).run()
    assert app.dataframe[2].value["Record ID"].tolist() == ["record-000201"]
    assert len(select(app, "Record detail").options) == 1
    assert len(app.dataframe[4].value) == 42


def test_clean_evidence_navigation_does_not_import_inference(evidence_repo):
    assert not (evidence_repo / "artifacts").exists()
    assert not list(evidence_repo.rglob("*.csv"))
    code = '''
from pathlib import Path
from streamlit.testing.v1 import AppTest
from cids.dashboard.app import PAGE_KEYS
import joblib, pickle, sys
original_open = Path.open
def guarded_open(self, *args, **kwargs):
    assert self.suffix not in ('.csv', '.joblib'), 'raw data/model access'
    return original_open(self, *args, **kwargs)
Path.open = guarded_open
def refuse(*args, **kwargs):
    raise AssertionError('deserialization forbidden')
joblib.load = pickle.load = pickle.loads = refuse
for key in PAGE_KEYS:
    script = "from cids.dashboard.app import render_single_page; render_single_page(%r, %r)" % (key, sys.argv[1])
    app = AppTest.from_string(script, default_timeout=60).run()
    assert not app.exception
assert 'cids.workbench.inference' not in sys.modules
assert 'shap' not in sys.modules
'''
    result = subprocess.run([sys.executable, "-c", code, str(evidence_repo)], cwd=ROOT,
                            env={**os.environ, "PYTHONPATH": "src", analysis.PACK_ENV: PACK_ID}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(model_pack.current_runtime() != model_pack.EXPECTED_RUNTIME,
                    reason="Phase 3C verified UI inference requires pinned model runtime")
def test_ui_uses_actual_verified_loader_and_inference(tmp_path, monkeypatch):
    # Real fitted synthetic artifacts and hardened services; only the trust-anchor
    # fixture is substituted. No benchmark data or original artifact is touched.
    from test_workbench_inference import synthetic_artifact, pack_directory
    artifacts = {task: synthetic_artifact(task) for task in ("binary", "multiclass")}
    pack_root = tmp_path / analysis.PACK_ROOT
    pack_root.mkdir(parents=True)
    directory = pack_directory(pack_root, monkeypatch, artifacts)
    monkeypatch.setenv(analysis.PACK_ENV, directory.name)
    data = payload(valid_frame(4).assign(id=["01", "02", "03", "04"]))
    direct = inference.infer(inference.load_model_pack(directory), analysis.parse_inference_csv(data))
    app = analyzed(run(tmp_path), data)
    actual = app.session_state.local_analysis.current_result().records
    assert actual == direct
    assert not app.error


@pytest.mark.skipif(model_pack.current_runtime() != model_pack.EXPECTED_RUNTIME,
                    reason="Phase 3C real-pack UI integration requires pinned model runtime")
def test_local_original_pack_ui_matches_direct_training_inference(monkeypatch):
    """Optional local gate: exact training source, at most 16 parsed rows."""
    import hashlib
    import pandas as pd
    training_name = os.environ.get("CIDS_PHASE3B_TRAINING_CSV")
    if not training_name:
        pytest.skip("verified local training CSV was not supplied for Phase 3C UI integration")
    training = Path(training_name)
    assert training.name == "cids-phase3b-training.csv"
    assert training.stat().st_size == 32293018
    digest = hashlib.sha256()
    with training.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    assert digest.hexdigest() == "bec7dd5ec88dc2a0ccc7a07879d338395ed7421750f675fd0339e07dfe0648fa"
    original_id = "e2d4f329b894a1b68b70af377ffc94441e02d024de27e7c351384d3e25692b18"
    directory = ROOT / analysis.PACK_ROOT / original_id
    if not directory.is_dir():
        pytest.skip("registered original pack is unavailable for Phase 3C UI integration")
    from cids.datasets.unsw_nb15 import FEATURE_COLUMNS
    rows = pd.read_csv(training, nrows=16, usecols=["id", *FEATURE_COLUMNS], dtype={"id": str})
    data = payload(rows)
    direct = inference.infer(inference.load_model_pack(directory), analysis.parse_inference_csv(data))
    monkeypatch.setenv(analysis.PACK_ENV, original_id)
    app = analyzed(run(), data)
    result = app.session_state.local_analysis.current_result()
    assert result.records == direct and len(result.records) == 16
    assert not app.error
    app.run()
    assert app.session_state.local_analysis.current_result() is result


def test_analysis_refuses_builtin_data_export_and_clears_prior_results(available):
    app = analyzed(run(), payload(valid_frame(4)))
    assert app.dataframe
    config.set_option("client.disableDataExport", False)
    app.run()
    assert not app.exception and not app.dataframe and not app.file_uploader
    assert "table data export must be disabled" in text(app)
    assert app.session_state.local_analysis.current_result() is None
    assert available == ["load", "infer"]
