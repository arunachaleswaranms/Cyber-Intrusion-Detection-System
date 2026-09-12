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

## Clean Apple Silicon reproduction

The validation workflow was repeated on Arun's Apple Silicon Mac on 2026-09-12
with Python 3.12.14 and the dependencies pinned in
[`requirements-reproduction.txt`](../requirements-reproduction.txt). The pinned
dataset hashes and documented prepared row counts matched, the deterministic
split fingerprints below were recorded, and the selected models and full
candidate orders matched. The fitted metrics varied slightly across platforms:

| Task | Metric | Recorded | Mac reproduction | Absolute difference |
|---|---|---:|---:|---:|
| Binary | Balanced accuracy | 0.931975 | 0.933965 | 0.001990 |
| Binary | Macro F1 | 0.931372 | 0.933331 | 0.001959 |
| Binary | False-positive rate | 0.087024 | 0.086051 | 0.000973 |
| Multiclass | Balanced accuracy | 0.814785 | 0.812202 | 0.002583 |
| Multiclass | Macro F1 | 0.748816 | 0.744975 | 0.003841 |
| Multiclass | Macro false-positive rate | 0.016678 | 0.017008 | 0.000330 |

| Partition | Binary ID SHA-256 | Multiclass ID SHA-256 |
|---|---|---|
| Train | `807a2f9ac963d83aa1365d036466c2d0f3fb4589a87dbd2176c62b83e59cd948` | `d910e2a3666cbac8d88674ab27ba00874ce5a30ef46a815bb91202fa20c21948` |
| Validation | `bbd8437f203791f47541541c90bec178184c6c6ebea5e8a90e18ee66ae8363e7` | `e29c292fec5f00f556a8e2e69f9ceb0e86620a2f2abac6d6833e9d4c6f60d8ba` |
| Official test | `e0ba957c470ff374011d87e4214e304b85b85dde050198e5b4da146c5c885039` | `e0ba957c470ff374011d87e4214e304b85b85dde050198e5b4da146c5c885039` |

Because tree fitting can vary slightly with platform-specific numerical
operations, the final protocol permits at most `0.005` absolute variation in a
selected metric. This is 0.5 percentage points on a 0-to-1 metric scale. Model
identity, candidate order, ranking rules, artifact versions, configuration,
dataset hashes, and split policy remain exact-match requirements. The tolerance
was documented before the official test was opened.

## Official-test state

The official test partition remained sealed throughout model selection, and the
selection record contains no official-test metrics. After the selection was
committed and reproduced, the separate guarded evaluation ran once on
2026-09-12. Its frozen result is documented in
[`v2-official-test-results.md`](v2-official-test-results.md).
