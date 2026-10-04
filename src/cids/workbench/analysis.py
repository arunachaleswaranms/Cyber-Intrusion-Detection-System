"""Session-owned CSV analysis orchestration; no inference import on display.

This module owns no globals containing uploads, frames, models, or results.
Callers keep one AnalysisSession per browser session. Errors shown to users are
fixed messages: contract exception text can contain private values or paths.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from cids.datasets.unsw_nb15 import CATEGORICAL_FEATURES
from cids.workbench.config import load_workbench_config
from cids.workbench.contracts import InferenceInput, InputContractError, PredictionRecord, parse_inference_csv

PACK_ENV = "CIDS_MODEL_PACK_ID"
PACK_ROOT = Path("artifacts/v2.1/model-packs")
QUEUE_BANDS = ("not_alerted", "review", "higher_score_review", "model_disagreement")
PAGE_ROWS = 200


class AnalysisUnavailable(ValueError):
    """A local pack cannot be used; safe fixed text for the UI."""


def configured_pack_dir(repo_root: Path, pack_id: str | None) -> Path:
    """Bind only a canonical ID under the app-owned root; never a web path."""
    if not pack_id:
        raise AnalysisUnavailable("Analysis unavailable: no registered pack is configured. Set CIDS_MODEL_PACK_ID outside the browser, then restart the dashboard.")
    if re.fullmatch(r"[0-9a-f]{64}", pack_id) is None:
        raise AnalysisUnavailable("Analysis unavailable: CIDS_MODEL_PACK_ID must be one lowercase 64-character registered pack ID.")
    root = Path(repo_root).resolve()
    candidate = root
    for part in (*PACK_ROOT.parts, pack_id):
        candidate = candidate / part
        if candidate.is_symlink():
            raise AnalysisUnavailable("Analysis unavailable: the app-controlled pack path must not contain symlinks.")
    return candidate


def preflight_binding(repo_root: Path, pack_id: str | None):
    """Verify availability without loading models. Used only on the opt-in page."""
    directory = configured_pack_dir(repo_root, pack_id)
    from cids.workbench.model_pack import preflight_model_pack

    try:
        return preflight_model_pack(directory)
    except Exception as exc:
        raise AnalysisUnavailable("Analysis unavailable: the registered pack or runtime failed verification. Run the documented CLI preflight in the pinned dashboard environment.") from exc


def validation_message(exc: InputContractError) -> str:
    """Map private contract diagnostics to actionable public categories."""
    text = str(exc)
    if "upload-size" in text:
        return "CSV exceeds 10 MiB. Supply a smaller uncompressed file."
    if "row limit" in text:
        return "CSV exceeds 50,000 data rows. Supply fewer rows."
    if "duplicate CSV columns" in text or "schema mismatch" in text:
        return "CSV headers must contain each of the 42 FEATURE_COLUMNS exactly once, with only optional id, event_time, label and attack_cat. Check duplicate, missing and unknown headers."
    if text.startswith("event_time"):
        return "Every event_time must be a valid ISO 8601 timestamp with an explicit UTC offset."
    if "label" in text or "attack" in text:
        return "Optional label must be 0 or 1, attack_cat must name a documented family, and both must agree when supplied."
    if text.startswith("id"):
        return "Supplied IDs must be non-empty and unique."
    if "numeric" in text or "finite" in text:
        return "All numeric features must be valid, non-null, finite numbers."
    if "contains null" in text or "contains empty" in text:
        return "Categorical features must be non-null and non-empty."
    return "Supply one uncompressed UTF-8 CSV with a header, at least one data row, consistent field counts and valid quoting."


def read_upload(upload) -> bytes:
    """Check declared size first, then independently limit the actual read."""
    limit = load_workbench_config()["input"]["max_upload_bytes"]
    if upload.size > limit:
        raise InputContractError("CSV exceeds the configured upload-size limit")
    upload.seek(0)
    payload = upload.read(limit + 1)
    if len(payload) > limit:
        raise InputContractError("CSV exceeds the configured upload-size limit")
    return payload


@dataclass(frozen=True)
class VocabularyWarning:
    task: str
    feature: str
    rows: int


def vocabulary_warnings(pack, input_data: InferenceInput) -> tuple[VocabularyWarning, ...]:
    """Counts per task/column, without disclosing the unknown categorical values."""
    warnings = []
    for task in ("binary", "multiclass"):
        artifact = getattr(pack, task)
        encoder = artifact.preprocessor.transformer.named_transformers_["categorical"]
        for column, categories in zip(CATEGORICAL_FEATURES, encoder.categories_):
            count = int((~input_data.frame[column].isin(categories)).sum())
            if count:
                warnings.append(VocabularyWarning(task, column, count))
    return tuple(warnings)


@dataclass(frozen=True)
class AnalysisResult:
    input_sha256: str
    model_pack_id: str
    records: tuple[PredictionRecord, ...]
    warnings: tuple[VocabularyWarning, ...]


@dataclass
class AnalysisSession:
    binding: tuple[str, str | None] | None = None
    input_data: InferenceInput | None = None
    result: AnalysisResult | None = None
    error: str | None = None
    revision: int = 0
    uploader_epoch: int = 0
    upload_identity: tuple | None = None

    def invalidate(self, *, reset_uploader: bool = False) -> None:
        self.input_data = None
        self.result = None
        self.error = None
        self.upload_identity = None
        self.revision += 1
        if reset_uploader:
            self.uploader_epoch += 1

    def bind(self, repo_root: Path, pack_id: str | None) -> None:
        binding = (str(Path(repo_root).resolve()), pack_id)
        if binding != self.binding:
            self.invalidate(reset_uploader=True)
            self.binding = binding

    def receive(self, upload) -> None:
        if upload is None:
            if self.input_data is not None or self.result is not None or self.error:
                self.invalidate()
            return
        try:
            payload = read_upload(upload)
            digest = hashlib.sha256(payload).hexdigest()
            identity = (getattr(upload, "file_id", None), digest)
            if self.input_data is not None and identity == self.upload_identity:
                return
            self.invalidate()  # A failed replacement cannot retain old results.
            self.input_data = parse_inference_csv(payload)
            self.upload_identity = identity
        except InputContractError as exc:
            self.invalidate()
            self.error = validation_message(exc)
        except Exception:
            self.invalidate()
            self.error = "CSV could not be validated. Supply a bounded, contract-valid CSV."

    def analyze(self, *, before_scoring: Callable | None = None) -> None:
        """Each explicit action uses the verified loader again. Retain no model."""
        self.result = None
        self.error = None
        self.revision += 1
        if self.input_data is None or self.binding is None:
            self.error = "Select a valid CSV before analysis."
            return
        try:
            root, pack_id = self.binding
            directory = configured_pack_dir(Path(root), pack_id)
            from cids.workbench.inference import infer, load_model_pack

            pack = load_model_pack(directory)
            if pack.model_pack_id != pack_id:
                raise AnalysisUnavailable("configured pack identity changed")
            warnings = vocabulary_warnings(pack, self.input_data)
            if before_scoring:
                before_scoring(warnings)
            records = infer(pack, self.input_data)
            # Bind outputs to input order before any display sorting/filtering.
            if (tuple(r.record_id for r in records) != tuple(self.input_data.frame["id"])
                    or any(r.model_pack_id != pack_id or r.explanation_status != "not_requested" for r in records)):
                raise AnalysisUnavailable("prediction provenance mismatch")
            self.result = AnalysisResult(self.input_data.input_sha256, pack.model_pack_id, records, warnings)
        except Exception:
            self.invalidate()
            self.error = "Analysis failed; previous results were cleared. Check the registered pack with CLI preflight and retry with a valid CSV in the pinned environment."

    def current_result(self) -> AnalysisResult | None:
        if (self.result is not None and self.input_data is not None and self.binding is not None
                and self.result.input_sha256 == self.input_data.input_sha256
                and self.result.model_pack_id == self.binding[1]):
            return self.result
        return None


def models_disagree(record: PredictionRecord) -> bool:
    return (record.binary_prediction == "normal") != (record.family_prediction_raw == "normal")


def queue_indices(records, *, bands=QUEUE_BANDS, predictions=("normal", "attack"), disagreements_only=False, order="sequence") -> list[int]:
    """Return original indices; ties retain input order and identity."""
    indices = [i for i, r in enumerate(records) if r.queue_band in bands
               and r.binary_prediction in predictions
               and (not disagreements_only or models_disagree(r))]
    if order == "score":
        indices.sort(key=lambda i: -records[i].attack_model_score)
    elif order == "timestamp":
        indices.sort(key=lambda i: pd.Timestamp(records[i].event_time_utc))
    elif order != "sequence":
        raise ValueError("unsupported review ordering")
    return indices
