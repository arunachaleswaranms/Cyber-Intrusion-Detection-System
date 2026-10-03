"""Phase 3B synthetic security tests; no official-test records or metrics."""

import ast
import hashlib
import io
import json
import os
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cids.config import load_experiment_config  # noqa: E402
from cids.datasets.split_unsw_nb15 import PreparedSplits  # noqa: E402
from cids.datasets.unsw_nb15 import ATTACK_FAMILIES, FEATURE_COLUMNS, NUMERIC_FEATURES, SCHEMA_VERSION  # noqa: E402
from cids.final_evaluation import FINAL_MODEL_ARTIFACT_VERSION, FinalModelArtifact  # noqa: E402
from cids.modeling.supervised import MODEL_ARTIFACT_VERSION, build_estimator, model_features_for_estimator  # noqa: E402
from cids.preprocessing import fit_preprocessor, transform_partition  # noqa: E402
from cids.workbench import model_pack  # noqa: E402
from cids.workbench.contracts import parse_inference_csv  # noqa: E402
from cids.workbench.inference import InferenceError, LoadedModelPack, infer, load_model_pack  # noqa: E402
from cids.workbench.registration import build_maintainer_final_manifest  # noqa: E402

pytestmark = pytest.mark.skipif(
    model_pack.current_runtime() != model_pack.EXPECTED_RUNTIME,
    reason="Phase 3B model tests require the pinned model runtime and libraries",
)


def synthetic_frame(rows=30):
    data = []
    for index in range(rows):
        row = {column: float(index % 10 + 1) for column in NUMERIC_FEATURES}
        row.update(id=f"dev-{index}", proto="tcp", service="-", state="FIN")
        row["attack_cat"] = ATTACK_FAMILIES[index % 10]
        row["label"] = int(row["attack_cat"] != "normal")
        data.append(row)
    return pd.DataFrame(data)


def synthetic_artifact(task):
    frame = synthetic_frame()
    digest = hashlib.sha256("\n".join(frame["id"]).encode()).hexdigest()
    report = {"task": task, "split_policy_version": "unsw-nb15-split-v1", "id_sha256": {"train": digest}}
    splits = PreparedSplits(frame, frame, frame, report)
    pre = fit_preprocessor(splits)
    config = load_experiment_config()
    estimator = build_estimator("hist_gradient_boosting", config["models"]["supervised"]["hist_gradient_boosting"], 42)
    estimator.fit(model_features_for_estimator("hist_gradient_boosting", transform_partition(pre, frame)), frame["label" if task == "binary" else "attack_cat"])
    metadata = {
        "artifact_version": FINAL_MODEL_ARTIFACT_VERSION,
        "source_artifact_version": MODEL_ARTIFACT_VERSION,
        **{key: value for key, value in model_pack.EXPECTED_CONTRACTS_BASE.items() if key != "preprocessor_version"},
        "split_policy_version": "unsw-nb15-split-v1",
        "task": task, "model_name": "hist_gradient_boosting", "seed": 42,
        "estimator_class": type(estimator).__name__,
        "estimator_parameters": estimator.get_params(deep=False),
        "training_scope": "prepared_train_plus_validation",
        "development_training_rows": len(frame), "development_training_id_sha256": digest,
        "official_test_rows": 1, "official_test_id_sha256": "a" * 64,
        "official_test_status": "evaluated_once", "fit_seconds": 0.1,
        "library_versions": model_pack.EXPECTED_RUNTIME["libraries"],
        "preprocessor": pre.metadata,
    }
    return FinalModelArtifact(FINAL_MODEL_ARTIFACT_VERSION, SCHEMA_VERSION, task, "hist_gradient_boosting", pre, estimator, metadata)


@pytest.fixture
def artifacts():
    return {task: synthetic_artifact(task) for task in ("binary", "multiclass")}


def pack_directory(tmp_path, monkeypatch, artifacts):
    payloads = {}
    for task, artifact in artifacts.items():
        buffer = io.BytesIO()
        joblib.dump(artifact, buffer)
        payloads[task] = buffer.getvalue()
    specs = {task: (hashlib.sha256(data).hexdigest(), len(data)) for task, data in payloads.items()}
    manifest = build_maintainer_final_manifest(
        artifacts=specs,
        acknowledged_at_utc="2026-10-01T00:00:00+00:00",
        created_at_utc="2026-10-01T00:00:00+00:00",
        creation_config_sha256=model_pack.EXPECTED_REGISTRATION_POLICY_SHA256,
    )
    root = tmp_path / manifest["model_pack_id"]
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(manifest))
    for task, data in payloads.items():
        (root / f"{task}.joblib").write_bytes(data)
    monkeypatch.setattr(model_pack, "load_maintainer_final_digests", lambda *_args: {task: spec[0] for task, spec in specs.items()})
    return root


def test_loads_both_synthetic_artifacts(tmp_path, monkeypatch, artifacts):
    root = pack_directory(tmp_path, monkeypatch, artifacts)
    pack = load_model_pack(root)
    assert pack.model_pack_id == root.name
    assert pack.binary.task == "binary" and pack.multiclass.task == "multiclass"


def test_loaded_pack_cannot_be_constructed_by_caller(artifacts):
    with pytest.raises(InferenceError, match="verified loading"):
        LoadedModelPack("a" * 64, artifacts["binary"], artifacts["multiclass"], object())


def test_deserializes_only_verified_in_memory_buffers(tmp_path, monkeypatch, artifacts):
    root = pack_directory(tmp_path, monkeypatch, artifacts)
    original = joblib.load
    seen = []
    def inspect_buffer(stream):
        assert isinstance(stream, io.BytesIO)
        seen.append(hashlib.sha256(stream.getvalue()).hexdigest())
        return original(stream)
    monkeypatch.setattr(joblib, "load", inspect_buffer)
    load_model_pack(root)
    manifest = json.loads((root / "manifest.json").read_text())
    assert seen == [manifest["artifacts"][task]["sha256"] for task in ("binary", "multiclass")]


@pytest.mark.parametrize("task,field,value", [
    ("binary", "version", "wrong"), ("binary", "schema_version", "wrong"),
    ("binary", "model_name", "random_forest"), ("binary", "task", "multiclass"),
])
def test_rejects_wrong_artifact_fields(tmp_path, monkeypatch, artifacts, task, field, value):
    setattr(artifacts[task], field, value)
    with pytest.raises(InferenceError):
        load_model_pack(pack_directory(tmp_path, monkeypatch, artifacts))


@pytest.mark.parametrize("mutation", [
    lambda a: setattr(a, "metadata", {**a.metadata, "official_test_status": "sealed"}),
    lambda a: setattr(a, "metadata", {**a.metadata, "library_versions": {}}),
    lambda a: setattr(a, "metadata", {**a.metadata, "final_protocol_sha256": "0" * 64}),
    lambda a: setattr(a.estimator, "classes_", a.estimator.classes_[::-1]),
    lambda a: setattr(a.estimator, "_predictors", None),
    lambda a: setattr(a.preprocessor, "task", "multiclass"),
])
def test_rejects_mutated_internal_contract(tmp_path, monkeypatch, artifacts, mutation):
    mutation(artifacts["binary"])
    with pytest.raises((InferenceError, TypeError, AttributeError)):
        load_model_pack(pack_directory(tmp_path, monkeypatch, artifacts))


def test_exact_bytes_checked_again_after_preflight(tmp_path, monkeypatch, artifacts):
    root = pack_directory(tmp_path, monkeypatch, artifacts)
    original = model_pack.preflight_model_pack
    from cids.workbench import inference
    def replace_after_preflight(path):
        verified = original(path)
        (root / "binary.joblib").write_bytes(b"replaced")
        return verified
    monkeypatch.setattr(inference, "preflight_model_pack", replace_after_preflight)
    monkeypatch.setattr(joblib, "load", lambda *_: pytest.fail("deserialized mismatched bytes"))
    with pytest.raises(InferenceError, match="changed after preflight"):
        load_model_pack(root)


def test_no_partial_pack_on_second_task_failure(tmp_path, monkeypatch, artifacts):
    artifacts["multiclass"].metadata["official_test_status"] = "sealed"
    with pytest.raises(InferenceError):
        load_model_pack(pack_directory(tmp_path, monkeypatch, artifacts))


def test_rejects_wrong_artifact_type(tmp_path, monkeypatch, artifacts):
    artifacts["binary"] = {"not": "an artifact"}
    with pytest.raises(InferenceError, match="wrong artifact type"):
        load_model_pack(pack_directory(tmp_path, monkeypatch, artifacts))


def test_rejects_unfitted_preprocessor(tmp_path, monkeypatch, artifacts):
    del artifacts["binary"].preprocessor.transformer.transformers_
    with pytest.raises((InferenceError, AttributeError)):
        load_model_pack(pack_directory(tmp_path, monkeypatch, artifacts))


def test_preflight_rejects_size_and_digest_mismatches(tmp_path, monkeypatch, artifacts):
    root = pack_directory(tmp_path, monkeypatch, artifacts)
    binary = root / "binary.joblib"
    binary.write_bytes(binary.read_bytes() + b"x")
    with pytest.raises(model_pack.ModelPackError, match="size mismatch"):
        load_model_pack(root)
    binary.write_bytes(binary.read_bytes()[:-1])
    data = bytearray(binary.read_bytes())
    data[-1] ^= 1
    binary.write_bytes(data)
    with pytest.raises(model_pack.ModelPackError, match="SHA-256 mismatch"):
        load_model_pack(root)


def test_duplicate_artifacts_rejected_before_deserialization(tmp_path, monkeypatch, artifacts):
    root = pack_directory(tmp_path, monkeypatch, artifacts)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["artifacts"]["multiclass"]["sha256"] = manifest["artifacts"]["binary"]["sha256"]
    manifest["artifacts"]["multiclass"]["size_bytes"] = manifest["artifacts"]["binary"]["size_bytes"]
    (root / "multiclass.joblib").write_bytes((root / "binary.joblib").read_bytes())
    manifest["model_pack_id"] = model_pack.compute_model_pack_id(manifest)
    replacement = root.parent / manifest["model_pack_id"]
    root.rename(replacement)
    (replacement / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(model_pack.ModelPackError):
        load_model_pack(replacement)


def test_dashboard_does_not_import_loading_or_inference():
    dashboard = Path(__file__).parents[1] / "src" / "cids" / "dashboard"
    for path in dashboard.rglob("*.py"):
        tree = ast.parse(path.read_text())
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(name in {"cids.workbench.inference", "cids.workbench.model_pack", "joblib"} for name in modules), path


def test_stable_bounded_inference_and_score_mapping(tmp_path, monkeypatch, artifacts):
    root = pack_directory(tmp_path, monkeypatch, artifacts)
    pack = load_model_pack(root)
    frame = synthetic_frame(3).loc[:, FEATURE_COLUMNS]
    frame.insert(0, "event_time", ["2026-10-01T05:30:00+05:30"] * 3)
    input_data = parse_inference_csv(frame.to_csv(index=False).encode())
    first = infer(pack, input_data)
    second = infer(pack, input_data)
    assert first == second and len(first) == 3
    assert [record.record_id for record in first] == ["record-000001", "record-000002", "record-000003"]
    assert all(record.event_time_utc == "2026-10-01T00:00:00Z" for record in first)
    assert all(record.model_pack_id == pack.model_pack_id and record.explanation_status == "not_requested" and not record.top_contributions for record in first)
    assert all(0 <= record.attack_model_score <= 1 and 0 <= record.family_model_score <= 1 for record in first)
    features = input_data.frame.loc[:, FEATURE_COLUMNS]
    for row_number, record in enumerate(first):
        binary_features = model_features_for_estimator("hist_gradient_boosting", pack.binary.preprocessor.transformer.transform(features.iloc[[row_number]]))
        family_features = model_features_for_estimator("hist_gradient_boosting", pack.multiclass.preprocessor.transformer.transform(features.iloc[[row_number]]))
        assert record.attack_model_score == pack.binary.estimator.predict_proba(binary_features)[0, list(pack.binary.estimator.classes_).index(1)]
        assert record.family_model_score == pack.multiclass.estimator.predict_proba(family_features)[0, list(pack.multiclass.estimator.classes_).index(record.family_prediction_raw)]


def test_bounded_batches_and_model_disagreement(tmp_path, monkeypatch, artifacts):
    from cids.workbench import inference
    root = pack_directory(tmp_path, monkeypatch, artifacts)
    pack = load_model_pack(root)
    sizes = []
    def controlled(artifact, features, task):
        sizes.append(len(features))
        if task == "binary":
            return np.ones(len(features), dtype=int), np.tile([0.05, 0.95], (len(features), 1)), {0: 0, 1: 1}
        classes = {name: index for index, name in enumerate(sorted(ATTACK_FAMILIES))}
        score = np.zeros((len(features), len(classes)))
        score[:, classes["normal"]] = 1
        return np.array(["normal"] * len(features)), score, classes
    monkeypatch.setattr(inference, "_predictions", controlled)
    frame = synthetic_frame(1025).loc[:, FEATURE_COLUMNS]
    data = parse_inference_csv(frame.to_csv(index=False).encode())
    records = infer(pack, data)
    assert len(records) == 1025 and sizes == [1024, 1024, 1, 1]
    assert all(record.queue_band == "model_disagreement" and record.triage_family == "unresolved" for record in records)


@pytest.mark.parametrize("attack_score,expected", [(0.75, "review"), (0.95, "higher_score_review")])
def test_queue_band_routing(tmp_path, monkeypatch, artifacts, attack_score, expected):
    from cids.workbench import inference
    pack = load_model_pack(pack_directory(tmp_path, monkeypatch, artifacts))
    def controlled(_artifact, features, task):
        if task == "binary":
            return np.ones(len(features), dtype=int), np.tile([1 - attack_score, attack_score], (len(features), 1)), {0: 0, 1: 1}
        classes = {name: index for index, name in enumerate(sorted(ATTACK_FAMILIES))}
        score = np.zeros((len(features), len(classes)))
        score[:, classes["analysis"]] = 1
        return np.array(["analysis"] * len(features)), score, classes
    monkeypatch.setattr(inference, "_predictions", controlled)
    data = parse_inference_csv(synthetic_frame(1).loc[:, FEATURE_COLUMNS].to_csv(index=False).encode())
    assert infer(pack, data)[0].queue_band == expected


def test_rejects_prediction_shape(tmp_path, monkeypatch, artifacts):
    pack = load_model_pack(pack_directory(tmp_path, monkeypatch, artifacts))
    monkeypatch.setattr(pack.binary.estimator, "predict_proba", lambda _matrix: np.ones((1, 1)))
    data = parse_inference_csv(synthetic_frame(1).loc[:, FEATURE_COLUMNS].to_csv(index=False).encode())
    with pytest.raises(InferenceError, match="shape mismatch"):
        infer(pack, data)


@pytest.mark.parametrize("bad", [np.nan, np.inf, -0.1, 1.1])
def test_rejects_bad_probability_output(tmp_path, monkeypatch, artifacts, bad):
    root = pack_directory(tmp_path, monkeypatch, artifacts)
    pack = load_model_pack(root)
    original = pack.binary.estimator.predict_proba
    def malformed(matrix):
        scores = original(matrix)
        scores[0, 1] = bad
        return scores
    monkeypatch.setattr(pack.binary.estimator, "predict_proba", malformed)
    data = parse_inference_csv(synthetic_frame(1).loc[:, FEATURE_COLUMNS].to_csv(index=False).encode())
    with pytest.raises(InferenceError):
        infer(pack, data)


def test_local_real_pack_on_verified_training_rows():
    training_name = os.environ.get("CIDS_PHASE3B_TRAINING_CSV")
    if not training_name:
        pytest.skip("verified local training CSV was not supplied")
    training = Path(training_name)
    if training.name != "cids-phase3b-training.csv":
        pytest.fail("only the explicitly verified training file is allowed")
    payload = training.read_bytes()
    assert len(payload) == 32293018
    assert hashlib.sha256(payload).hexdigest() == "bec7dd5ec88dc2a0ccc7a07879d338395ed7421750f675fd0339e07dfe0648fa"
    pack_dir = Path("artifacts/v2.1/model-packs/e2d4f329b894a1b68b70af377ffc94441e02d024de27e7c351384d3e25692b18")
    if not pack_dir.is_dir():
        pytest.skip("ignored real pack is not installed")
    rows = pd.read_csv(io.BytesIO(payload), nrows=16)
    data = parse_inference_csv(rows.loc[:, ["id", *FEATURE_COLUMNS]].to_csv(index=False).encode())
    records = infer(load_model_pack(pack_dir), data)
    assert len(records) == 16
    assert [record.record_id for record in records] == [str(value) for value in rows["id"]]
    assert all(record.event_time_utc is None for record in records)
