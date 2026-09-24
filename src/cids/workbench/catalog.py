"""Assemble every committed evidence source the dashboard may display.

Each component is loaded through its existing fail-closed validator and then
bound to the frozen official-test report by the digests that report recorded.
A failure is isolated to its component so the dashboard can keep showing
verified evidence while stating exactly what is unavailable and why. Nothing
here imports Streamlit, loads a model artifact, or reads the dataset.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from cids.config import ExperimentConfigError, config_sha256, load_experiment_config
from cids.datasets.verify_manifest import DatasetVerificationError, load_manifest
from cids.final_protocol import FinalProtocolError, load_final_protocol, protocol_sha256
from cids.selection import ModelSelectionError, load_model_selection, selection_sha256
from cids.workbench.config import WorkbenchConfigError, load_workbench_config
from cids.workbench.evidence import (
    CHECKSUM_FILENAME,
    RESULT_FILENAME,
    STATE_FILENAME,
    FrozenEvidence,
    load_frozen_evidence,
)
from cids.workbench.gate_evidence import (
    GATE_CHECKSUM_FILENAME,
    GATE_REPORT_FILENAME,
    ExplanationGateEvidence,
    load_gate_evidence,
)
from cids.workbench.integrity import EvidenceError, load_json_object

REPO_ROOT = Path(__file__).resolve().parents[3]

OFFICIAL_DIR = Path("results/v2.0")
GATE_DIR = Path("results/v2.1")
EXPERIMENT_CONFIG_PATH = Path("configs/v2-baseline-v1.json")
MODEL_SELECTION_PATH = Path("configs/v2-model-selection-v1.json")
FINAL_PROTOCOL_PATH = Path("configs/v2-final-evaluation-v1.json")
WORKBENCH_CONFIG_PATH = Path("configs/v2.1-workbench-v2.json")
DATASET_MANIFEST_PATH = Path("dataset/unsw-nb15/manifest.json")

# Only validation and I/O failures are recoverable. Programming errors such as
# KeyError or TypeError propagate so they cannot masquerade as evidence status.
RECOVERABLE_ERRORS = (
    EvidenceError,
    ExperimentConfigError,
    ModelSelectionError,
    FinalProtocolError,
    DatasetVerificationError,
    WorkbenchConfigError,
    UnicodeDecodeError,
    OSError,
)


class ComponentStatus(str, Enum):
    VERIFIED = "verified"
    MISSING = "missing"
    FAILED = "failed"
    SKIPPED = "skipped"


class CatalogHealth(str, Enum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class EvidenceComponent:
    key: str
    title: str
    purpose: str
    status: ComponentStatus
    detail: str
    paths: tuple[Path, ...]
    required: bool = False


@dataclass(frozen=True)
class EvidenceCatalog:
    repo_root: Path
    components: tuple[EvidenceComponent, ...]
    official: FrozenEvidence | None
    experiment_config: dict | None
    selection: dict | None
    protocol: dict | None
    manifest: dict | None
    workbench_policy: dict | None
    gate: ExplanationGateEvidence | None

    def component(self, key: str) -> EvidenceComponent:
        for component in self.components:
            if component.key == key:
                return component
        raise KeyError(key)

    @property
    def health(self) -> CatalogHealth:
        if any(
            c.required and c.status is not ComponentStatus.VERIFIED
            for c in self.components
        ):
            return CatalogHealth.BLOCKED
        if all(c.status is ComponentStatus.VERIFIED for c in self.components):
            return CatalogHealth.COMPLETE
        return CatalogHealth.DEGRADED

    def relative(self, path: Path) -> str:
        """Display a path relative to the repository root when possible."""
        try:
            return path.resolve().relative_to(self.repo_root.resolve()).as_posix()
        except ValueError:
            return str(path)


@dataclass(frozen=True)
class _Spec:
    key: str
    title: str
    purpose: str
    paths: tuple[Path, ...]
    required: bool = False


class _Builder:
    """Record component outcomes while loading evidence in dependency order."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.components: list[EvidenceComponent] = []

    def _record(self, spec: _Spec, status: ComponentStatus, detail: str) -> None:
        self.components.append(
            EvidenceComponent(
                key=spec.key,
                title=spec.title,
                purpose=spec.purpose,
                status=status,
                detail=detail,
                paths=tuple(self.root / path for path in spec.paths),
                required=spec.required,
            )
        )

    def load(
        self,
        spec: _Spec,
        loader: Callable[[], tuple[object, str]],
        *,
        prerequisites: tuple[tuple[str, object | None], ...] = (),
    ):
        blocked = [name for name, value in prerequisites if value is None]
        if blocked:
            self._record(
                spec,
                ComponentStatus.SKIPPED,
                "Not checked because a prerequisite is unavailable: "
                + ", ".join(blocked)
                + ".",
            )
            return None
        absent = [
            path.as_posix()
            for path in spec.paths
            if not (self.root / path).exists() and not (self.root / path).is_symlink()
        ]
        if absent:
            self._record(
                spec,
                ComponentStatus.MISSING,
                "Required evidence is absent: " + ", ".join(absent) + ".",
            )
            return None
        try:
            value, detail = loader()
        except RECOVERABLE_ERRORS as exc:
            self._record(spec, ComponentStatus.FAILED, _describe(exc))
            return None
        self._record(spec, ComponentStatus.VERIFIED, detail)
        return value


def _describe(exc: BaseException) -> str:
    message = str(exc) or type(exc).__name__
    return f"{type(exc).__name__}: {message}"


def _require_digest(label: str, actual: str, recorded: object) -> None:
    if actual != recorded:
        raise EvidenceError(
            f"{label} canonical SHA-256 {actual} does not match the digest "
            f"recorded by the official run ({recorded})"
        )


def _bind_manifest(manifest: dict, official: FrozenEvidence) -> None:
    recorded = official.report["dataset_files"]
    by_role: dict[str, dict] = {}
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("role"), str):
            raise EvidenceError("dataset manifest entries must be objects with a role")
        if entry["role"] in by_role:
            raise EvidenceError(f"dataset manifest repeats role {entry['role']!r}")
        by_role[entry["role"]] = entry
    if set(by_role) != set(recorded):
        raise EvidenceError("dataset manifest roles differ from the official run")
    for role, expected in recorded.items():
        entry = by_role[role]
        for key in ("filename", "size_bytes", "records", "sha256"):
            if entry.get(key) != expected.get(key):
                raise EvidenceError(
                    f"dataset manifest {role} {key} differs from the official run"
                )


def _bind_gate(gate: ExplanationGateEvidence, official: FrozenEvidence) -> None:
    """Require the gate to describe artifacts consistent with the frozen run."""
    runtime = gate.report["environment"]
    for task, gate_task in gate.tasks.items():
        result = official.report["tasks"][task]
        metadata = result["metadata"]
        if gate_task.model_name != metadata["model_name"]:
            raise EvidenceError(f"gate {task} model differs from the official run")
        if list(gate_task.class_labels) != result["official_test_metrics"]["labels"]:
            raise EvidenceError(
                f"gate {task} class order differs from the official run"
            )
        if gate_task.transformed_feature_count != (
            metadata["preprocessor"]["output_feature_count"]
        ):
            raise EvidenceError(
                f"gate {task} transformed width differs from the frozen preprocessor"
            )
        for library, version in metadata["library_versions"].items():
            if runtime.get(library) != version:
                raise EvidenceError(
                    f"gate {task} ran with {library} {runtime.get(library)!r}, "
                    f"not the frozen {version!r}"
                )


def load_catalog(repo_root: str | Path = REPO_ROOT) -> EvidenceCatalog:
    root = Path(repo_root)
    builder = _Builder(root)

    official = builder.load(
        _Spec(
            "official_results",
            "v2.0 official-test results",
            "Every official-test metric, confusion matrix, and split count.",
            (
                OFFICIAL_DIR / RESULT_FILENAME,
                OFFICIAL_DIR / STATE_FILENAME,
                OFFICIAL_DIR / CHECKSUM_FILENAME,
            ),
            required=True,
        ),
        lambda: (
            load_frozen_evidence(root / OFFICIAL_DIR),
            (
                "SHA-256 of both files matches the pinned digests and SHA256SUMS; "
                "report and run state agree."
            ),
        ),
    )

    def experiment_loader():
        config = load_experiment_config(root / EXPERIMENT_CONFIG_PATH)
        digest = config_sha256(config)
        _require_digest(
            "Experiment configuration",
            digest,
            official.report["experiment_config_sha256"],
        )
        return config, f"Canonical digest {digest} matches the official run."

    experiment_config = builder.load(
        _Spec(
            "experiment_config",
            "Frozen experiment configuration",
            "Candidate models, ranking rule, split seed and validation fraction.",
            (EXPERIMENT_CONFIG_PATH,),
        ),
        experiment_loader,
        prerequisites=(("official results", official),),
    )

    def selection_loader():
        selection = load_model_selection(
            root / MODEL_SELECTION_PATH, config=experiment_config
        )
        digest = selection_sha256(selection, experiment_config)
        _require_digest(
            "Model-selection record", digest, official.report["model_selection_sha256"]
        )
        return selection, f"Canonical digest {digest} matches the official run."

    selection = builder.load(
        _Spec(
            "model_selection",
            "Frozen model-selection record",
            "Validation metrics that selected each model before the test was unsealed.",
            (MODEL_SELECTION_PATH,),
        ),
        selection_loader,
        prerequisites=(("experiment configuration", experiment_config),),
    )

    def protocol_loader():
        protocol = load_final_protocol(
            root / FINAL_PROTOCOL_PATH, config=experiment_config, selection=selection
        )
        digest = protocol_sha256(
            protocol, config=experiment_config, selection=selection
        )
        _require_digest(
            "Final evaluation protocol",
            digest,
            official.report["final_protocol_sha256"],
        )
        return protocol, f"Canonical digest {digest} matches the official run."

    protocol = builder.load(
        _Spec(
            "final_protocol",
            "Final evaluation protocol",
            "One-run guard, refit scope, and reproduction tolerance.",
            (FINAL_PROTOCOL_PATH,),
        ),
        protocol_loader,
        prerequisites=(("model-selection record", selection),),
    )

    def manifest_loader():
        # The manifest is bound by content, not pinned by digest, so parse it
        # strictly (object root, no duplicate keys) before the dataset checks.
        load_json_object(root / DATASET_MANIFEST_PATH)
        manifest = load_manifest(root / DATASET_MANIFEST_PATH)
        _bind_manifest(manifest, official)
        return (
            manifest,
            (
                "Filenames, sizes, record counts and SHA-256 match the dataset "
                "files recorded by the official run."
            ),
        )

    manifest = builder.load(
        _Spec(
            "dataset_manifest",
            "UNSW-NB15 dataset manifest",
            "Pinned identity of the two official prepared CSV partitions.",
            (DATASET_MANIFEST_PATH,),
        ),
        manifest_loader,
        prerequisites=(("official results", official),),
    )

    workbench_policy = builder.load(
        _Spec(
            "workbench_policy",
            "v2.1 workbench policy",
            "Explanation algorithm, bounds and tolerances approved in Phase 1.",
            (WORKBENCH_CONFIG_PATH,),
        ),
        lambda: (
            load_workbench_config(root / WORKBENCH_CONFIG_PATH),
            "Schema and frozen policy values validated.",
        ),
    )

    def gate_loader():
        gate = load_gate_evidence(workbench_policy, root / GATE_DIR)
        _bind_gate(gate, official)
        return (
            gate,
            (
                "SHA-256 matches the pinned digest; policy digest, class order, "
                "transformed width and library versions agree with v2.0."
            ),
        )

    gate = builder.load(
        _Spec(
            "explanation_gate",
            "v2.1 explanation-gate report",
            "Feasibility and correctness checks for the bounded SHAP method.",
            (GATE_DIR / GATE_REPORT_FILENAME, GATE_DIR / GATE_CHECKSUM_FILENAME),
        ),
        gate_loader,
        prerequisites=(
            ("workbench policy", workbench_policy),
            ("official results", official),
        ),
    )

    return EvidenceCatalog(
        repo_root=root,
        components=tuple(builder.components),
        official=official,
        experiment_config=experiment_config,
        selection=selection,
        protocol=protocol,
        manifest=manifest,
        workbench_policy=workbench_policy,
        gate=gate,
    )
