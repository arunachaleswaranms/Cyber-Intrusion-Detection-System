"""CLI-only frozen development backgrounds and optional global model reliance.

Never trains a model or evaluates/explains the official test. No raw partition,
ID, or target column is written into a runtime background resource.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

from cids.config import load_experiment_config
from cids.datasets.split_unsw_nb15 import prepare_development_splits, target_for_task
from cids.datasets.unsw_nb15 import FEATURE_COLUMNS, validate_prepared_frame
from cids.modeling.supervised import model_features_for_estimator
from cids.workbench.analysis import configured_pack_dir
from cids.workbench.config import load_workbench_config, workbench_config_sha256
from cids.workbench.evidence import load_frozen_evidence
from cids.workbench.explanation_resources import (
    GLOBAL_POLICY, MAX_BACKGROUND_BYTES, MAX_GLOBAL_BYTES, MAX_MANIFEST_BYTES,
    RESOURCE_ROOT, VERSION, canonical, controlled_directory, digest_bytes,
    frozen_provenance, load_resources, read_regular_bytes, resource_id,
)
from cids.workbench.inference import load_model_pack
from cids.workbench.model_pack import preflight_model_pack
from cids.workbench.sampling import _stratified_sample

ROOT = Path(__file__).resolve().parents[3]


def id_digest(frame):
    return hashlib.sha256("\n".join(str(v) for v in frame.id).encode()).hexdigest()


def verified_source(path, role):
    spec = load_frozen_evidence().report["dataset_files"][role]
    # The frozen report binds exact bytes. Paths are supplied only through CLI.
    return read_regular_bytes(path, spec["size_bytes"], spec)


def verify_partition(frame, source, task, partition):
    """Bind full prepared rows to the verified source and frozen split IDs."""
    frame = validate_prepared_frame(frame)
    provenance = frozen_provenance(task)
    prefix = "training" if partition == "train" else "validation"
    if len(frame) != provenance[prefix + "_rows"] or id_digest(frame) != provenance[prefix + "_id_sha256"]:
        raise ValueError("prepared partition does not match frozen split")
    source_by_id = source.set_index("id", drop=False)
    if not set(frame.id).issubset(source_by_id.index):
        raise ValueError("prepared IDs do not belong to training source")
    expected = source_by_id.loc[frame.id].reset_index(drop=True)
    pd.testing.assert_frame_equal(frame.reset_index(drop=True), expected, check_dtype=False)
    return frame


def development_partitions(training_csv, prepared_dir=None, test_source=None, allow_overlap=False):
    source = validate_prepared_frame(pd.read_csv(io.BytesIO(verified_source(training_csv, "train"))))
    tasks = {}
    if prepared_dir is not None:
        for task in ("binary", "multiclass"):
            tasks[task] = {}
            for partition in ("train", "validation"):
                path = Path(prepared_dir) / f"{task}-{partition}.csv"
                data = read_regular_bytes(path, 40 * 1024 * 1024)
                tasks[task][partition] = verify_partition(pd.read_csv(io.BytesIO(data)), source, task, partition)
        return tasks
    if not allow_overlap or test_source is None:
        raise ValueError("supply verified prepared partitions, or explicitly permit feature-only overlap removal")
    # The only allowed official-test access: feature columns used to remove overlap.
    # No test IDs/targets are parsed and these rows never reach any estimator.
    reference = pd.read_csv(io.BytesIO(verified_source(test_source, "test")), usecols=list(FEATURE_COLUMNS))
    config = load_experiment_config()
    for task in ("binary", "multiclass"):
        splits = prepare_development_splits(source, reference, task,
                                           validation_fraction=config["split"]["validation_fraction"], seed=42)
        tasks[task] = {p: verify_partition(getattr(splits, p), source, task, p) for p in ("train", "validation")}
    return tasks


def global_model_reliance(artifact, development):
    """Permute each original feature before encoding; development data only.

    Final estimators were refit on development train + validation. This measures
    in-development reliance, not held-out generalization or a new benchmark.
    """
    sample = _stratified_sample(development, artifact.task, GLOBAL_POLICY["sample_limit"])
    features = sample.loc[:, FEATURE_COLUMNS].copy()
    truth = sample[target_for_task(artifact.task)]
    classes = [v.item() if isinstance(v, np.generic) else v for v in artifact.estimator.classes_]
    def score(frame):
        matrix = model_features_for_estimator(artifact.model_name, artifact.preprocessor.transformer.transform(frame))
        predictions = artifact.estimator.predict(matrix)
        return float(f1_score(truth, predictions, labels=classes, average="macro", zero_division=0))
    baseline = score(features)
    random = np.random.default_rng(42)
    rows = []
    for feature in FEATURE_COLUMNS:
        decreases = []
        for _ in range(GLOBAL_POLICY["repeats"]):
            permuted = features.copy()
            permuted[feature] = features[feature].to_numpy()[random.permutation(len(features))]
            decreases.append(baseline - score(permuted))
        rows.append({"feature": feature, "mean_score_decrease": float(np.mean(decreases)),
                     "std_score_decrease": float(np.std(decreases))})
    return {"task": artifact.task, "policy": GLOBAL_POLICY, "sample_rows": len(sample),
            "class_labels": classes, "baseline_score": baseline, "features": rows}, id_digest(sample)


def prepare_resources(repo_root, pack_id, partitions, *, prepare_global=False):
    directory = configured_pack_dir(repo_root, pack_id)
    verified = preflight_model_pack(directory)
    pack = load_model_pack(directory)  # Never weaken the existing trust boundary.
    policy = load_workbench_config()
    files, tasks = {}, {}
    for task in ("binary", "multiclass"):
        train, validation = partitions[task]["train"], partitions[task]["validation"]
        provenance = frozen_provenance(task)
        for frame, prefix in ((train, "training"), (validation, "validation")):
            if len(frame) != provenance[prefix + "_rows"] or id_digest(frame) != provenance[prefix + "_id_sha256"]:
                raise ValueError("frozen split identity mismatch")
        background = _stratified_sample(train, task, min(256, policy["explainability"]["background_rows"]))
        background_name = f"{task}-background.csv"
        files[background_name] = background.loc[:, FEATURE_COLUMNS].to_csv(index=False, lineterminator="\n").encode()
        def spec(name, rows):
            return {"filename": name, "sha256": digest_bytes(files[name]), "size_bytes": len(files[name]), "rows": rows}
        entry = {"provenance": provenance, "background": spec(background_name, len(background)),
                 "background_sample_id_sha256": id_digest(background), "global": None, "global_sample_id_sha256": None}
        if prepare_global:
            evidence, sampled_ids = global_model_reliance(getattr(pack, task), validation)
            name = f"{task}-global.json"
            files[name] = canonical(evidence)
            entry.update({"global": spec(name, evidence["sample_rows"]), "global_sample_id_sha256": sampled_ids})
        tasks[task] = entry
    manifest = {"manifest_version": VERSION, "model_pack_id": pack_id,
                "artifacts": verified.manifest["artifacts"], "runtime": verified.manifest["runtime"],
                "schema": list(FEATURE_COLUMNS), "policy_sha256": workbench_config_sha256(policy), "tasks": tasks}
    manifest["resource_id"] = resource_id(manifest)
    final = controlled_directory(repo_root, manifest["resource_id"])
    files["manifest.json"] = canonical(manifest)
    for name, data in files.items():
        maximum = MAX_MANIFEST_BYTES if name == "manifest.json" else MAX_BACKGROUND_BYTES if name.endswith(".csv") else MAX_GLOBAL_BYTES
        if len(data) > maximum:
            raise ValueError("prepared resource exceeds size bound")
    final.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Recheck controlled parents after creation and never overwrite a version.
    controlled_directory(repo_root, manifest["resource_id"])
    if final.exists():
        load_resources(repo_root, manifest["resource_id"], verified.manifest)
        return manifest["resource_id"]
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=final.parent) as temporary:
        temporary = Path(temporary)
        for name, data in files.items():
            descriptor = os.open(temporary / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
        # Publication is a directory rename after all bytes are complete.
        temporary.rename(final)
    load_resources(repo_root, manifest["resource_id"], verified.manifest)
    return manifest["resource_id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-id", required=True)
    parser.add_argument("--training-csv", required=True, type=Path)
    parser.add_argument("--prepared-dir", type=Path)
    parser.add_argument("--official-test-feature-reference", type=Path)
    parser.add_argument("--allow-test-feature-overlap", action="store_true")
    parser.add_argument("--prepare-global", action="store_true", help="Explicit offline global permutation evidence (256 development rows, 3 repeats)")
    args = parser.parse_args()
    partitions = development_partitions(args.training_csv, args.prepared_dir,
                                         args.official_test_feature_reference, args.allow_test_feature_overlap)
    identifier = prepare_resources(ROOT, args.pack_id, partitions, prepare_global=args.prepare_global)
    print(f"Prepared explanation resource: {identifier}")
    print("Set CIDS_EXPLANATION_RESOURCE_ID to this digest outside the browser.")
    print("Official test: feature-only overlap reference if explicitly permitted; never predicted, explained or scored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
