# v2.0 normal-only anomaly baseline

The anomaly baseline asks a different question from the supervised classifiers:
can a model trained only on known-normal flows identify attacks as unusual without
learning attack labels?

## Method

- Model: Isolation Forest with 300 trees and seed `42`.
- Training scope: only normal rows in the cleaned binary training partition.
- Preprocessing scope: the same normal-only rows; known attack rows do not
  contribute categorical vocabulary.
- Anomaly score: negative Isolation Forest `score_samples`, so higher values are
  more anomalous.
- Threshold: the 95th percentile of normal-training anomaly scores, selected
  before validation evaluation.
- Evaluation: binary validation partition only; the official test remains sealed.

The threshold targets an approximate 5% alert rate on known-normal training data.
It is not tuned using validation labels.

## Reproduce locally

```bash
PYTHONPATH=src python -m cids.experiments.train_anomaly \
  --data-dir dataset/unsw-nb15/raw \
  --output-dir artifacts/v2/anomaly
```

The command verifies the dataset, loads the frozen experiment configuration,
saves a trusted local `isolation_forest.joblib` artifact, and writes detailed
validation metrics to `validation_results.json`.

## Validation result

| Metric | Value |
|---|---:|
| Normal-only training rows | 41,092 |
| Normal-training alert rate | 5.0010% |
| Validation accuracy | 0.5604 |
| Validation balanced accuracy | 0.5478 |
| Validation macro F1 | 0.4682 |
| Validation false-positive rate | 5.3052% |
| Validation false-negative rate | 85.1265% |
| Validation ROC-AUC | 0.7395 |
| Validation PR-AUC | 0.7030 |

The ranking metrics show that attack flows often receive higher anomaly scores
than normal flows, but the fixed low-alert threshold misses most attacks. Generic
attacks are detected much more often than the other families, which means this
baseline is not reliable as the primary detector. It remains useful as an honest
reference for the later hybrid-detection design.
