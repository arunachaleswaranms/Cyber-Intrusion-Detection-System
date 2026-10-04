"""CLI split preparation and global evidence on synthetic representative data."""
import copy
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from cids.experiments import prepare_explanation_resources as cli
from cids.workbench import explanation_resources as er
from cids.datasets.split_unsw_nb15 import prepare_development_splits
from cids.datasets.unsw_nb15 import FEATURE_COLUMNS, NUMERIC_FEATURES
from cids.workbench.sampling import _stratified_sample


def sources():
    rows = []
    for i in range(100):
        row = {name: float(i + 1) for name in NUMERIC_FEATURES}
        row.update(id=i + 1, proto="tcp", service="-", state="FIN", label=int(i >= 50), attack_cat="normal" if i < 50 else "generic")
        rows.append(row)
    train = pd.DataFrame(rows)
    reference = train.iloc[[0, 50]].loc[:, FEATURE_COLUMNS]
    return train, reference


def synthetic_provenance(partitions, task):
    p = er.frozen_provenance(task)
    p.update(training_rows=len(partitions[task]["train"]), training_id_sha256=cli.id_digest(partitions[task]["train"]),
             validation_rows=len(partitions[task]["validation"]), validation_id_sha256=cli.id_digest(partitions[task]["validation"]))
    return p


@pytest.fixture
def partitions(monkeypatch):
    source, reference = sources()
    parts = {}
    for task in ("binary", "multiclass"):
        split = prepare_development_splits(source, reference, task)
        parts[task] = {"train": split.train, "validation": split.validation}
    monkeypatch.setattr(cli, "frozen_provenance", lambda task: synthetic_provenance(parts, task))
    return source, reference, parts


def test_preferred_verified_prepared_partitions_never_read_test_source(partitions, monkeypatch, tmp_path):
    source, reference, parts = partitions
    for task, frames in parts.items():
        for partition, frame in frames.items():
            (tmp_path / f"{task}-{partition}.csv").write_bytes(frame.to_csv(index=False).encode())
    calls = []
    def read(path, role):
        calls.append(role)
        assert role == "train"
        return source.to_csv(index=False).encode()
    monkeypatch.setattr(cli, "verified_source", read)
    actual = cli.development_partitions(tmp_path / "source.csv", prepared_dir=tmp_path)
    assert calls == ["train"]
    for task in parts:
        for partition in parts[task]:
            pd.testing.assert_frame_equal(actual[task][partition], parts[task][partition])


def test_overlap_path_requires_explicit_permission_before_test_read(partitions, monkeypatch, tmp_path):
    source, _, _ = partitions
    calls = []
    monkeypatch.setattr(cli, "verified_source", lambda path, role: calls.append(role) or source.to_csv(index=False).encode())
    with pytest.raises(ValueError, match="explicitly permit"):
        cli.development_partitions(tmp_path / "train", test_source=tmp_path / "test")
    assert calls == ["train"]


def test_approved_overlap_path_parses_feature_columns_only(partitions, monkeypatch, tmp_path):
    source, reference, parts = partitions
    fake_test = reference.assign(id=[1, 2], label=["DO_NOT_PARSE"] * 2, attack_cat=["DO_NOT_PARSE"] * 2)
    def read(path, role):
        return (source if role == "train" else fake_test).to_csv(index=False).encode()
    monkeypatch.setattr(cli, "verified_source", read)
    original = pd.read_csv
    def inspect(buffer, **kwargs):
        if b"DO_NOT_PARSE" in buffer.getvalue():
            assert kwargs["usecols"] == list(FEATURE_COLUMNS)
        return original(buffer, **kwargs)
    monkeypatch.setattr(pd, "read_csv", inspect)
    actual = cli.development_partitions(tmp_path / "train", test_source=tmp_path / "test", allow_overlap=True)
    for task in parts:
        pd.testing.assert_frame_equal(actual[task]["train"], parts[task]["train"])
        pd.testing.assert_frame_equal(actual[task]["validation"], parts[task]["validation"])


@pytest.mark.parametrize("change", ["id", "feature", "target", "order", "rows"])
def test_prepared_partitions_require_frozen_identity_and_source_rows(partitions, change):
    source, _, parts = partitions
    frame = parts["binary"]["train"].copy()
    if change == "id": frame.loc[0, "id"] = 9999
    if change == "feature": frame.loc[0, "dur"] += 1
    if change == "target": frame.loc[0, "attack_cat"], frame.loc[0, "label"] = "exploits", 1
    if change == "order": frame = frame.iloc[::-1]
    if change == "rows": frame = frame.iloc[:-1]
    with pytest.raises((ValueError, AssertionError)):
        cli.verify_partition(frame, source, "binary", "train")


def test_global_reliance_has_deterministic_scoring_provenance_and_no_targets_in_features():
    source, _ = sources()
    source.loc[source.index >= 50, "dur"] += 200
    source.loc[source.index < 50, "dur"] = 1
    class Transformer:
        def transform(self, frame):
            assert list(frame.columns) == list(FEATURE_COLUMNS)
            return frame[["dur"]].to_numpy()
    class Estimator:
        classes_ = np.array([0, 1])
        def predict(self, values): return (values[:, 0] > 100).astype(int)
    artifact = SimpleNamespace(task="binary", model_name="hist_gradient_boosting", estimator=Estimator(),
                               preprocessor=SimpleNamespace(transformer=Transformer()))
    first, digest = cli.global_model_reliance(artifact, source)
    second, again = cli.global_model_reliance(artifact, source)
    assert first == second and digest == again
    assert first["baseline_score"] == 1. and first["sample_rows"] == 100
    assert first["policy"] == er.GLOBAL_POLICY and first["features"][0]["mean_score_decrease"] > .1
    assert all(row["mean_score_decrease"] == 0 for row in first["features"][1:])


def test_verified_source_rejects_unknown_csv_before_parsing(tmp_path, monkeypatch):
    path = tmp_path / "not-official.csv"
    path.write_bytes(b"dur\n1\n")
    with pytest.raises(er.ResourceError):
        cli.verified_source(path, "train")


@pytest.mark.parametrize("prepare_global", [False, True])
def test_cli_publication_is_private_feature_only_immutable_and_pack_preserving(partitions, monkeypatch, tmp_path, prepare_global):
    from cids.workbench import model_pack
    if model_pack.current_runtime() != model_pack.EXPECTED_RUNTIME:
        pytest.skip("Phase 4 resource publication integration requires pinned model runtime")
    from test_workbench_inference import synthetic_artifact, pack_directory
    from cids.workbench.analysis import PACK_ROOT
    source, reference, parts = partitions
    frozen = {t: synthetic_provenance(parts, t) for t in parts}
    monkeypatch.setattr(er, "frozen_provenance", lambda t: frozen[t])
    monkeypatch.setattr(cli, "frozen_provenance", lambda t: frozen[t])
    pack_root = tmp_path / PACK_ROOT
    pack_root.mkdir(parents=True)
    directory = pack_directory(pack_root, monkeypatch, {t: synthetic_artifact(t) for t in parts})
    original_manifest = (directory / "manifest.json").read_bytes()
    if not prepare_global:
        monkeypatch.setattr(cli, "global_model_reliance", lambda *_: pytest.fail("global work must be explicit"))
    identifier = cli.prepare_resources(tmp_path, directory.name, parts, prepare_global=prepare_global)
    root = er.controlled_directory(tmp_path, identifier)
    manifest = json.loads((root / "manifest.json").read_bytes())
    assert (directory / "manifest.json").read_bytes() == original_manifest
    resources = er.load_resources(tmp_path, identifier, json.loads(original_manifest))
    assert len(resources.global_reliance) == (2 if prepare_global else 0)
    for task in parts:
        expected = _stratified_sample(parts[task]["train"], task, 256).loc[:, FEATURE_COLUMNS]
        pd.testing.assert_frame_equal(resources.backgrounds[task], expected, check_dtype=False)
        assert manifest["tasks"][task]["background_sample_id_sha256"] == cli.id_digest(_stratified_sample(parts[task]["train"], task, 256))
    assert all((p.stat().st_mode & 0o077) == 0 for p in root.iterdir())
    assert not any(p.suffix == ".joblib" for p in root.iterdir())
    assert cli.prepare_resources(tmp_path, directory.name, parts, prepare_global=prepare_global) == identifier
