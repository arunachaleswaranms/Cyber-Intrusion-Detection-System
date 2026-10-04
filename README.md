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
| v2.1 | UNSW-NB15 | Evidence-first local analyst workbench | Phases 1–2 and 3A–3C implemented; Phase 3C independently reviewed, awaiting PR merge; Phase 3D next after merge, not started |

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
evidence provenance. Global feature importance is **not** shown: the committed
gate report contains correctness diagnostics only, and attribution views are
scheduled for Phase 4. See [`docs/dashboard.md`](docs/dashboard.md) for evidence
sources, degraded states, validation, and limitations.

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
probabilities or production risk. Phase 3D label-backed review, threshold
simulation and export have not started.

## Local CSV analysis (v2.1 Phase 3C)

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
Clearing references is not secure memory erasure. Optional labels are validated
only, and `explanation_status` remains `not_requested`. These offline research
predictions are separate from the frozen benchmark. See
[`docs/dashboard.md`](docs/dashboard.md) for lifecycle and queue semantics.

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
