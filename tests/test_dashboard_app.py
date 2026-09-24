"""Streamlit smoke and degraded-state tests for the evidence dashboard.

Skipped when Streamlit is not installed (the base and reproduction CI jobs);
run in the environment built from requirements-dashboard.txt.
"""

import ast
import json
import pickle
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("altair")

from streamlit.testing.v1 import AppTest  # noqa: E402

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from cids.dashboard import charts  # noqa: E402
from cids.dashboard.app import PAGE_KEYS, exposure_problems  # noqa: E402
from cids.workbench.catalog import load_catalog  # noqa: E402
from cids.workbench.confusion import confusion_matrix  # noqa: E402
from cids.workbench.formatting import format_ratio  # noqa: E402
from cids.workbench.reporting import (  # noqa: E402
    HEADLINE_METRICS,
    family_detection_table,
    per_class_table,
    stage_comparisons,
)

TIMEOUT = 60


def _page_script(key, repo_root):
    from cids.dashboard.app import render_single_page

    render_single_page(key, repo_root)


def _run_page(key, repo_root=REPO_ROOT):
    app = AppTest.from_function(
        _page_script, args=(key, repo_root), default_timeout=TIMEOUT
    )
    return app.run()


def _text(app) -> str:
    parts = []
    for kind in ("markdown", "caption", "error", "warning", "info", "success", "title"):
        parts.extend(str(element.value) for element in getattr(app, kind))
    return "\n".join(parts)


@pytest.fixture
def streamlit_options():
    """Set Streamlit options for one test and restore them afterwards."""
    from streamlit import config

    saved = {}

    def apply(**options):
        for key, value in options.items():
            name = key.replace("__", ".")
            saved.setdefault(name, config.get_option(name))
            config.set_option(name, value)

    yield apply
    for name, value in saved.items():
        config.set_option(name, value)


def test_entry_point_renders_overview_without_exceptions(streamlit_options):
    # Independent of the working directory's .streamlit/config.toml.
    streamlit_options(server__address="127.0.0.1", browser__gatherUsageStats=False)
    app = AppTest.from_file(
        str(REPO_ROOT / "dashboard/app.py"), default_timeout=TIMEOUT
    ).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["CIDS evidence dashboard"]
    assert not app.error


@pytest.mark.parametrize("key", PAGE_KEYS)
def test_every_page_renders_from_committed_evidence(key):
    app = _run_page(key)

    assert not app.exception, [e.value for e in app.exception]
    assert not app.error, [e.value for e in app.error]
    assert "Offline research artifact, not a production IDS" in _text(app)


@pytest.mark.parametrize(
    ("key", "charts_expected"), [("binary", 2), ("families", 2), ("overview", 2)]
)
def test_result_pages_pair_charts_with_exact_value_tables(key, charts_expected):
    app = _run_page(key)

    assert len(app.get("vega_lite_chart")) == charts_expected
    assert len(app.dataframe) >= charts_expected


def test_official_results_carry_the_official_test_stage_badge():
    for key in ("binary", "families"):
        assert ":violet-badge[OFFICIAL TEST]" in _text(_run_page(key))


@pytest.mark.parametrize(
    ("key", "task"), [("binary", "binary"), ("families", "multiclass")]
)
def test_headline_tiles_show_recorded_official_values(key, task):
    official = load_catalog().official.report["tasks"][task]["official_test_metrics"]
    tiles = {metric.label: metric.value for metric in _run_page(key).metric}

    assert tiles["Macro F1"] == format_ratio(official["f1_macro"])
    assert tiles["Balanced accuracy"] == format_ratio(official["balanced_accuracy"])
    for metric in HEADLINE_METRICS[task]:
        assert format_ratio(official[metric]) in tiles.values()


def test_overview_labels_both_evaluation_stages_and_the_refit_caveat():
    text = _text(_run_page("overview"))

    assert ":blue-badge[VALIDATION]" in text
    assert ":violet-badge[OFFICIAL TEST]" in text
    assert "not a like-for-like remeasurement" in text
    assert "reproduction" in text


def test_explainability_never_presents_feature_importance():
    app = _run_page("explainability")
    text = _text(app)

    assert "not available in evidence mode" in text
    assert "Not causality" in text
    assert not app.get("vega_lite_chart")


def test_missing_gate_evidence_degrades_explainability_only(evidence_repo):
    shutil.rmtree(evidence_repo / "results/v2.1")

    explain = _run_page("explainability", evidence_repo)
    overview = _run_page("overview", evidence_repo)

    assert not explain.exception and not overview.exception
    assert "v2.1 explanation-gate report is missing" in _text(explain)
    assert "Partial evidence" in _text(overview)
    assert "Macro F1" in [metric.label for metric in overview.metric]


@pytest.mark.parametrize("key", PAGE_KEYS)
def test_missing_official_evidence_blocks_metrics_on_every_page(evidence_repo, key):
    shutil.rmtree(evidence_repo / "results/v2.0")

    app = _run_page(key, evidence_repo)

    assert not app.exception
    assert not [m for m in app.metric if m.label == "Macro F1"]
    if key not in {"explainability", "provenance"}:
        assert "never substitutes sample or recomputed values" in _text(app)


def test_tampered_official_evidence_is_shown_as_an_integrity_failure(evidence_repo):
    path = evidence_repo / "results/v2.0/official-test-results.json"
    path.write_bytes(
        path.read_bytes().replace(b'"evaluated_once"', b'"evaluated_twice"', 1)
    )

    app = _run_page("binary", evidence_repo)
    errors = " ".join(str(e.value) for e in app.error)

    assert not app.exception
    assert "failed verification" in errors and "SHA-256 mismatch" in errors
    assert not app.metric


def test_unbound_selection_record_hides_validation_numbers(evidence_repo):
    path = evidence_repo / "configs/v2-model-selection-v1.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["selected"]["binary"]["selected_validation_metrics"]["f1_macro"] = 0.99
    path.write_text(json.dumps(value), encoding="utf-8")

    app = _run_page("overview", evidence_repo)
    text = _text(app)

    assert not app.exception
    assert "Validation metrics are hidden" in text
    assert "0.9900" not in text


@pytest.mark.parametrize(
    ("address", "telemetry", "expected"),
    [
        ("127.0.0.1", False, []),
        ("localhost", False, []),
        ("", False, ["all interfaces"]),
        ("0.0.0.0", False, ["0.0.0.0"]),
        ("127.0.0.1", True, ["telemetry"]),
    ],
)
def test_exposure_policy(address, telemetry, expected):
    problems = exposure_problems(address, telemetry)

    assert len(problems) == len(expected)
    for problem, fragment in zip(problems, expected):
        assert fragment in problem


@pytest.mark.parametrize(
    "options",
    [
        {"server__address": "0.0.0.0", "browser__gatherUsageStats": False},
        {"server__address": "127.0.0.1", "browser__gatherUsageStats": True},
    ],
)
def test_entry_point_refuses_to_render_when_exposed(streamlit_options, options):
    streamlit_options(**options)
    app = AppTest.from_file(
        str(REPO_ROOT / "dashboard/app.py"), default_timeout=TIMEOUT
    ).run()

    assert not app.exception
    assert "Refusing to render" in " ".join(str(e.value) for e in app.error)
    assert not app.metric


def test_evidence_contract_violation_is_shown_on_the_page(monkeypatch):
    from cids.dashboard.views import binary
    from cids.workbench.integrity import EvidenceError

    def violate(catalog):
        raise EvidenceError("binary per-family detection rates are missing")

    monkeypatch.setattr(binary, "_families", violate)

    app = _run_page("binary")

    assert not app.exception
    assert "violated a display contract" in " ".join(str(e.value) for e in app.error)


def test_gate_row_claim_requires_verified_gate(evidence_repo):
    assert "validation rows per task" in _text(_run_page("explainability"))

    shutil.rmtree(evidence_repo / "results/v2.1")

    assert "validation rows per task" not in _text(
        _run_page("explainability", evidence_repo)
    )


def test_pages_render_without_deserializing_any_model(monkeypatch):
    import joblib

    def refuse(*args, **kwargs):
        raise AssertionError("evidence mode must not deserialize artifacts")

    monkeypatch.setattr(joblib, "load", refuse)
    monkeypatch.setattr(pickle, "load", refuse)
    monkeypatch.setattr(pickle, "loads", refuse)

    for key in PAGE_KEYS:
        assert not _run_page(key).exception


def test_evidence_services_do_not_import_streamlit_or_shap():
    code = (
        "import sys; sys.path.insert(0, 'src');"
        "from cids.workbench import catalog, reporting, confusion, formatting;"
        "c = catalog.load_catalog(); confusion.consistency_checks(c.official);"
        "print(sorted(m for m in ('streamlit', 'shap', 'altair') if m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "[]"


def test_dashboard_source_contains_no_recorded_metric_literals():
    """Recorded metric values must reach the UI from evidence, never from code."""
    catalog = load_catalog()
    values = []
    for task in catalog.official.report["tasks"].values():
        for value in task["official_test_metrics"].values():
            if isinstance(value, float):
                values.append(value)
        for entry in task["official_test_metrics"]["per_class"].values():
            values.extend(v for v in entry.values() if isinstance(v, float))
    for task in catalog.selection["selected"].values():
        values.extend(task["selected_validation_metrics"].values())
    literals = {f"{v:.4f}" for v in values if 0.01 < v < 0.99} | {
        f"{v * 100:.2f}" for v in values if 0.01 < v < 0.99
    }
    sources = [
        *sorted((REPO_ROOT / "src/cids/dashboard").rglob("*.py")),
        *(
            REPO_ROOT / "src/cids/workbench" / name
            for name in ("reporting.py", "confusion.py", "catalog.py")
        ),
    ]
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        text_constants = [
            node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
        ]
        for constant in text_constants:
            rendered = str(constant)
            hits = [literal for literal in literals if literal in rendered]
            assert not hits, f"{source.name} hardcodes recorded value(s) {hits}"


def test_chart_specs_build_for_committed_evidence():
    catalog = load_catalog()
    official = catalog.official
    palette = charts.LIGHT
    specs = [
        charts.confusion_heatmap(
            confusion_matrix(official, "binary"), palette, label_min_share=0
        ),
        charts.confusion_heatmap(
            confusion_matrix(official, "multiclass"), charts.DARK, label_min_share=0.05
        ),
        charts.precision_recall_dots(per_class_table(official, "multiclass"), palette),
        charts.miss_rate_bars(family_detection_table(official), palette),
        charts.stage_dumbbell(
            stage_comparisons(catalog.selection, official, "binary"), palette
        ),
    ]
    for spec in specs:
        rendered = spec.to_dict()
        assert rendered["$schema"].startswith(
            "https://vega.github.io/schema/vega-lite/"
        )
        # Streamlit's Vega-Lite renderer throws client-side on a null channel
        # scale, which AppTest cannot observe; forbid it in every layer.
        assert not list(_null_scales(rendered))


def _null_scales(node):
    if isinstance(node, dict):
        if "scale" in node and node["scale"] is None:
            yield node
        for value in node.values():
            yield from _null_scales(value)
    elif isinstance(node, list):
        for value in node:
            yield from _null_scales(value)
