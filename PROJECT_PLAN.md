# Project Plan and State

This file is the durable source of truth for the Cyber Intrusion Detection
System project. Read it before starting work and update it whenever a task,
decision, milestone, or scope changes.

## Project direction

Rebuild the original college project in controlled releases into an explainable,
analyst-oriented network intrusion detection research platform. Preserve the
project's history without presenting the KDD Cup 1999 baseline as production-ready
or representative of modern traffic.

## Working rules

1. Complete and verify one release before expanding the next release.
2. Keep preprocessing, training, evaluation, and inference reproducible.
3. Fit every learned transformation on training data only.
4. Keep test data held out from preprocessing, feature selection, and tuning.
5. Report security-relevant metrics; do not use accuracy as the sole result.
6. Prefer a small, explainable architecture over unnecessary infrastructure.
7. Do not commit datasets, generated models, secrets, or local environments.
8. Preserve authorship as `Arunachaleswaran M S <arunachaleswaranms@gmail.com>`.
9. Do not add AI tools as authors, committers, or co-authors.
10. Update this file in the same change that completes or changes planned work.
11. Do not rerun the completed v2.0 official test or tune v2.0 from its results.
    Any new modeling study requires a new versioned experiment and evaluation
    policy.

## Current state

| Item | State |
|---|---|
| Active release | v2.1 planning |
| Release status | v2.0 published as tag and GitHub Release `v2.0.0` |
| v1.1 implementation commit | `516ca7099ef3fa5f1629e1ad8829573c5300a403` |
| v2.0 release commit | `39a6a6f5e24164573913dbed6fd3e382b93fb769` |
| Baseline dataset | KDD Cup 1999 (historical baseline only) |
| v1.1 baseline models | Random Forest and Gradient Boosting |
| Automated tests | Passing locally and in GitHub Actions |
| v2.0 primary dataset | UNSW-NB15 |
| Dataset integrity | Official partitions pinned by SHA-256 manifest |
| Split policy | Deterministic, target-aware, duplicate-safe v1 |
| Preprocessing | Versioned train-only pipeline with provenance metadata |
| v2.0 supervised models | Random Forest and Histogram Gradient Boosting validated |
| v2.0 anomaly model | Normal-only Isolation Forest validated; reference baseline only |
| Frozen experiment | `unsw-nb15-experiment-v1` |
| Selected binary model | Histogram Gradient Boosting |
| Selected multiclass model | Histogram Gradient Boosting |
| Final evaluation protocol | Implemented as `unsw-nb15-final-evaluation-v1` |
| Reproduction environment | Python 3.12 with exact dependencies in `requirements-reproduction.txt` |
| Mac reproduction | Passed dataset, split, tests, winners, ranking, and bounded metric checks |
| Official test state | Evaluated once on 2026-09-12; results frozen and preserved |
| Binary official-test result | Macro F1 0.8663; balanced accuracy 0.8595; FPR 0.2689 |
| Multiclass official-test result | Macro F1 0.5029; balanced accuracy 0.5761 |
| Next milestone | Define the v2.1 dashboard and explainability contract before implementation |

## Release roadmap

### v1.1 — Repair the original baseline

Status: **Published as `v1.1.0`**

- [x] Remove train/test preprocessing leakage.
- [x] Load original headerless KDD Cup gzip files correctly.
- [x] Handle unseen categorical values in held-out data.
- [x] Save preprocessing and classifier together as a model pipeline.
- [x] Make model randomness deterministic.
- [x] Add accuracy, precision, recall, F1, and confusion-matrix output.
- [x] Add unit tests and GitHub Actions.
- [x] Correct README commands, claims, limitations, and dataset instructions.
- [x] Remove duplicate code and invalid placeholder files.
- [x] Push the completed commits to GitHub.
- [x] Confirm the GitHub Actions test workflow passes on `main`.
- [x] Create the `v1.1.0` tag after CI passes.

Exit criteria: clean setup on Python 3.10+, tests pass in GitHub Actions, training
and evaluation commands work with the documented source datasets, and no dataset
or generated model is committed.

### v2.0 — Modern ML baseline

Status: **Published as `v2.0.0`**

- [x] Write [a dataset decision record](docs/decisions/0001-v2-primary-dataset.md)
      comparing UNSW-NB15 and CICIDS2017.
- [x] Select one primary modern dataset; do not add both initially.
- [x] Define a stable attack-family taxonomy and normal/attack mapping.
- [x] Add a dataset manifest and local-file integrity validation.
- [x] Add deterministic train/validation/test splits with duplicate safeguards.
- [x] Build a versioned preprocessing and feature-schema pipeline.
- [x] Compare a small model set:
  - [x] Random Forest and Histogram Gradient Boosting supervised baselines.
  - [x] One normal-only Isolation Forest anomaly-detection baseline.
- [x] Add precision, recall, macro/weighted F1, false-positive rate,
      false-negative rate, PR-AUC, ROC-AUC where applicable, per-family detection
      rate, and inference latency for supervised models.
- [x] Add configuration files for experiments and persist result metadata.
- [x] Add tests covering schema validation, leakage prevention, label mapping,
      serialization, and deterministic outputs.
- [x] Pin and test a guarded one-time official-test protocol.
- [x] Run the clean validation reproduction on Arun's Apple Silicon Mac.
- [x] Run the official-test evaluation once.
- [x] Preserve the exact result and completion evidence with SHA-256 checks.
- [x] Document reproducible benchmark results, error analysis, and limitations.

Exit criteria: another person can download the selected dataset, reproduce the
reported experiment, and obtain comparable metrics without modifying source code.

### v2.1 — Analyst dashboard and explainability

Status: **Planning**

- [ ] Add a Streamlit dashboard for dataset or flow-file analysis.
- [ ] Show alert timeline, attack family, confidence, and severity.
- [ ] Add global and per-detection SHAP explanations.
- [ ] Add false-positive review and threshold-tuning views.
- [ ] Clearly distinguish model confidence from operational risk severity.
- [ ] Add safe sample data for demonstrations.
- [ ] Package the application with Docker and document local startup.

Exit criteria: a reviewer can run the dashboard locally, analyze safe sample
data, understand why detections occurred, and inspect false positives.

### v3.0 — PCAP-to-alert research workflow

Status: **Future; requires design review**

- [ ] Evaluate a maintained flow extractor and document its trust boundary.
- [ ] Implement PCAP to flow features to schema validation to model inference.
- [ ] Validate feature parity between training data and extracted traffic.
- [ ] Add malformed-PCAP, resource-limit, and parser-failure handling.
- [ ] Add batch alert export in JSON or CSV.
- [ ] Measure throughput, latency, memory use, and detection limitations.

Exit criteria: supplied PCAP samples can be converted into compatible flows and
alerts reproducibly, with documented safety controls and known limitations.

## Explicitly out of scope for now

- Live traffic blocking or automated response.
- Production deployment claims.
- Kafka, Kubernetes, Elasticsearch, or a microservice split without measured need.
- Large collections of overlapping ML or deep-learning models.
- LLM-generated detection decisions.
- Training on private or sensitive network captures.

## Decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-09-05 | Preserve the existing repository instead of replacing its history. | The college-project-to-professional-rebuild story is valuable and honest. |
| 2026-09-05 | Repair KDD Cup 1999 only as the v1.1 historical baseline. | It provides continuity but is too old for modern performance claims. |
| 2026-09-05 | Fit preprocessing on training data only. | Prevents evaluation leakage. |
| 2026-09-05 | Save complete sklearn pipelines. | Keeps training and inference transformations consistent. |
| 2026-09-05 | Defer dashboard and PCAP ingestion until the modern baseline is sound. | Avoids building presentation layers on an unreliable model foundation. |
| 2026-09-05 | Select UNSW-NB15 as the only v2.0 primary dataset. | Its official prepared partitions and nine attack families provide a controlled path to a reproducible modern baseline; see ADR 0001. |
| 2026-09-05 | Version the prepared UNSW-NB15 schema and fail closed on schema or label inconsistencies. | Prevents silent feature drift and makes binary and multiclass experiments comparable. |
| 2026-09-05 | Pin the official prepared partitions by filename, size, row count, schema, and SHA-256. | Prevents mislabeled mirrors, incomplete downloads, and silent dataset substitution. |
| 2026-09-05 | Keep the official test partition immutable and remove overlaps, target conflicts, and duplicate features only from training before deterministic validation splitting. | Prevents equivalent observations crossing evaluation boundaries while preserving the published holdout. |
| 2026-09-05 | Preserve numerical units and fit one-hot categorical vocabularies only on the prepared training split. | Matches the planned tree models, improves explanation readability, and prevents category leakage. |
| 2026-09-05 | Use Random Forest and scikit-learn Histogram Gradient Boosting for the first supervised comparison. | Provides bagged and boosted tree baselines without adding a native external dependency; XGBoost or LightGBM can be reconsidered only if controlled validation justifies it. |
| 2026-09-05 | Select supervised models only from validation metrics and keep the official test sealed until configuration is frozen. | Prevents test-driven model choice and preserves an honest final holdout. |
| 2026-09-05 | Train Isolation Forest and its preprocessor only on normal training rows, using the 95th percentile of normal-training anomaly scores as a fixed threshold. | Creates a label-free attack reference without learning attack categories or tuning the threshold on validation labels. |
| 2026-09-05 | Rank candidates by macro F1, then balanced accuracy, then false-positive rate. | Prioritizes performance across minority attack families instead of allowing common classes to dominate selection. |
| 2026-09-05 | Select Histogram Gradient Boosting for both final supervised tasks. | It ranks first under the frozen validation-only rule; the official test was not used. |
| 2026-09-12 | Refit each selected model on cleaned train plus validation data, then evaluate both tasks in one recorded official-test run. | Uses all development data after selection while preventing further model choice based on test performance. |
| 2026-09-12 | Require a matching clean validation reproduction, explicit confirmation phrase, and new output directory before final evaluation. | Reduces accidental test access and makes the final benchmark auditable. |
| 2026-09-12 | Pin the final benchmark to Python 3.12 and an exact dependency lock, while permitting at most `0.005` absolute selected-metric variation across platforms. | The Apple Silicon rerun matched the pinned dataset, documented row counts, winners, and rankings; recorded deterministic split fingerprints; and had a largest metric difference of `0.003841`. Exact floating-point equality was not portable. This amendment was made while the official test remained sealed. |
| 2026-09-12 | Freeze the single official-test run without test-driven retuning. | Binary macro F1 was `0.8663` with a `0.2689` false-positive rate; multiclass macro F1 was `0.5029`, exposing weak minority-family generalization. Honest held-out results and limitations provide more research and portfolio value than optimizing against the test partition. |
| 2026-09-12 | Publish v2.0 as annotated tag and GitHub Release `v2.0.0`. | Freezes the reproducible UNSW-NB15 baseline and creates a clear boundary before any dashboard, explainability, or later model experiment. |

## Handoff checklist for any AI or contributor

Before making changes:

1. Read `README.md` and this entire file.
2. Run `git status --short --branch` and preserve unrelated changes.
3. Confirm the active milestone and choose only unchecked tasks within it.
4. Run the existing test suite before editing.
5. Do not silently change datasets, labels, metrics, or release scope.

Before finishing:

1. Add or update tests for changed behavior.
2. Run `pytest -q`, command-line smoke tests, and `git diff --check`.
3. Update checklist status and add any durable decision to the decision log.
4. Keep commits focused and use only Arun's configured git identity.
5. Record unresolved blockers under the current milestone.

## Next session

1. Define v2.1 user journeys, input/output contracts, and acceptance criteria.
2. Decide how the dashboard obtains trusted local models without committing or
   automatically loading unsafe pickle artifacts.
3. Design explainability and false-positive analysis around the frozen v2.0
   limitations without retraining from its official-test results.
