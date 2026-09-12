# v2.0 supervised validation baselines

This milestone compares two deterministic supervised tree baselines for both
UNSW-NB15 tasks. It is a model-development checkpoint, not the final test result.

## Evaluation boundary

The experiment runner performs these steps:

1. Verify the two official CSV files against the pinned manifest.
2. Build the task-specific cleaned training and validation partitions.
3. Fit the categorical vocabulary only on the cleaned training partition.
4. Fit each classifier only on that transformed training partition.
5. Calculate metrics only on the validation partition.
6. Save the official-test digest as provenance with status
   `sealed_not_evaluated`, without transforming or predicting the test records.

The final test partition must remain sealed until the model set, configuration,
and selection rule are frozen.

## Untuned model definitions

| Model | Main settings | Purpose |
|---|---|---|
| Random Forest | 200 trees, balanced bootstrap weights, minimum leaf size 2, square-root feature sampling | Bagged-tree reference baseline |
| Histogram Gradient Boosting | 150 iterations, learning rate 0.1, 31 leaves, L2 regularization 1.0, balanced class weights | Dependency-light boosted-tree comparison |

Both use seed `42`. These settings were selected before seeing official-test
performance and have not been hyperparameter-tuned.

Histogram Gradient Boosting is used before XGBoost or LightGBM so the first
comparison remains portable within the existing scikit-learn dependency. An
external boosting library should be added only if a later controlled validation
experiment demonstrates enough value to justify another dependency.

## Validation metrics

The machine-readable report records:

- accuracy and balanced accuracy;
- macro and weighted precision, recall, and F1;
- binary FPR/FNR or macro one-vs-rest multiclass FPR/FNR;
- binary or one-vs-rest multiclass ROC-AUC and PR-AUC;
- precision, recall, F1, and support for every class;
- detection rate for each attack family;
- confusion matrix;
- warmed prediction time and milliseconds per record;
- model parameters, library versions, split digests, and preprocessing metadata.

Prediction timing excludes model loading, preprocessing, and probability scoring.
It varies by hardware and should not be compared across machines without a
controlled benchmark protocol.

## Reproduce locally

```bash
PYTHONPATH=src python -m cids.experiments.train_supervised \
  --data-dir dataset/unsw-nb15/raw \
  --task binary \
  --output-dir artifacts/v2/binary

PYTHONPATH=src python -m cids.experiments.train_supervised \
  --data-dir dataset/unsw-nb15/raw \
  --task multiclass \
  --output-dir artifacts/v2/multiclass
```

## Current validation snapshot

This snapshot used frozen configuration `unsw-nb15-experiment-v1` with canonical
SHA-256 `070c009c139f41bcf34d63c7a5fa1324c819ded7a5884b800cc1bdbfb34234d2`,
the pinned files, split policy `unsw-nb15-split-v1`, preprocessor
`unsw-nb15-preprocessor-v1`, validation fraction `0.20`, and seed `42`.

| Task | Model | Balanced accuracy | Macro F1 | Weighted F1 | ROC-AUC | PR-AUC |
|---|---|---:|---:|---:|---:|---:|
| Binary | Random Forest | 0.9289 | 0.9280 | 0.9280 | 0.9851 | 0.9836 |
| Binary | Histogram Gradient Boosting | 0.9320 | 0.9314 | 0.9314 | 0.9854 | 0.9837 |
| Multiclass | Random Forest | 0.7208 | 0.7282 | 0.8737 | 0.9864 | 0.7813 |
| Multiclass | Histogram Gradient Boosting | 0.8148 | 0.7488 | 0.8652 | 0.9868 | 0.8057 |

Multiclass ROC-AUC and PR-AUC are macro one-vs-rest values. Histogram Gradient
Boosting currently has the stronger macro F1 and minority-family recall, while
Random Forest has slightly higher multiclass accuracy and weighted F1. This
difference illustrates why intrusion-detection comparisons must not be reduced
to accuracy alone.

## Remaining work before final evaluation

- Reproduce the frozen validation results from a clean environment.
- Evaluate the selected frozen models once on the official test partition.
- Document final results, limitations, and error analysis.
