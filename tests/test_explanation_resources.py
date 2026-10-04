"""Synthetic resource fixtures only; no official dataset rows or executable files."""
import copy
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from cids.datasets.unsw_nb15 import ATTACK_FAMILIES, FEATURE_COLUMNS
from cids.workbench import model_pack
from cids.workbench.config import load_workbench_config, workbench_config_sha256
from cids.workbench import explanation_resources as er
from test_workbench_contracts import valid_frame


@pytest.fixture
def resource_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(model_pack, "current_runtime", lambda: model_pack.EXPECTED_RUNTIME)
    pack = {"model_pack_id": "a" * 64, "runtime": copy.deepcopy(model_pack.EXPECTED_RUNTIME),
            "artifacts": {t: {"filename": f"{t}.joblib", "sha256": str(i) * 64, "size_bytes": 123, "task": t}
                          for i, t in enumerate(("binary", "multiclass"), 1)}}
    files, tasks = {}, {}
    for task in ("binary", "multiclass"):
        name = f"{task}-background.csv"
        data = valid_frame(8).loc[:, FEATURE_COLUMNS].to_csv(index=False).encode()
        files[name] = data
        tasks[task] = {"provenance": er.frozen_provenance(task),
                       "background": {"filename": name, "sha256": er.digest_bytes(data), "size_bytes": len(data), "rows": 8},
                       "background_sample_id_sha256": "b" * 64, "global": None, "global_sample_id_sha256": None}
    manifest = {"manifest_version": er.VERSION, **copy.deepcopy(pack), "schema": list(FEATURE_COLUMNS),
                "policy_sha256": workbench_config_sha256(load_workbench_config()), "tasks": tasks}
    def publish(manifest=manifest):
        manifest["resource_id"] = er.resource_id(manifest)
        root = er.controlled_directory(tmp_path, manifest["resource_id"])
        root.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (root / name).write_bytes(data)
        (root / "manifest.json").write_bytes(er.canonical(manifest))
        return root
    root = publish()
    return SimpleNamespace(repo=tmp_path, root=root, pack=pack, manifest=manifest, files=files, publish=publish)


def test_resources_are_feature_only_bounded_and_pack_bound(resource_fixture):
    f = resource_fixture
    resources = er.load_resources(f.repo, f.root.name, f.pack)
    assert resources.resource_id == f.root.name
    assert set(resources.backgrounds) == {"binary", "multiclass"}
    assert resources.global_reliance == {}
    assert all(list(frame.columns) == list(FEATURE_COLUMNS) and len(frame) == 8 for frame in resources.backgrounds.values())


@pytest.mark.parametrize("change", ["missing", "file_digest", "manifest_digest", "wrong_pack", "artifact", "runtime", "actual_runtime",
                                   "schema", "policy", "provenance", "target_column", "rows", "filename", "too_large", "duplicate_key", "symlink", "parent_link", "fifo"])
def test_resources_fail_closed(resource_fixture, monkeypatch, change):
    f = resource_fixture
    identifier = f.root.name
    background = f.root / "binary-background.csv"
    if change == "missing":
        background.unlink()
    elif change == "file_digest":
        background.write_bytes(background.read_bytes().replace(b"tcp", b"udp"))
    elif change == "manifest_digest":
        (f.root / "manifest.json").write_text((f.root / "manifest.json").read_text().replace('"seed":42', '"seed":43'))
    elif change == "wrong_pack":
        f.pack["model_pack_id"] = "c" * 64
    elif change == "artifact":
        f.pack["artifacts"]["binary"]["sha256"] = "d" * 64
    elif change == "runtime":
        f.pack["runtime"]["python"] = "3.12.0"
    elif change == "actual_runtime":
        monkeypatch.setattr(model_pack, "current_runtime", lambda: {})
    elif change == "duplicate_key":
        (f.root / "manifest.json").write_bytes(b'{"x":1,"x":2}')
    elif change in ("symlink", "fifo"):
        data = background.read_bytes()
        background.unlink()
        if change == "symlink":
            other = f.repo / "outside.csv"
            other.write_bytes(data)
            background.symlink_to(other)
        else:
            os.mkfifo(background)
    elif change == "parent_link":
        moved = f.root.with_name("other")
        f.root.rename(moved)
        f.root.symlink_to(moved, target_is_directory=True)
    else:
        entry = f.manifest["tasks"]["binary"]
        if change == "schema":
            f.manifest["schema"].reverse()
        elif change == "policy":
            f.manifest["policy_sha256"] = "f" * 64
        elif change == "provenance":
            entry["provenance"]["training_scope"] = "official_test"
        elif change == "target_column":
            name = entry["background"]["filename"]
            f.files[name] = valid_frame(8).assign(label=0).to_csv(index=False).encode()
            entry["background"].update(sha256=er.digest_bytes(f.files[name]), size_bytes=len(f.files[name]))
        elif change == "rows":
            entry["background"]["rows"] = 257
        elif change == "filename":
            entry["background"]["filename"] = "../outside.csv"
        elif change == "too_large":
            entry["background"]["size_bytes"] = er.MAX_BACKGROUND_BYTES + 1
        identifier = f.publish().name
    with pytest.raises(er.ResourceError):
        er.load_resources(f.repo, identifier, f.pack)


def test_no_resource_configuration_is_unavailable(resource_fixture):
    with pytest.raises(er.ResourceError):
        er.load_resources(resource_fixture.repo, None, resource_fixture.pack)


def test_global_evidence_is_distinct_validated_and_complete(resource_fixture):
    f = resource_fixture
    for task in ("binary", "multiclass"):
        value = {"task": task, "policy": er.GLOBAL_POLICY, "sample_rows": 8,
                 "class_labels": [0, 1] if task == "binary" else sorted(ATTACK_FAMILIES),
                 "baseline_score": .25,
                 "features": [{"feature": name, "mean_score_decrease": -.01, "std_score_decrease": .1} for name in FEATURE_COLUMNS]}
        name = f"{task}-global.json"
        data = er.canonical(value)
        f.files[name] = data
        f.manifest["tasks"][task].update(global_sample_id_sha256="c" * 64,
                                         **{"global": {"filename": name, "sha256": er.digest_bytes(data), "size_bytes": len(data), "rows": 8}})
    root = f.publish()
    resources = er.load_resources(f.repo, root.name, f.pack)
    assert resources.global_reliance["binary"]["policy"] == er.GLOBAL_POLICY
    assert len(resources.global_reliance["multiclass"]["features"]) == 42
    f.manifest["tasks"]["binary"]["global"]["rows"] = 9
    root = f.publish()
    with pytest.raises(er.ResourceError):
        er.load_resources(f.repo, root.name, f.pack)


def test_read_regular_bytes_rejects_descriptor_change(tmp_path, monkeypatch):
    path = tmp_path / "bounded.json"
    path.write_bytes(b"abcdef")
    original = os.read
    def change(fd, limit):
        data = original(fd, limit)
        if data:
            path.write_bytes(b"ghijkl")
        return data
    monkeypatch.setattr(os, "read", change)
    with pytest.raises(er.ResourceError):
        er.read_regular_bytes(path, 10)
