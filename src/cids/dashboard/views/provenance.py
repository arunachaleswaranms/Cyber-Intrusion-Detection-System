"""Evidence and provenance: where every displayed claim comes from."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cids.dashboard.components import (
    STATUS_LABELS,
    component_problem,
    count_column,
    fact_tile,
    full_height,
    health_badge,
    page_header,
)
from cids.workbench.catalog import (
    EXPERIMENT_CONFIG_PATH,
    FINAL_PROTOCOL_PATH,
    GATE_DIR,
    MODEL_SELECTION_PATH,
    OFFICIAL_DIR,
    ComponentStatus,
    EvidenceCatalog,
)
from cids.workbench.confusion import consistency_checks
from cids.workbench.formatting import format_seconds, format_timestamp
from cids.workbench.reporting import (
    TASK_TITLES,
    TASKS,
    model_display_name,
    partition_table,
)


def _components(catalog: EvidenceCatalog) -> None:
    st.header("Evidence components")
    st.caption(
        "Loaded on every page view. Hashes are recomputed each time; nothing is cached"
        " between interactions."
    )
    frame = pd.DataFrame(
        [
            {
                "Component": c.title,
                "Status": STATUS_LABELS[c.status],
                "Required": "yes" if c.required else "no",
                "Supports": c.purpose,
                "Check": c.detail,
                "Files": "\n".join(catalog.relative(path) for path in c.paths),
            }
            for c in catalog.components
        ]
    )
    st.dataframe(frame, hide_index=True, width="stretch")
    for component in catalog.components:
        if component.status is not ComponentStatus.VERIFIED:
            component_problem(catalog, component)


def _file_pins(catalog: EvidenceCatalog) -> None:
    rows = []
    if catalog.official is not None:
        for filename, digest in catalog.official.sha256.items():
            rows.append(
                {
                    "File": (OFFICIAL_DIR / filename).as_posix(),
                    "SHA-256 (pinned, verified)": digest,
                }
            )
    if catalog.gate is not None:
        for filename, digest in catalog.gate.sha256.items():
            rows.append(
                {
                    "File": (GATE_DIR / filename).as_posix(),
                    "SHA-256 (pinned, verified)": digest,
                }
            )
    st.subheader("Pinned evidence files")
    st.caption(
        "Each digest is pinned in code and in the directory's SHA256SUMS; both must"
        " agree with the file bytes."
    )
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("No evidence file could be verified.", icon=":material/info:")


def _bindings(catalog: EvidenceCatalog) -> None:
    report = catalog.official.report
    st.subheader("Digests recorded by the official run")
    st.caption(
        "Configuration digests are SHA-256 over canonical JSON (sorted keys, compact"
        " separators), recomputed from the committed files."
    )
    bound = {
        "experiment_config_sha256": (
            "Experiment configuration",
            EXPERIMENT_CONFIG_PATH.as_posix(),
            catalog.experiment_config,
        ),
        "model_selection_sha256": (
            "Frozen model selection",
            MODEL_SELECTION_PATH.as_posix(),
            catalog.selection,
        ),
        "final_protocol_sha256": (
            "Final evaluation protocol",
            FINAL_PROTOCOL_PATH.as_posix(),
            catalog.protocol,
        ),
        "reproduction_selection_sha256": (
            "Clean reproduction selection",
            "not committed (local artifact)",
            None,
        ),
    }
    rows = []
    for key, (label, path, value) in bound.items():
        if path.startswith("not committed"):
            state = "recorded only; cannot be recomputed from the repository"
        else:
            state = "matches committed file" if value is not None else "not verified"
        rows.append(
            {
                "Record": label,
                "Recorded SHA-256": report[key],
                "Committed file": path,
                "State": state,
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.subheader("Dataset identity")
    dataset_rows = [
        {
            "Role": role,
            "Filename": entry["filename"],
            "Records": entry["records"],
            "Size (bytes)": entry["size_bytes"],
            "SHA-256": entry["sha256"],
        }
        for role, entry in report["dataset_files"].items()
    ]
    st.dataframe(
        pd.DataFrame(dataset_rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Records": count_column("Records"),
            "Size (bytes)": count_column("Size (bytes)"),
        },
    )
    manifest_state = STATUS_LABELS[catalog.component("dataset_manifest").status].lower()
    st.caption(
        f"Dataset manifest `dataset/unsw-nb15/manifest.json`: {manifest_state}. The"
        " dashboard never reads the CSV files themselves."
    )


def _run(catalog: EvidenceCatalog) -> None:
    report = catalog.official.report
    st.header("Official run")
    columns = st.columns(3)
    with columns[0]:
        fact_tile(
            "Started",
            format_timestamp(report["started_at_utc"]),
            "Recorded in the report and the run state.",
        )
    with columns[1]:
        fact_tile(
            "Completed",
            format_timestamp(report["completed_at_utc"]),
            "Recorded in the report and the run state.",
        )
    with columns[2]:
        fact_tile(
            "Status",
            report["official_test_status"],
            "Must be `evaluated_once` in both the report and the run state.",
        )
    if catalog.protocol is not None:
        guard = catalog.protocol["run_guard"]
        st.caption(
            f"Protocol `{catalog.protocol['protocol_version']}`:"
            f" {catalog.protocol['official_test']['evaluation_runs']} evaluation run, a"
            " required confirmation phrase, a new output directory"
            f" (`output_directory_must_not_exist={guard['output_directory_must_not_exist']}`),"
            " and a reproduction tolerance of"
            f" {guard['reproduction_metric_abs_tolerance']}."
        )


def _models(catalog: EvidenceCatalog) -> None:
    st.header("Model identity")
    rows = {}
    for task in TASKS:
        result = catalog.official.report["tasks"][task]
        metadata = result["metadata"]
        preprocessor = metadata["preprocessor"]
        gate_digest = (
            catalog.gate.tasks[task].artifact_sha256
            if catalog.gate is not None
            else "gate evidence unavailable"
        )
        rows[TASK_TITLES[task]] = {
            "Model": model_display_name(metadata["model_name"]),
            "Estimator class": metadata["estimator_class"],
            "Artifact filename": result["artifact"],
            "Artifact SHA-256 (from v2.1 gate)": gate_digest,
            "Artifact version": metadata["artifact_version"],
            "Training scope": metadata["training_scope"],
            "Training rows": f"{metadata['development_training_rows']:,}",
            "Seed": str(metadata["seed"]),
            "Schema": metadata["schema_version"],
            "Preprocessor": (
                f"{preprocessor['preprocessor_version']} ·"
                f" {preprocessor['input_feature_count']} →"
                f" {preprocessor['output_feature_count']} features"
            ),
            "Fit time": format_seconds(metadata["fit_seconds"]),
            "Libraries": ", ".join(
                f"{name} {version}"
                for name, version in metadata["library_versions"].items()
            ),
        }
    identity = pd.DataFrame(rows)
    st.dataframe(identity, width="stretch", height=full_height(len(identity)))
    st.caption(
        "The v2.0 report records artifact filenames but not artifact hashes. The"
        " digests shown come from the v2.1 gate, which hashed the maintainer's local"
        " artifacts. Model binaries are pickle-based and deliberately not committed;"
        " this dashboard never loads them."
    )
    with st.expander("Estimator parameters", icon=":material/tune:"):
        columns = st.columns(2)
        for column, task in zip(columns, TASKS):
            with column:
                st.markdown(f"**{TASK_TITLES[task]}**")
                st.json(
                    catalog.official.report["tasks"][task]["metadata"][
                        "estimator_parameters"
                    ],
                    expanded=False,
                )


def _lineage(catalog: EvidenceCatalog) -> None:
    st.header("Data lineage")
    for task in TASKS:
        split = catalog.official.report["tasks"][task]["split_report"]
        st.subheader(TASK_TITLES[task])
        st.dataframe(
            partition_table(catalog.official, task), hide_index=True, width="stretch"
        )
        removed = split["removed_from_training"]
        st.caption(
            "Removed from training before splitting: "
            + ", ".join(
                f"{name.replace('_', ' ')} {value:,}" for name, value in removed.items()
            )
            + f". Policy `{split['split_policy_version']}`, seed {split['seed']},"
            f" validation fraction {split['validation_fraction']}."
        )


def _consistency(catalog: EvidenceCatalog) -> None:
    st.header("Internal consistency")
    checks = consistency_checks(catalog.official)
    failed = [check for check in checks if not check.passed]
    if failed:
        st.error(
            f"**{len(failed)} of {len(checks)} consistency checks failed.** The report"
            " contradicts itself; treat its metrics as unreliable.",
            icon=":material/gpp_bad:",
        )
    else:
        st.success(
            f"All {len(checks)} listed checks passed: each checked metric equals the"
            " value implied by the report's own confusion matrices and split counts.",
            icon=":material/task_alt:",
        )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Scope": c.scope,
                    "Check": c.name,
                    "Result": "pass" if c.passed else "FAIL",
                    "Detail": c.detail,
                }
                for c in checks
            ]
        ),
        hide_index=True,
        width="stretch",
        height=full_height(len(checks)),
    )
    st.caption(
        "These checks re-derive nothing from data or models; they only confirm the"
        " frozen report agrees with itself."
    )


def _reproduce() -> None:
    st.header("Verify it yourself")
    st.markdown("Check the evidence files against their committed digests:")
    st.code(
        "(cd results/v2.0 && shasum -a 256 -c SHA256SUMS)\n(cd results/v2.1 && shasum"
        " -a 256 -c SHA256SUMS)",
        language="bash",
    )
    st.markdown(
        "Run the test suite, which re-validates the same evidence without the dataset"
        " or models:"
    )
    st.code("pip install -r requirements-dev.txt\npytest -q", language="bash")
    st.markdown(
        "The validation reproduction and the guarded official-test protocol are"
        " documented in `docs/final-evaluation-protocol.md`. The official test has been"
        " evaluated once and **must not be rerun**; reproduce the validation stage"
        " instead."
    )


def render(catalog: EvidenceCatalog) -> None:
    page_header(
        "Evidence & provenance",
        "Every component, digest, and consistency check behind the displayed results.",
    )
    health_badge(catalog)
    _components(catalog)
    _file_pins(catalog)
    if catalog.official is not None:
        _bindings(catalog)
        _run(catalog)
        _models(catalog)
        _lineage(catalog)
        _consistency(catalog)
    _reproduce()
