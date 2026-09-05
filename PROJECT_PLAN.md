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

## Current state

| Item | State |
|---|---|
| Active release | v2.0 |
| Release status | v1.1 published on `main`; v2.0 design in progress |
| v1.1 implementation commit | `516ca7099ef3fa5f1629e1ad8829573c5300a403` |
| Baseline dataset | KDD Cup 1999 (historical baseline only) |
| Baseline models | Random Forest and Gradient Boosting |
| Automated tests | Passing locally and in GitHub Actions |
| v2.0 primary dataset | UNSW-NB15 |
| Next milestone | Define and test the v2.0 feature and label schema |

## Release roadmap

### v1.1 — Repair the original baseline

Status: **Published; release tag pending**

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
- [ ] Create the `v1.1.0` tag after CI passes.

Exit criteria: clean setup on Python 3.10+, tests pass in GitHub Actions, training
and evaluation commands work with the documented source datasets, and no dataset
or generated model is committed.

### v2.0 — Modern ML baseline

Status: **In progress**

- [x] Write [a dataset decision record](docs/decisions/0001-v2-primary-dataset.md)
      comparing UNSW-NB15 and CICIDS2017.
- [x] Select one primary modern dataset; do not add both initially.
- [ ] Define a stable attack-family taxonomy and normal/attack mapping.
- [ ] Add deterministic train/validation/test splits with duplicate safeguards.
- [ ] Build a versioned preprocessing and feature-schema pipeline.
- [ ] Compare a small model set: Random Forest, XGBoost or LightGBM, and one
      anomaly-detection baseline.
- [ ] Add precision, recall, macro/weighted F1, false-positive rate,
      false-negative rate, PR-AUC, ROC-AUC where applicable, per-family detection
      rate, and inference latency.
- [ ] Add configuration files for experiments and persist result metadata.
- [ ] Add tests covering schema validation, leakage prevention, label mapping,
      serialization, and deterministic outputs.
- [ ] Document reproducible benchmark results and limitations.

Exit criteria: another person can download the selected dataset, reproduce the
reported experiment, and obtain comparable metrics without modifying source code.

### v2.1 — Analyst dashboard and explainability

Status: **Planned after v2.0**

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

1. Create the `v1.1.0` tag when release housekeeping is performed.
2. Define the canonical UNSW-NB15 feature schema and attack-family mapping.
3. Add a dataset manifest and local-file validation without distributing data.
4. Design deterministic train/validation/test handling with duplicate safeguards.
5. Review those contracts before implementing v2.0 model training.
