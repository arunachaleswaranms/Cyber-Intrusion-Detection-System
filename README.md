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
| v2.0 | UNSW-NB15 | Leakage-resistant binary and attack-family baselines | In progress |

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
- Selects models using validation data only; the official test remains sealed.
- Reports macro/weighted precision, recall and F1, false-positive and
  false-negative rates, ROC-AUC, PR-AUC, per-family detection rate, confusion
  matrices, and prediction latency.
- Persists trusted local model artifacts and machine-readable experiment results.

See [`docs/supervised-baselines.md`](docs/supervised-baselines.md),
[`docs/anomaly-baseline.md`](docs/anomaly-baseline.md), and
[`docs/model-selection.md`](docs/model-selection.md) for methodology and current
validation results.

The selected models are now frozen. The guarded final procedure is documented in
[`docs/final-evaluation-protocol.md`](docs/final-evaluation-protocol.md). The
official test has not yet been evaluated.

## Repository structure

```text
.
├── dataset/                     # Dataset manifests and download instructions
├── configs/                     # Frozen v2.0 experiment and selection records
├── docs/                        # Decisions, schemas, policies, and results
├── notebooks/                   # Original exploratory notebooks
├── src/
│   ├── cids/                    # Versioned v2.0 package
│   │   ├── datasets/
│   │   ├── experiments/
│   │   └── modeling/
│   ├── data_preprocessing.py    # v1.1 historical baseline
│   ├── model_training.py
│   └── model_evaluation.py
├── tests/
├── .github/workflows/test.yml
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

## Limitations

UNSW-NB15 and KDD Cup 1999 contain synthetic, dated research traffic. Validation
performance does not demonstrate effectiveness against current production
networks. v2.0 currently consumes prepared CSV flow records; it does not capture
packets, extract live flows, or automate security response. Review the roadmap
before interpreting or extending the project.

## License

Licensed under the [MIT License](LICENSE).
