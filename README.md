# Cyber Intrusion Detection System

A reproducible classical machine-learning baseline for classifying network
connections in the KDD Cup 1999 dataset.

> This project was originally created as a college project and repaired in v1.1.
> KDD Cup 1999 is intentionally retained for historical continuity; its age and
> known limitations make this a learning baseline, not a production IDS.

## What v1.1 fixes

- Prevents data leakage by fitting preprocessing only on training data.
- Reads the original KDD Cup headerless `.gz` files directly.
- Handles unseen test-set categories without fitting on the test set.
- Saves preprocessing and each classifier together as one inference pipeline.
- Uses deterministic model seeds and reports per-class metrics.
- Adds automated tests and GitHub Actions.
- Removes duplicate and unused code and invalid placeholder dataset files.

## Models and evaluation

The baseline trains Random Forest and Gradient Boosting classifiers. Evaluation
reports accuracy, a per-class precision/recall/F1 report, and a confusion matrix.
For intrusion detection, examine per-class recall and false positives instead of
using accuracy alone.

## Repository structure

```text
.
├── dataset/                 # Dataset metadata and download instructions
├── notebooks/               # Original exploratory notebooks
├── src/
│   ├── data_preprocessing.py
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

On Windows PowerShell, activate the environment with
`.venv\Scripts\Activate.ps1`.

Follow [`dataset/README.md`](dataset/README.md) to download:

```text
dataset/kddcup.data_10_percent.gz
dataset/corrected.gz
```

## Train and evaluate

Train both models, save complete pipelines under `models/`, and evaluate them on
the official corrected test set:

```bash
python src/model_training.py \
  --train dataset/kddcup.data_10_percent.gz \
  --test dataset/corrected.gz
```

Evaluate previously saved pipelines without retraining:

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

## Limitations and roadmap

KDD Cup 1999 contains synthetic, outdated traffic and duplicated records. This
baseline must not be used to claim present-day detection performance. A future
v2 can introduce a modern dataset, explicit attack-family mapping, richer IDS
metrics, explainability, and a small analyst dashboard.

## License

Licensed under the [MIT License](LICENSE).
