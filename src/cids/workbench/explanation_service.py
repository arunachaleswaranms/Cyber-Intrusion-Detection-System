"""Explicit session-owned explanations with macOS subprocess isolation and cancellation.

No model, SHAP, upload or attribution cache. Only bounded JSON crosses the
worker boundary; returned data never reaches disk or application logs.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from cids.datasets.unsw_nb15 import FEATURE_COLUMNS, validate_model_feature_frame
from cids.workbench.config import load_workbench_config, workbench_config_sha256
from cids.workbench.contracts import FeatureContribution
from cids.workbench.explanation_resources import canonical, controlled_directory, digest_bytes

MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 128 * 1024
FAILURE_MESSAGE = "Explanation failed or exceeded its time limit. Analysis remains usable; no attribution is available."
UNAVAILABLE_MESSAGE = "Explanation unavailable: verified compatible CLI-prepared resources and the pinned runtime are required. Analysis remains usable."


class ExplanationFailure(ValueError):
    """Fixed public failure without private exception content."""


@dataclass(frozen=True)
class LocalExplanation:
    input_sha256: str
    model_pack_id: str
    resource_id: str
    background_sha256: str
    policy_sha256: str
    task: str
    record_index: int
    record_id: str
    explained_class: str
    baseline_output: float
    model_output: float
    contributions: tuple[FeatureContribution, ...]
    max_additivity_error: float
    max_aggregation_error: float


def worker_result(request_bytes):
    """Dedicated child entry point; never emit private errors or unbounded results."""
    try:
        if len(request_bytes) > MAX_REQUEST_BYTES:
            raise ValueError("oversized worker input")
        request = json.loads(request_bytes)
        import pandas as pd
        from threadpoolctl import threadpool_limits
        from cids.workbench.analysis import configured_pack_dir
        from cids.workbench.inference import load_model_pack
        from cids.workbench.model_pack import preflight_model_pack
        from cids.workbench.explanation_resources import load_resources
        from cids.workbench.explanations import explain_records

        policy = load_workbench_config()
        if request["policy_sha256"] != workbench_config_sha256(policy) or request["task"] not in ("binary", "multiclass"):
            raise ValueError("worker policy mismatch")
        directory = configured_pack_dir(Path(request["repo_root"]), request["model_pack_id"])
        verified = preflight_model_pack(directory)
        resources = load_resources(request["repo_root"], request["resource_id"], verified.manifest)
        pack = load_model_pack(directory)
        selected = pd.DataFrame(request["selected_rows"])
        if (len(selected) != len(request["records"])
                or not 0 < len(selected) <= policy["explainability"]["max_explain_rows"]
                or set(selected.columns) != {"id", *FEATURE_COLUMNS}
                or selected.id.tolist() != [r["id"] for r in request["records"]]):
            raise ValueError("worker record identity mismatch")
        # JSON preserves normalized numeric values without a second CSV float parse.
        features = validate_model_feature_frame(selected.loc[:, FEATURE_COLUMNS])
        with threadpool_limits(limits=1):
            values = explain_records(getattr(pack, request["task"]), resources.backgrounds[request["task"]], features)
        for value, record in zip(values, request["records"]):
            value.update(record_index=record["index"], record_id=record["id"])
        output = canonical({"status": "available", "request_sha256": digest_bytes(request_bytes), "values": values})
        if len(output) > MAX_RESULT_BYTES:
            raise ValueError("oversized worker result")
        return output
    except Exception:
        return b'{"status":"failed"}'


def _isolated(request_bytes, seconds, *, command=None):
    """Fresh interpreter, bounded pipes, deadline cancellation, reap on every path.

    A dedicated module avoids multiprocessing's re-execution of Streamlit's
    mutable __main__ bootstrap, without changing global process/module state.
    """
    if len(request_bytes) > MAX_REQUEST_BYTES or not 0 < seconds <= 60:
        raise ExplanationFailure(FAILURE_MESSAGE)
    if command is None:
        command = [sys.executable, "-m", "cids.workbench.explanation_worker"]
    environment = dict(os.environ)
    source_root = str(Path(__file__).resolve().parents[2])
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    process = None
    timer = None
    expired = threading.Event()
    deadline = monotonic() + seconds
    def cancel_worker():
        expired.set()
        if process is not None:
            try:
                process.kill()
            except (OSError, ValueError):
                pass
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=environment)
        timer = threading.Timer(max(0, deadline - monotonic()), cancel_worker)
        timer.daemon = True
        timer.start()
        # Watchdog covers blocked input, partial output, imports and calculation.
        process.stdin.write(request_bytes)
        process.stdin.close()
        data = process.stdout.read(MAX_RESULT_BYTES + 1)
        remaining = deadline - monotonic()
        if len(data) > MAX_RESULT_BYTES or remaining <= 0 or expired.is_set():
            raise ExplanationFailure(FAILURE_MESSAGE)
        process.wait(timeout=remaining)
        if expired.is_set() or process.returncode != 0:
            raise ExplanationFailure(FAILURE_MESSAGE)
        value = json.loads(data)
        if (value.get("status") != "available" or set(value) != {"status", "request_sha256", "values"}
                or value["request_sha256"] != digest_bytes(request_bytes)):
            raise ExplanationFailure(FAILURE_MESSAGE)
        return value["values"]
    except Exception as exc:
        raise ExplanationFailure(FAILURE_MESSAGE) from exc
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass


def request_explanations(repo_root, input_data, analysis_result, resources, task, indices):
    """Explicit action API. Bind full upload identity while sending selected rows only."""
    policy = load_workbench_config()
    if (task not in ("binary", "multiclass") or not 0 < len(indices) <= policy["explainability"]["max_explain_rows"]
            or len(set(indices)) != len(indices) or any(type(i) is not int or not 0 <= i < len(input_data.frame) for i in indices)
            or analysis_result.input_sha256 != input_data.input_sha256
            or resources.manifest["model_pack_id"] != analysis_result.model_pack_id):
        raise ExplanationFailure(FAILURE_MESSAGE)
    controlled_directory(repo_root, resources.resource_id)
    selected = input_data.frame.iloc[indices].loc[:, ["id", *FEATURE_COLUMNS]]
    records = [{"index": i, "id": analysis_result.records[i].record_id} for i in indices]
    if selected.id.tolist() != [r["id"] for r in records]:
        raise ExplanationFailure(FAILURE_MESSAGE)
    policy_digest = workbench_config_sha256(policy)
    request = {"repo_root": str(Path(repo_root).resolve()), "model_pack_id": analysis_result.model_pack_id,
               "resource_id": resources.resource_id, "input_sha256": input_data.input_sha256,
               "policy_sha256": policy_digest, "task": task, "records": records,
               "selected_rows": selected.to_dict(orient="records")}
    try:
        output = _isolated(canonical(request), policy["explainability"]["max_task_seconds"])
        if not isinstance(output, list) or len(output) != len(indices):
            raise ValueError("worker returned wrong rows")
        results = []
        for index, values in zip(indices, output):
            if set(values) != {"record_index", "record_id", "explained_class", "baseline_output", "model_output", "contributions", "max_additivity_error", "max_aggregation_error"}:
                raise ValueError("worker returned wrong fields")
            if type(values["record_index"]) is not int or values["record_index"] != index or values["record_id"] != analysis_result.records[index].record_id:
                raise ValueError("worker returned wrong record identity")
            expected = 1 if task == "binary" else analysis_result.records[index].family_prediction_raw
            if values["explained_class"] != expected or len(values["contributions"]) != 42:
                raise ValueError("worker returned wrong class or features")
            numeric = [values[k] for k in ("baseline_output", "model_output", "max_additivity_error", "max_aggregation_error")]
            numeric.extend(values["contributions"])
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in numeric):
                raise ValueError("worker returned nonfinite result")
            if task == "binary" and (values["model_output"] > 0) != (analysis_result.records[index].binary_prediction == "attack"):
                raise ValueError("worker output does not match original binary prediction")
            if (not 0 <= values["max_additivity_error"] <= 1e-5
                    or not 0 <= values["max_aggregation_error"] <= 1e-10
                    or abs(values["baseline_output"] + sum(values["contributions"]) - values["model_output"]) > 1e-5):
                raise ValueError("worker reconstruction failed")
            explained_class = "attack" if task == "binary" else expected
            contributions = tuple(FeatureContribution(
                name, str(input_data.frame.iloc[index][name])[:200], contribution, explained_class,
                values["baseline_output"], values["model_output"],
            ) for name, contribution in zip(FEATURE_COLUMNS, values["contributions"]))
            results.append(LocalExplanation(input_data.input_sha256, analysis_result.model_pack_id,
                          resources.resource_id, resources.manifest["tasks"][task]["background"]["sha256"],
                          policy_digest, task, index, analysis_result.records[index].record_id, explained_class,
                          values["baseline_output"], values["model_output"], contributions,
                          values["max_additivity_error"], values["max_aggregation_error"]))
        return tuple(results)
    except Exception as exc:
        raise ExplanationFailure(FAILURE_MESSAGE) from exc
