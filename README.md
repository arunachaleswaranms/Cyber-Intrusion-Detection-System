# Cyber Intrusion Detection System

A reproducible network-intrusion detection research project built with classical
machine learning. The repository preserves its original college-project history
while rebuilding the methodology in controlled, testable releases.

Development status, decisions, and the staged roadmap are maintained in
[`PROJECT_PLAN.md`](PROJECT_PLAN.md).

> This is an offline research and portfolio project, not a production IDS. It
> does not inspect, block, or respond to live traffic.

## Release tracks

| Release | Dataset | Purpose | Status |
|---|---|---|---|
| v1.0 | KDD Cup 1999 | Original college project | Preserved as tag `v1.0.0` |
| v1.1 | KDD Cup 1999 | Repaired, reproducible historical baseline | Published as tag `v1.1.0` |
| v2.0 | UNSW-NB15 | Leakage-resistant binary and attack-family baselines | Published as tag [`v2.0.0`](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/releases/tag/v2.0.0) |
| v2.1 | UNSW-NB15 | Evidence-first local analyst workbench | Phases 1–5 implemented, reviewed and merged; stable [v2.1.0](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/releases/tag/v2.1.0) published 2026-10-04 |

[v2.1.0](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/releases/tag/v2.1.0) was published as a stable GitHub Release on
2026-10-04 at `ed2e38a9014ee52756276bb0707d0de09ea3df35`. Release closure
[PR #8](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/pull/8) is merged; all five closure
post-merge jobs passed in [run 37207887388](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/actions/runs/37207887388).
The project is paused for maintenance; no next-version implementation is authorized.

The roadmap retains v3.0 as a possible future milestone requiring fresh design
and explicit approval.

The approved v2.1 boundary, user journeys, safety controls, contracts, phases,
and acceptance criteria are in [`docs/v2.1-design.md`](docs/v2.1-design.md).
Phase 1 framework-independent contracts are implemented. The original
TreeExplainer route failed its selected-artifact additivity check, so the
bounded model-agnostic fallback in
[`ADR 0003`](docs/decisions/0003-v2.1-explanation-fallback.md) was tested against
both original local artifacts and accepted. The preserved gate evidence is in
[`results/v2.1`](results/v2.1); see
[`docs/shap-compatibility-gate.md`](docs/shap-compatibility-gate.md) for limits.
Phase 2 adds the evidence-first Streamlit dashboard described below. Phase 3A
adds command-line registration of the trusted local v2.0 model pack. Phase 3B
adds verified deserialization and framework-independent inference. Phase 3C
adds a separate opt-in CSV analysis page and bounded research review queue.

## Evidence dashboard (v2.1 Phase 2)

A local Streamlit dashboard presents the frozen v2.0 results from a clean clone:
no dataset, no model artifact, and no network access are needed. Every number
is read from committed, SHA-256-verified evidence and tagged with its evaluation
stage (official test, validation, or explanation gate) and exact JSON source.
Evidence pages never load a model or recompute a result. Evidence mode remains
the startup default, including when a local pack is configured.

```bash
python3.12 -m venv .venv-dashboard
source .venv-dashboard/bin/activate
python -m pip install pip==26.2.1
python -m pip install -r requirements-dashboard.txt
streamlit run dashboard/app.py    # from the repository root
```

The server binds to `127.0.0.1` with usage telemetry disabled. Pages cover the
overview, binary detection, attack families, explainability status, and
evidence provenance. The committed gate contains correctness diagnostics only. Phase 4 adds explicit
selected-record SHAP and an offline global model-reliance resource view; both
remain unavailable without verified local resources. See [`docs/dashboard.md`](docs/dashboard.md) for evidence
sources, degraded states, validation, and limitations.

## Local container packaging (v2.1 Phase 5)

Python 3.12.14 is pinned by official image digest. The existing dashboard lock
is preserved, with a Linux-only watchdog pin in `requirements-container.txt`.
The local workflow runs non-root with a read-only filesystem, bounded ephemeral
tmpfs, dropped capabilities and **127.0.0.1** host publication:

```bash
docker compose build
docker compose up -d --wait
curl --fail --max-time 5 http://127.0.0.1:8501/_stcore/health
docker compose down --timeout 15
```

Evidence and the synthetic preview/download require no dataset/model. See
[container operations](docs/container.md) for separate trusted-analysis and
explanation/global-resource commands, private read-only mounts, non-root UID
permissions, health verification and exact build-context controls. The explicit
container profile binds 0.0.0.0 internally; ordinary host launch remains loopback
and fail closed. Docker's host port mapping controls external exposure, which
the app cannot independently prove. Registration/preparation are host CLI actions.

[Release acceptance](docs/release-readiness-v2.1.md) records verified platforms,
counts and verification scope. Independent Phase 5 code/documentation review found
no blocking issues (606 passed / 8 skipped locally; dependency consistency passed).
[PR #7](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/pull/7)
merged at `665a3efeb77e10ab5d55adcb8d8d7e6b499d951b`; all five post-merge jobs passed in
[run 37198188962](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/actions/runs/37198188962).
[v2.1.0 notes](docs/release-notes-v2.1.0.md) describe the published release;
[publication record](docs/release-handoff-v2.1.0.md) preserves the completed
procedure as historical reference. Frozen benchmark weaknesses remain intact.

## Trusted model-pack registration (v2.1 Phase 3A)

The maintainer can register the original, uncommitted v2.0 final artifacts as
an app-controlled local model pack. Registration is command-line only. It
accepts each source only if its SHA-256 equals the digest recorded by the
committed, checksum-verified explanation gate. It copies the files without
deserializing them and verifies the finished pack with the existing preflight.
Run it in the pinned Python 3.12.14 workbench environment:

```bash
PYTHONPATH=src python -m cids.experiments.register_model_pack \
  --binary-artifact artifacts/v2/official-test-v1/binary-hist_gradient_boosting.joblib \
  --multiclass-artifact artifacts/v2/official-test-v1/multiclass-hist_gradient_boosting.joblib \
  --pack-root artifacts/v2.1/model-packs \
  --confirm REGISTER_TRUSTED_LOCAL_V2_MODEL_PACK
```

Joblib is pickle-based: a matching hash does not make an untrusted file safe.
Packs are written under the ignored `artifacts/v2.1/model-packs/` and never
committed. See [`docs/model-pack-registration.md`](docs/model-pack-registration.md)
for the trust boundary, checks, manifest, preflight, and manual removal.

## Verified local inference (v2.1 Phase 3B)

Use the pinned Python 3.12.14 workbench environment. A caller supplies a local,
CLI-registered pack directory and bytes from a bounded feature CSV. The
Phase 3C browser page can use only one pack bound outside the UI.

```python
from pathlib import Path
from cids.workbench.contracts import parse_inference_csv
from cids.workbench.inference import infer, load_model_pack

pack = load_model_pack("artifacts/v2.1/model-packs/<model_pack_id>")
data = parse_inference_csv(Path("my-development-features.csv").read_bytes())
records = infer(pack, data)
```

Run this with `PYTHONPATH=src` from the repository root. The loader preflights
the pack, reads each artifact into a bounded buffer, checks that buffer's exact
size and SHA-256, deserializes the same bytes, and validates both fitted final
artifacts before returning a pack. Joblib is executable trusted code; digest
identity does not establish safety. Only the gate-anchored maintainer final
artifacts are accepted. The service scores binary and multiclass models
independently in batches, preserves supplied IDs and UTC timestamps, and emits
`PredictionRecord` objects with uncalibrated model scores, queue bands, and
`explanation_status="not_requested"`. These scores are not calibrated
probabilities or production risk. Phase 3D adds uploaded-label review,
ephemeral threshold simulation and explicit safe export; merged through PR #5 with post-merge CI passing.

## Local CSV analysis, review and export (v2.1 Phases 3C–3D)

From this repository root, use Python **3.12.14** and the pinned dashboard
environment above. Register the original trusted pack with the Phase 3A CLI
first, then bind its single lowercase 64-character ID outside the browser:

```bash
PYTHONPATH=src python -m cids.experiments.preflight_model_pack \
  --pack-dir artifacts/v2.1/model-packs/<model_pack_id>
CIDS_MODEL_PACK_ID=<model_pack_id> streamlit run dashboard/app.py \
  --server.address 127.0.0.1 --browser.gatherUsageStats false \
  --client.disableDataExport true
```

The ID resolves only under `artifacts/v2.1/model-packs/`; arbitrary paths,
URLs, model selection, model uploads and trust controls are absent from the
browser. Configuration and page preflight do not deserialize models. Navigate
to **Local CSV analysis**, upload one uncompressed UTF-8 CSV, then explicitly
choose **Analyze CSV**. Each analysis uses the hardened verified loader anew.

The input limit is **10 MiB / 50,000 data rows**, with exactly the 42
`FEATURE_COLUMNS` plus optional `id`, `event_time`, `label`, `attack_cat`.
Out-of-vocabulary values are counted for each model before scoring; the fitted
encoder retains `handle_unknown="ignore"`. Results show independent binary and
raw family predictions, model scores (uncalibrated), queue bands, provenance,
filters, counts and one record's bounded feature detail. Review tables hold at
most 200 records per page. Timestamp views require supplied offset-aware
`event_time`, normalized to UTC; otherwise the view is **Record sequence**.

Uploads and results live only in session memory. Replacement (including an
invalid replacement), removal, pack changes, failure and **Clear analysis**
invalidate earlier results; clear also resets the uploader. Input digests and
pack IDs bind result provenance. Display reruns do not reload or score models.
Clearing references is not secure memory erasure. Uploaded `label` enables
TP/TN/FP/FN, sample confusion matrix and explicit-denominator precision, recall,
F1, FPR and FNR; undefined rates show Unavailable. Uploaded `attack_cat`
independently enables raw-family misclassification review. Neither label column
means prediction review only; ground truth is never inferred.

With `label`, **ephemeral, sample-specific threshold simulation** compares
stored attack scores using strict `>` (baseline 0.50, equality normal) on the
full current uploaded sample, including filtered-out rows. Reset restores the
baseline. This does not change original predictions or the frozen 0.90 queue
policy, reload models, or score again. Scores remain uncalibrated. Uploaded
feature rows cannot establish provenance: do not upload official-test rows or
use benchmark evidence for threshold selection.

Choose **Full analysis** or **Current filtered review** (all matching pages),
choose JSON (default) or CSV, then **Prepare export** and use the dedicated
download. Exports omit raw features, paths and artifact contents; include
stable IDs, original/review outputs, digest, pack ID, provenance and scope.
Optional simulation is explicitly separate. JSON is strict, with undefined
metrics null; CSV neutralizes spreadsheet formulas behind whitespace/control
characters and properly quotes cells. Filenames are fixed. Analysis lifecycle
and export-context changes discard prepared downloads. Built-in dataframe
export/copy stays disabled. `explanation_status` remains `not_requested`.
Phase 3D merged through PR #5 at `5305f0a`; post-merge CI passed. Local Phase 4
attribution states are separate from this exported analysis snapshot. These offline research predictions are separate from frozen evidence. See
[`docs/dashboard.md`](docs/dashboard.md) for lifecycle and queue semantics.

## Bounded explainability and synthetic demonstration (v2.1 Phase 4)

Phase 4 merged through PR #6 at `ce7f37e` with no blocking review findings and
passing post-merge CI. Phase 5 is merged through PR #7 with no blocking independent
review findings and successful five-job post-merge CI. Stable v2.1.0 is published;
the project is paused for maintenance.

The **Synthetic feature sample** page previews/downloads eight deterministic,
non-sensitive, non-realistic arithmetic rows on a clean clone. It supplies no
hosts, IPs, timestamps or labels, copies no official data, and is not benchmark
evidence. Upload [the CSV](samples/synthetic-features-v1.csv) on **Local CSV
analysis** and explicitly choose **Analyze CSV**; predictions still require the
original trusted pack. No demonstration model builder or broader trust rule is
provided.

Prepare development resources **outside the browser**, in the exact pinned
Python 3.12.14 environment:

```bash
PYTHONPATH=src python -m cids.experiments.prepare_explanation_resources \
  --pack-id "$CIDS_MODEL_PACK_ID" \
  --training-csv /private/path/UNSW_NB15_training-set.csv \
  --prepared-dir /private/path/prepared-development
# Set the printed digest, then restart the dashboard:
export CIDS_EXPLANATION_RESOURCE_ID="<printed-64-hex-resource-digest>"
PYTHONPATH=src streamlit run dashboard/app.py
```

See [resource setup](docs/explanation-resources.md) for verified prepared-partition
requirements and the explicitly approved CLI-only feature overlap-removal fallback
when those partitions are absent. Runtime resources contain only bounded feature
backgrounds and non-executable JSON, privately stored under ignored `artifacts/`.
Add `--prepare-global` explicitly to compute separate source-feature permutation
reliance on at most 256 development-validation rows (macro F1, 3 repeats, seed 42).
This is in-development reliance, not held-out benchmark evidence; the final models
were refit on train plus validation.

**Explain selected record — binary** and **— multiclass** run only after explicit
action, on one record each, using the verified loader and accepted SHAP 0.52.0
PermutationExplainer. Raw `decision_function` units remain separate from
uncalibrated scores. Baseline plus all 42 signed source contributions must
reconstruct the output; binary always explains attack (even for a normal prediction),
while multiclass explains the independent raw predicted family. Features
*influenced this model output*; this is not causal or calibrated evidence.

Fresh dedicated Python subprocess workers enforce 60 seconds per task with actual cancellation and bounded
JSON IPC; no global model/data/explanation caches. Missing/tampered resources or
worker/correctness failures leave analysis usable with honest unavailable/failed
states. Replacement, removal, clear, reanalysis, failed analysis, selection and
pack/resource changes discard stale attributions. Downloads retain the Phase 3D
schema/allowlist and omit the new attribution data. See [sample limitations](samples/README.md)
and [verification/visual QA](docs/dashboard.md).

## Current v2.0 capabilities

- Pins the official UNSW-NB15 prepared partitions by SHA-256, size, record count,
  and schema.
- Normalizes a versioned ten-class taxonomy: normal plus nine attack families.
- Removes official-test overlaps, target conflicts, and duplicate feature vectors
  from training before deterministic validation splitting.
- Fits numerical/categorical preprocessing only on the cleaned training split.
- Trains seeded Random Forest and histogram gradient-boosting baselines.
- Trains an Isolation Forest reference using only known-normal training rows.
- Enforces one versioned configuration for parameters and model selection.
- Selects models using validation data only and records one guarded official-test
  evaluation without test-driven retuning.
- Reports macro/weighted precision, recall and F1, false-positive and
  false-negative rates, ROC-AUC, PR-AUC, per-family detection rate, confusion
  matrices, and prediction latency.
- Persists trusted local model artifacts and machine-readable experiment results.

See [`docs/v2-official-test-results.md`](docs/v2-official-test-results.md),
[`docs/supervised-baselines.md`](docs/supervised-baselines.md),
[`docs/anomaly-baseline.md`](docs/anomaly-baseline.md), and
[`docs/model-selection.md`](docs/model-selection.md) for the final benchmark,
methodology, and validation results.

The selected models and official-test results are now frozen. The guarded
procedure, executed once on 2026-09-12, is documented in
[`docs/final-evaluation-protocol.md`](docs/final-evaluation-protocol.md).

| Official-test task | Model | Macro F1 | Balanced accuracy | Key limitation |
|---|---|---:|---:|---|
| Binary attack detection | Histogram Gradient Boosting | 0.8663 | 0.8595 | 26.89% false-positive rate |
| Attack-family classification | Histogram Gradient Boosting | 0.5029 | 0.5761 | Weak Analysis, Backdoor, and DoS recall |

## Repository structure

```text
.
├── dataset/                     # Dataset manifests and download instructions
├── configs/                     # Frozen v2.0 experiment and selection records
├── docs/                        # Decisions, schemas, policies, and results
├── notebooks/                   # Original exploratory notebooks
├── dashboard/app.py             # Streamlit entry point (v2.1 evidence mode)
├── results/v2.0/                # Frozen official-test JSON evidence and hashes
├── results/v2.1/                # Accepted Phase 1 explanation-gate evidence
├── src/
│   ├── cids/                    # Versioned package
│   │   ├── dashboard/           # Streamlit pages (only Streamlit importer)
│   │   ├── datasets/
│   │   ├── experiments/
│   │   ├── modeling/
│   │   └── workbench/           # Framework-independent v2.1 services
│   ├── data_preprocessing.py    # v1.1 historical baseline
│   ├── model_training.py
│   └── model_evaluation.py
├── tests/
├── .github/workflows/test.yml
├── requirements-dashboard.txt   # Pinned v2.1 dashboard environment
├── requirements-reproduction.txt
├── requirements-workbench.txt
├── requirements.txt
└── requirements-dev.txt
```

## Setup

Requires Python 3.10 or newer.

```bash
git clone https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System.git
cd Cyber-Intrusion-Detection-System
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The guarded v2.0 reproduction and one-time official evaluation use Python 3.12
with [`requirements-reproduction.txt`](requirements-reproduction.txt), which
pins the complete benchmark environment. Follow
[`docs/final-evaluation-protocol.md`](docs/final-evaluation-protocol.md) for that
workflow instead of the general setup above.

On Windows PowerShell, activate the environment with
`.venv\Scripts\Activate.ps1`.

## Run the v2.0 supervised validation benchmark

Follow [`dataset/unsw-nb15/README.md`](dataset/unsw-nb15/README.md) and place the
two official prepared CSV files under `dataset/unsw-nb15/raw/`. The command first
verifies both files against the committed manifest.

Binary classification:

```bash
PYTHONPATH=src python -m cids.experiments.train_supervised \
  --data-dir dataset/unsw-nb15/raw \
  --task binary \
  --output-dir artifacts/v2/binary
```

Attack-family classification:

```bash
PYTHONPATH=src python -m cids.experiments.train_supervised \
  --data-dir dataset/unsw-nb15/raw \
  --task multiclass \
  --output-dir artifacts/v2/multiclass
```

Each run creates two trusted local `.joblib` model artifacts and a
`validation_results.json` report. Generated artifacts and datasets are ignored by
Git. Joblib is pickle-based, so never load artifacts from untrusted sources.

Run the normal-only anomaly baseline:

```bash
PYTHONPATH=src python -m cids.experiments.train_anomaly \
  --data-dir dataset/unsw-nb15/raw \
  --output-dir artifacts/v2/anomaly
```

Apply the frozen selection rule after all three validation runs:

```bash
PYTHONPATH=src python -m cids.experiments.select_models \
  --binary-supervised-report artifacts/v2/binary/validation_results.json \
  --multiclass-supervised-report artifacts/v2/multiclass/validation_results.json \
  --anomaly-report artifacts/v2/anomaly/validation_results.json \
  --output artifacts/v2/model-selection.json
```

## Run the v1.1 historical baseline

Follow [`dataset/README.md`](dataset/README.md) to download the KDD Cup files,
then run:

```bash
python src/model_training.py \
  --train dataset/kddcup.data_10_percent.gz \
  --test dataset/corrected.gz
```

Evaluate previously saved v1.1 pipelines without retraining:

```bash
python src/model_evaluation.py \
  --test dataset/corrected.gz \
  models/random_forest.joblib \
  models/gradient_boosting.joblib
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

Tests that need SHAP or Streamlit are skipped when those packages are absent.
Install `requirements-dashboard.txt` (Python 3.12) to run the complete suite,
including the Streamlit page tests.

## Limitations

UNSW-NB15 and KDD Cup 1999 contain synthetic, dated research traffic. Validation
performance does not demonstrate effectiveness against current production
networks. v2.0 currently consumes prepared CSV flow records; it does not capture
packets, extract live flows, or automate security response. Review the roadmap
before interpreting or extending the project.

## License

Licensed under the [MIT License](LICENSE).
