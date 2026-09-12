# v2.0 validation-only model selection

Configuration: `unsw-nb15-experiment-v1`

Canonical configuration SHA-256:
`070c009c139f41bcf34d63c7a5fa1324c819ded7a5884b800cc1bdbfb34234d2`

Recorded selection: `unsw-nb15-model-selection-v1`

## Frozen rule

Models are ranked separately for binary and multiclass tasks using validation
results only:

1. Maximize macro F1.
2. If tied, maximize balanced accuracy.
3. If still tied, minimize FPR for binary or macro one-vs-rest FPR for
   multiclass.

Macro F1 is primary because every attack family should influence model choice;
weighted metrics can be dominated by common classes.

## Result

| Task | Selected model | Validation macro F1 | Balanced accuracy |
|---|---|---:|---:|
| Binary | Histogram Gradient Boosting | 0.9314 | 0.9320 |
| Multiclass | Histogram Gradient Boosting | 0.7488 | 0.8148 |

Binary candidate order:

1. Histogram Gradient Boosting
2. Random Forest
3. Isolation Forest

Multiclass candidate order:

1. Histogram Gradient Boosting
2. Random Forest

The machine-readable record is
[`configs/v2-model-selection-v1.json`](../configs/v2-model-selection-v1.json).
It is validated against the exact experiment configuration digest. Changing the
configuration, winner, candidate order, ranking rule, or official-test state
causes validation to fail.

## Official-test state

The official test partition is still sealed. Selection does not contain official
test metrics. A separate one-time final evaluation may occur only after the
selection record is committed and a clean reproduction check passes.
