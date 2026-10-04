"""Phase 3D AppTest actions with synthetic rows and session-owned derivatives."""
import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from test_dashboard_analysis import (available, local_options, run, analyzed, upload,
                                     button, select, text)
from test_workbench_contracts import valid_frame, payload
from cids.workbench import analysis, inference


def multi(app, label):
    return next(w for w in app.multiselect if w.label == label)


def slider(app):
    return next(w for w in app.slider if w.label.startswith("Simulation"))


def labeled(binary=True, family=True, rows=4):
    frame = valid_frame(rows)
    if binary:
        frame["label"] = [i % 2 for i in range(rows)]
    if family:
        frame["attack_cat"] = ["normal" if i % 2 == 0 else "generic" for i in range(rows)]
    return frame


@pytest.mark.parametrize("binary,family", [(False, False), (True, False), (False, True), (True, True)])
def test_truth_combinations_gate_controls_and_independent_family(available, binary, family):
    app = analyzed(run(), payload(labeled(binary, family)))
    assert bool(app.slider) == binary
    labels = [w.label for w in app.multiselect]
    assert ("Binary review categories" in labels) == binary
    assert ("Independent family review categories" in labels) == family
    table = app.dataframe[2].value
    assert ("Binary review category" in table) == binary
    assert ("Independent family review" in table) == family
    if family:
        assert table["Independent family review"].tolist() == ["misclassified", "misclassified", "misclassified", "correct"]
    assert app.session_state.local_analysis.prepared_export is None
    assert not app.get("download_button")
    assert select(app, "Export format").value == "JSON"
    assert available == ["load", "infer"]


def test_simulation_full_sample_reset_no_mutation_no_loading(available):
    app = analyzed(run(), payload(labeled()))
    original = app.session_state.local_analysis.result
    assert slider(app).value == .5
    assert app.session_state.local_analysis.simulation.decisions == (0, 1, 1, 1)
    multi(app, "Binary review categories").set_value(["FP"]).run()
    assert len(app.dataframe[2].value) == 1
    slider(app).set_value(.95).run()
    assert app.session_state.local_analysis.simulation.decisions == (0, 0, 0, 0)
    assert "Full current uploaded sample only" in text(app)
    button(app, "Reset simulation to baseline").click().run()
    assert slider(app).value == .5 and app.session_state.local_analysis.simulation.threshold == .5
    assert app.session_state.local_analysis.result is original
    assert available == ["load", "infer"]
    assert "not_requested" in text(app)
    assert any("Denominator" in df.value for df in app.dataframe)


def test_explicit_scoped_export_allowlist_simulation_download_and_context_reset(available, monkeypatch):
    import streamlit as st
    original_download = st.download_button
    filenames = []
    def download(*args, **kwargs):
        filenames.append(kwargs["file_name"])
        return original_download(*args, **kwargs)
    monkeypatch.setattr(st, "download_button", download)
    app = analyzed(run(), payload(labeled().assign(id=["=1+1", "b", "c", "d"])))
    assert not app.get("download_button")
    multi(app, "Queue bands").set_value(["review"]).run()
    select(app, "Export scope").set_value("Current filtered review").run()
    next(w for w in app.checkbox if w.label == "Include ephemeral simulation in export").check().run()
    assert not app.get("download_button")
    button(app, "Prepare export").click().run()
    assert not app.exception and len(app.get("download_button")) == 1
    doc = json.loads(app.session_state.local_analysis.prepared_export)
    assert doc["export_scope"] == "current_filtered_review" and doc["record_count"] == 1
    assert doc["records"][0]["record_id"] == "d" and doc["records"][0]["record_sequence"] == 4
    assert doc["simulation"]["sample_metrics"]["record_count"] == 4
    assert "dur" not in doc["records"][0]
    assert doc["simulation"]["comparison_rule"].startswith("attack_model_score >")
    # A format change discards both bytes and the old download widget.
    select(app, "Export format").set_value("CSV").run()
    assert app.session_state.local_analysis.prepared_export is None and not app.get("download_button")
    select(app, "Export scope").set_value("Full analysis").run()
    button(app, "Prepare export").click().run()
    assert b"'=1+1" in app.session_state.local_analysis.prepared_export
    proto = app.get("download_button")[0].proto
    assert filenames[-1] == "cids-review.csv" and proto.url.endswith(".csv")
    assert "private.csv" not in proto.url
    slider(app).set_value(.95).run()
    assert not app.get("download_button") and app.session_state.local_analysis.prepared_export is None
    assert available == ["load", "infer"]


@pytest.mark.parametrize("transition", ["replacement", "removal", "clear", "invalid", "failure", "pack", "reanalyze", "export_guard"])
def test_lifecycle_clears_simulation_export_and_downloads(available, monkeypatch, transition):
    app = analyzed(run(), payload(labeled()))
    slider(app).set_value(.9).run()
    button(app, "Prepare export").click().run()
    assert app.session_state.local_analysis.prepared_export and app.get("download_button")
    if transition == "replacement":
        upload(app, payload(labeled(rows=2)))
    elif transition == "invalid":
        upload(app, b"invalid")
    elif transition == "removal":
        app.file_uploader[0].clear().run()
    elif transition == "clear":
        button(app, "Clear analysis").click().run()
    elif transition == "pack":
        monkeypatch.setenv(analysis.PACK_ENV, "b" * 64)
        app.run()
    elif transition == "failure":
        def fail(*_):
            raise RuntimeError("PRIVATE")
        monkeypatch.setattr(inference, "infer", fail)
        button(app, "Analyze CSV").click().run()
    elif transition == "export_guard":
        from streamlit import config
        config.set_option("client.disableDataExport", False)
        app.run()
    else:
        button(app, "Analyze CSV").click().run()
    state = app.session_state.local_analysis
    assert not app.exception and state.prepared_export is None and not app.get("download_button")
    if transition == "reanalyze":
        assert state.simulation.threshold == .5 and slider(app).value == .5
    else:
        assert state.simulation is None and not app.slider
    assert "PRIVATE" not in text(app)


def test_cross_session_derivatives_are_isolated(available):
    first = analyzed(run(), payload(labeled()))
    slider(first).set_value(.9).run()
    button(first, "Prepare export").click().run()
    second = analyzed(run(), payload(labeled(rows=2)))
    assert second.session_state.local_analysis.prepared_export is None
    assert second.session_state.local_analysis.simulation.threshold == .5
    button(second, "Clear analysis").click().run()
    first.run()
    assert first.session_state.local_analysis.prepared_export
    assert first.session_state.local_analysis.simulation.threshold == .9
    assert len(first.get("download_button")) == 1


def test_filtered_order_pagination_detail_and_export_preserve_identity(available):
    frame = labeled(rows=201).assign(id=[f"id-{i}" for i in range(201)])
    app = analyzed(run(), payload(frame))
    select(app, "Review order").set_value("Attack model score (uncalibrated), descending").run()
    select(app, "Record page").set_value(2).run()
    assert len(app.dataframe[2].value) == 1
    selected = select(app, "Record detail").value
    assert app.dataframe[3].value["Record ID"].tolist() == [f"id-{selected}"]
    assert app.dataframe[4].value.iloc[0]["Value"] == str(frame.iloc[selected].dur)
    select(app, "Export scope").set_value("Current filtered review").run()
    button(app, "Prepare export").click().run()
    doc = json.loads(app.session_state.local_analysis.prepared_export)
    assert doc["record_count"] == 201  # All pages, not just the last page.
    assert [r["record_sequence"] for r in doc["records"][:4]] == [2, 3, 6, 7]
    multi(app, "Binary review categories").set_value([]).run()
    assert not app.get("download_button")
    button(app, "Prepare export").click().run()
    assert json.loads(app.session_state.local_analysis.prepared_export)["record_count"] == 0
    assert available == ["load", "infer"]


def test_uploaded_single_class_unavailable_rates_are_explained(available):
    app = analyzed(run(), payload(valid_frame(4).assign(label=0)))
    reports = [df.value for df in app.dataframe if "Uploaded-sample metric" in df.value]
    assert len(reports) == 2
    for report in reports:
        recall = report[report["Uploaded-sample metric"] == "recall"].iloc[0]
        assert recall["Value"] == "Unavailable" and recall["Denominator"] == 0
        assert "denominator is zero" in recall["Explanation"]
