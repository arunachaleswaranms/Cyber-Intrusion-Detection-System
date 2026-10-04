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
| Active release | v2.1 release closure; Phases 1–5 implemented and merged |
| Release status | v2.0 published as `v2.0.0`; v2.1.0 notes finalized, tag and GitHub Release publication pending |
| v1.1 implementation commit | `516ca7099ef3fa5f1629e1ad8829573c5300a403` |
| v2.0 release commit | `39a6a6f5e24164573913dbed6fd3e382b93fb769` |
| Baseline dataset | KDD Cup 1999 (historical baseline only) |
| v1.1 baseline models | Random Forest and Gradient Boosting |
| Automated tests | Phase 5 independent local verification: 606 passed / 8 skipped; dependency consistency passed; no blocking code/documentation findings. All five post-merge jobs passed at `665a3efeb77e10ab5d55adcb8d8d7e6b499d951b` in [run 37198188962](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/actions/runs/37198188962). Exact scope: docs/release-readiness-v2.1.md |
| Phase 3B local verification | Base 247 passed, 34 skipped (30 pinned-runtime tests, 2 SHAP and 2 Streamlit); reproduction 277 passed, 4 skipped (2 SHAP and 2 Streamlit); workbench 286 passed, 2 skipped (Streamlit); dashboard 322 passed. The ignored real pack passed 16 checksum-verified training rows. Dashboard `pip check`, all four environment dependency checks, and `git diff --check` passed |
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
| v2.1 dashboard | Phase 2 evidence mode merged to `main` by PR #1 at `9d72ad1`; see `docs/dashboard.md`. Streamlit server health check passed with the server bound to `127.0.0.1` |
| Dashboard environment | Python 3.12.14 with `requirements-dashboard.txt` (Streamlit 1.64.0 over the workbench lock) |
| v2.1 model pack | Phase 3A registration and Phase 3B verified loading/inference implemented. The ignored local pack `e2d4f329…2b18` passed exact-buffer loading and bounded inference on 16 checksum-verified training-partition rows; no official-test data or metrics were accessed. Phase 3C adds an explicit opt-in bounded CSV analysis page; default evidence navigation does not load models |
| Phase 3D handoff | Merged through PR #5 at `5305f0a317164c24e81631abbc2a870498e0ac7f`; all four post-merge CI jobs passed in run `37183225010`. Historical local verification: Local matrix: base 325 passed / 59 skipped; reproduction 378 / 6; workbench 387 / 4; dashboard 464 / 0. Focused 188 / 0; four dependency checks passed |
| Phase 3C handoff | Merged through PR #4 at `9d81a3c4136f7062aca3c238c0d041e722dd1330`; independent review had no blocking findings; all four post-merge CI jobs passed |
| Phase 4 handoff | Merged through PR #6 at `ce7f37e2a0a33894ea5c83de40bdf5d065b7f947`; independent review had no blocking findings. Original explanation/global integration and populated-view browser QA were outstanding at handoff |
| Phase 5 handoff | Implemented and merged through [PR #7](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/pull/7) at `665a3efeb77e10ab5d55adcb8d8d7e6b499d951b`; independent review found no blocking issues; all five post-merge CI jobs passed. Implementation accepted within documented verification scope; no formal GitHub approval submitted; release unpublished |
| Next milestone | Review and merge the v2.1.0 closure PR, then separately authorize annotated tag and GitHub Release publication using docs/release-handoff-v2.1.0.md; no v3.0 or image publication |

## Phase 3C implementation and verification (2026-10-04)

- Evidence remains the default. The separate Local CSV analysis page binds one
  CLI-registered pack via `CIDS_MODEL_PACK_ID` under the app-controlled root.
  Page preflight does not deserialize; each explicit Analyze CSV action uses
  the hardened Phase 3B loader and independent inference services anew.
- One UTF-8 uncompressed CSV is bounded to 10 MiB / 50,000 rows. Required and
  optional columns use the existing policy and parser. Strict body quoting and
  field counts are checked, and supplied IDs retain leading zeros.
- Session-only results bind the input digest and pack ID. Replacement, removal,
  invalid replacement/pack, configuration changes, failure and explicit clear
  invalidate prior results and selections; clear resets the uploader too.
  Built-in table downloads and clipboard copy are disabled and guarded.
  Application data is not persisted/logged/cached globally. Clearing references
  does not claim secure memory erasure.
- Per-model out-of-vocabulary counts precede scoring, without changing the
  fitted encoder's ignore behavior. The paged research queue shows independent
  outputs, uncalibrated scores, fixed bands and broader disagreements, with
  stable sequence/score/UTC order and one bounded, aligned record detail.
- Labels are validated only; explanation status stays not_requested. No Phase
  3D/4/5 feature, frozen evidence, experiment, model selection or official-test
  record was changed or used for new scoring.

Implementer-reported local verification: **base 272 passed / 58 skipped; reproduction 325 / 5;
workbench 334 / 3; dashboard 394 / 0**. Focused tests: 118 passed / 0 skipped.
All four existing environments used Python 3.12.14 and passed pip check.
Exact skip reasons are in [dashboard verification](docs/dashboard.md). The
original registered pack passed direct/UI record equality on exactly 16 rows
from the size/SHA-256-verified training copy in `/private/tmp`; no official-test
raw data was accessed. Loopback server health passed. AppTest covered analysis
interactions; new-page browser visual QA remains unperformed.

Phase 3C was pushed and independently reviewed at
`b60a703b52a24ebef3e3903b51408d1151968baa`: **no blocking findings**;
independent tests **391 passed / 3 skipped**, and the dependency check passed.
All four GitHub CI jobs (`test`, `reproduction-environment`, `workbench-phase-1`,
`dashboard-phase-2`) passed on that commit. The independent reviewer could not
repeat the original-model integration checks requiring ignored local artifacts;
the implementer's original-pack verification above is separately reported.
Phase 3C merged through PR #4 at `9d81a3c4136f7062aca3c238c0d041e722dd1330`.
All four post-merge jobs passed in [CI run 37180576999](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/actions/runs/37180576999).

## Phase 3D implementation (2026-10-04)

Branch: `cids-v2.1-phase3d-review-export`, based on current `origin/main`
`9d81a3c4136f7062aca3c238c0d041e722dd1330`. Subsequently merged through PR #5
at `5305f0a317164c24e81631abbc2a870498e0ac7f`. All four post-merge CI jobs passed
in [run 37183225010](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/actions/runs/37183225010). Historical implementation details follow.

- Framework-independent `review.py` uses uploaded `label` for TP/TN/FP/FN
  and explicit-denominator sample metrics. Uploaded `attack_cat` independently
  compares to `family_prediction_raw`, never binary-gated triage. No truth is
  inferred. Missing-class/zero-denominator rates are unavailable with reasons.
- Ephemeral, sample-specific threshold simulation uses existing scores on the
  full current upload. The pinned estimator uses raw logit > 0 (normal on ties);
  the score-domain baseline is 0.50 with strict `>` and normal on equality.
  Stored-score rounding can differ from raw decisions near the boundary.
  Original predictions, review categories and frozen 0.90 queue bands remain
  unchanged. No official-test rows/evidence are used for threshold selection.
- Explicit JSON-default/CSV export is prepared only in session memory. The
  documented allowlist omits raw features, paths and artifacts; includes digest,
  pack ID, provenance, scope, stable IDs and research notices. Filtered scope
  covers all matching pages in deterministic review order. Undefined metrics
  serialize as null. CSV prefixes formula initiators behind whitespace/control
  characters while preserving numeric types and applying proper quoting.
- Analysis lifecycle clears simulation and prepared downloads, including explicit
  reanalysis, failed replacements, removal, clear, failures and pack changes.
  Scope/format/filter/simulation changes invalidate affected prepared exports.
  Built-in dataframe download/copy remains disabled; explanations remain
  `not_requested`. Clearing references is not secure memory erasure.
- No new dependency, retraining, calibration, frozen-file change, official-test
  evaluation, SHAP implementation, demonstration, Docker or release work.
  Verification and exact environment counts are in [dashboard.md](docs/dashboard.md).

## Phase 4 implementation (2026-10-04)

Branch: `cids-v2.1-phase4-explainability-demo`, based on current `origin/main`
`5305f0a317164c24e81631abbc2a870498e0ac7f`, including Phase 3D PR #5. Implemented
and independently reviewed with no blocking findings (588 passed / 4 skipped;
dependency check passed). Merged through PR #6 at `ce7f37e`; all four post-merge
jobs passed in run `37191000174`. Historical implementation evidence follows. [Setup/contracts](docs/explanation-resources.md) and
[verification](docs/dashboard.md) describe the evidence and limitations.

- Reused the accepted SHAP 0.52.0 permutation method and source mapping. Explicit
  one-record task actions explain raw binary attack output (also for normal
  predictions) or the independent raw predicted family. All class dimensions and
  finite values, reconstruction (`1e-5`) and full source conservation (`1e-10`)
  validate before exposing all 42 signed contributions/baseline/output/class.
- CLI-only deterministic frozen prepared-training backgrounds, private feature-only
  CSVs and versioned manifest bound to hashes, pack/artifact/runtime, schema, policy,
  seed, training/split provenance and sampling. Verified prepared partitions are
  preferred and matched to verified training source rows; only explicit feature-only
  official-test overlap removal can reconstruct them. No test IDs/targets parsed,
  no test foreground prediction/explanation/scoring/tuning or changed frozen evidence.
- Fresh dedicated Python subprocess worker per action, ≤32 service rows, ≤256 background rows, bounded
  JSON IPC and actual 60-second cancellation/reaping (including stalled IPC).
  Input/pack/resource/background/policy/task/class/record binding and session
  lifecycle/selection clearing. Missing or failed explanations leave existing
  analysis/review/simulation/export usable. No application data persistence/logging
  or global model/upload/explanation caches.
- Separate explicit offline global source-feature permutation reliance on ≤256
  prepared-validation rows, macro F1 over all estimator classes, zero_division=0,
  3 repeats and seed 42. In-development reliance because final models were refit
  on train plus validation; distinct from frozen benchmarks and local SHAP. No
  uploaded-SHAP aggregation; default evidence pages import/load neither SHAP nor
  runtime resources.
- Committed eight deterministic arithmetic feature rows: synthetic, non-sensitive,
  non-realistic, no official copies, labels, hosts, IPs or timestamps. Clean-clone
  explicit preview/download; trusted models/resources still required for analysis/
  explanations. No demonstration model builder or broadened provenance acceptance.
- Preserved Phase 3D export schema/allowlist and original snapshot; new attributions
  and observed features remain omitted. Strict upload/explicit analysis/session/
  stale-state/safe-export/loopback/telemetry controls retained. No retraining,
  calibration, official-test run, gate rerun, Docker, release or Phase 5 work.

Phase 4 verification: **base 439 passed / 65 skipped; reproduction 494 / 10;
workbench 505 / 6; dashboard 591 / 1**. New focused suite: **127 passed / 1 skipped**.
All four Python 3.12.14 environments passed dependency checks; `git diff --check`
passed. Exact skips and test-environment thread limits are in [dashboard verification](docs/dashboard.md).
Original-pack inference regressions used 16 checksum-verified training rows; the
original pack additionally analyzed the eight committed synthetic rows. Original
explanation/global-resource integration remains unperformed because compatible
verified prepared partitions/backgrounds are absent. Representative synthetic
workers and real AppTest actions passed with test-only anchors. Chrome inspected
the synthetic preview and unavailable states; populated attribution/global views
were tested with AppTest but not visually inspected in a browser. No original
official-test raw file was accessed or rescored and no frozen config/evidence/gate,
model-pack acceptance rule or export allowlist changed.

## Phase 5 packaging implementation (2026-10-04)

Historical implementation branch `cids-v2.1-phase5-packaging-release` started at then-current `origin/main`
`ce7f37e2a0a33894ea5c83de40bdf5d065b7f947` (Phase 4 PR #6 included).
Phase 4 independent review: 588 passed / 4 skipped, dependency check passed, no
blocking findings. All four post-merge jobs passed in run `37191000174`.

- Verified/pinned Python 3.12.14 official multi-platform image index; exact
  existing dashboard/workbench/reproduction locks preserved. A separate Linux
  overlay pins watchdog 6.0.0. Explicit file allowlist excludes private data,
  artifacts, environments, secrets, uploads, exports and Git from build context.
- Non-root image and standard-library bounded health probe; explicit Docker-only
  launch profile permits internal 0.0.0.0 without weakening ordinary host
  loopback/telemetry guards. Host publication is operator-controlled 127.0.0.1.
- Three documented modes with read-only private digest-directory mounts, owner
  UID permissions, read-only filesystem, bounded ephemeral tmpfs, capabilities
  dropped, no-new-privileges, init, CPU/memory/PID bounds and graceful stop.
  No registration/preparation during build/startup or browser actions.
- Existing four CI jobs preserved; new packaging job audits actual context,
  builds, checks exact runtime/dependencies/permissions, exercises restricted
  synthetic workers/review/simulation/export and validates startup/stop/networking.
- Original development resources prepared only by approved host CLI feature-only
  overlap reconstruction (prepared CSV partitions absent); both original worker
  tasks passed on committed synthetic foreground on Mac and native arm64 Docker.
  Both separate global reliance bundles validated. No official-test foreground
  scoring/explaining/tuning, gate rerun, retraining or acceptance broadening.
- [Acceptance evidence](docs/release-readiness-v2.1.md) maps all design criteria;
  [container operations](docs/container.md) has exact commands; release notes are
  finalized/unpublished. Independent review and merge are recorded below.

Local full matrix: **base 453 passed / 73 skipped; reproduction 508 / 18;
workbench 520 / 13; dashboard 614 / 0**. Native Linux arm64 container workbench/
dashboard suite: **537 / 5**; separate original synthetic explanation integration
**1 / 0**; profile/permission focus **22 / 0**. Four host dependency checks, image
checks, context audit, healthy loopback publication, read-only operation, graceful
shutdown and diff checks passed. Exact skip/platform/browser scope and remaining
review scope is in the acceptance document. All five implementation-head jobs
passed in [run 37193157065](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/actions/runs/37193157065);
native Linux amd64 container qualification passed 537 / 5. Browser inspected
populated original explanation/global/export views, container analysis/explanations,
the missing-resource view and a test-only deadline-failure state with export still
usable. Historical final-head CI passed in run `37193546153` and PR CI in
run `37193785168`; [PR #7](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/pull/7) records both links. Frozen results/configs/gate
hashes and all existing model/runtime acceptance rules remain unchanged.

## Phase 5 independent acceptance and release closure (2026-10-04)

Phases 1–5 are implemented and merged. Independent Phase 5 code/documentation
review found **no blocking issues**; local verification recorded **606 passed /
8 skipped** and dependency consistency passed. Docker was unavailable to that
reviewer. Container verification used CI logs: **537 passed / 5 skipped**, context
exclusion, runtime/dependency, non-root/read-only, loopback, health and shutdown
checks. Original-model and browser checks were reviewed from implementer evidence,
not independently repeated. No formal GitHub approval was submitted.

Phase 5 merged through PR #7 at `665a3efeb77e10ab5d55adcb8d8d7e6b499d951b`. All five
post-merge jobs passed in [run 37198188962](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/actions/runs/37198188962). Closure started
from this current `origin/main`; no intervening main changes existed. No `v2.1.0`
tag or GitHub Release existed at the closure check. Implementation acceptance
within [documented scope](docs/release-readiness-v2.1.md) is complete; release
publication remains pending. [Final notes](docs/release-notes-v2.1.0.md) and
[maintainer handoff](docs/release-handoff-v2.1.0.md) prepare that separate action.
Frozen evidence, model/runtime acceptance and dependency locks are preserved.

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

Status: **Phases 1–5 implemented and merged; independent Phase 5 review found no blocking issues; v2.1.0 publication pending**

The approved architecture, user journeys, contracts, security controls, phases,
and acceptance criteria are in [`docs/v2.1-design.md`](docs/v2.1-design.md) and
[ADR 0002](docs/decisions/0002-v2.1-analyst-workbench.md).

- [x] Define the product boundary and evidence-first reviewer journey.
- [x] Define feature CSV, prediction, alert, and model-pack contracts.
- [x] Define model-loading trust boundaries and a dashboard threat model.
- [x] Define score, false-positive, timestamp, and explanation terminology.
- [x] Define phased implementation and release acceptance criteria.
- [x] Phase 1: implement framework-independent input and evidence contracts.
- [x] Phase 1: implement trusted-model-pack schema and preflight.
- [x] Phase 1: pass representative binary and multiclass SHAP integration tests.
- [x] Phase 1: complete the pinned SHAP compatibility/correctness/performance spike.
- [x] Phase 2: implement the evidence-first Streamlit pages.
- [x] Phase 2 state cleanup: record the merge, CI results, and next milestone.
- Phase 3: trusted local inference, review, and safe export, in four steps:
  - [x] Phase 3A: trusted final-model-pack registration and preflight.
  - [x] Phase 3B: verified deserialization and framework-independent inference.
  - [x] Phase 3C: bounded CSV analysis UI and review queue (merged by PR #4 at `9d81a3c`; post-merge CI passed).
  - [x] Phase 3D: label-backed review, ephemeral threshold simulation, and safe export (merged by PR #5 at `5305f0a`; post-merge CI passed).
- [x] Phase 4: bounded explanations and synthetic sample (PR #6 merged; review and post-merge CI passed).
- [x] Phase 5: non-root Docker packaging, health checks, local read-only workflow,
      container verification and release acceptance documentation (PR #7 merged).
- [x] Complete implementation acceptance and independent review within documented scope.
- [ ] Review and merge release closure documentation.
- [ ] Separately authorize and publish the annotated v2.1.0 tag and GitHub Release.

Exit criteria: a reviewer can run the dashboard locally, analyze safe sample
data, inspect features that influenced each model output, and review measured false positives.

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
| 2026-09-12 | Build v2.1 as an evidence-first local analyst workbench with a separate opt-in trusted inference mode. | Gives reviewers value from a clean clone while preventing model uploads and keeping executable local artifacts outside the default path; see ADR 0002. |
| 2026-09-12 | Use `model score (uncalibrated)`, review queue bands, and record sequence unless real timestamps are supplied. | v2.0 did not establish calibration or operational risk, and the prepared schema has no event timestamp or network identity fields. |
| 2026-09-12 | Put SHAP behind a pinned technical gate and keep official-test data out of explanation backgrounds and threshold experiments. | Avoids claiming unsupported explanations and preserves the frozen v2.0 test boundary. |
| 2026-09-12 | Pin the Phase 1 explanation gate to SHAP `0.52.0`, raw model output, a deterministic 256-row development background, ten explained rows, and explicit correctness/resource bounds. | Representative binary and multiclass HGB checks pass on Python 3.12; approval remains pending against the original local selected artifacts. |
| 2026-09-12 | Reject interventional TreeExplainer for the selected binary artifact and propose bounded model-agnostic PermutationExplainer in ADR 0003. | The real artifact produced an additivity gap of about `0.228350`; the fallback preserves the independent `1e-5` correctness check and remains pending on both selected artifacts. |
| 2026-09-23 | Accept bounded PermutationExplainer and close v2.1 Phase 1. | Both selected artifacts passed gate v2 in under 4.3 seconds with maximum additivity error `6.22e-14`; the report confirms the official test was not evaluated or used as explanation data. |
| 2026-09-24 | Build Phase 2 as a read-only evidence catalog plus thin Streamlit pages in `src/cids/dashboard`, with `dashboard/app.py` as the entry point. | Keeps every Streamlit import in one package and every evidence rule in tested, framework-independent services; pages stay importable for `AppTest`. |
| 2026-09-24 | Bind every displayed configuration to the official run by canonical digest and re-verify all evidence on each page view instead of caching it. | Makes each number traceable to a committed file and JSON pointer; verification costs about 7 ms, so stale or edited files cannot hide behind a cache. |
| 2026-09-24 | Compare validation and official-test metrics using the committed frozen selection record, labelled with its stage and the refit caveat. | The Apple Silicon reproduction record quoted in the results document is not committed and cannot be verified by a clean clone; the protocol already bounded the two records to ±0.005. |
| 2026-09-24 | Show explanation-gate status and meaning, but no feature importance, in Phase 2. | The committed gate report contains diagnostics only; ten development rows cannot support a global ranking, and attribution views belong to Phase 4. |
| 2026-09-24 | Add a separate pinned dashboard lock and a loopback-only, telemetry-free Streamlit configuration, re-checked at startup. | Adds Streamlit without changing workbench or reproduction pins. Streamlit reads its config only from the working directory, so the app refuses to render when bound beyond loopback or with telemetry enabled. |
| 2026-10-01 | Split Phase 3 into 3A registration, 3B verified loading and inference, 3C CSV analysis UI, and 3D label-backed review and export. | Isolates the riskiest step, accepting executable local artifacts, so it can be verified before any code deserializes or presents model output. |
| 2026-10-01 | Register `maintainer_final_v2` packs only through a CLI that requires an exact confirmation phrase and source digests equal to the selected-artifact digests in the checksum-verified gate evidence. | The gate already examined these exact artifacts. Reading the digests through the verified loader avoids a second copy of them. The browser can never register, select, upload, or trust a model. |
| 2026-10-01 | Never deserialize during registration; copy under app-owned names into a private staging directory, then claim `<model_pack_id>` with an exclusive `mkdir` and rename onto it only after the manifest and preflight pass. | A hash does not make a pickle safe. Fixed names and an exclusive claim prevent path injection and overwrites. Cleanup removes only the files the registrar created, followed by a non-recursive `rmdir`, so a failure cannot delete unrelated data or leave a trusted-looking pack. |
| 2026-10-01 | Keep manifest schema `cids-trusted-model-pack-v1`. Define `creation_config_sha256` as the pinned canonical digest of the versioned registration policy, and tighten preflight. | The v1 schema was sufficient. The policy digest is host-independent and binds the phrase, anchor, filenames, and limits. The tightened preflight checks the directory name against the ID, fixed filenames, UTC timestamps, the size limit, the gate anchor, and the policy digest; no pack existed under the looser checks. |
| 2026-10-01 | Leave post-deserialization validation to Phase 3B. | Phase 3A never deserializes, so it cannot validate object type, fitted state, or internal metadata; 3B must do so immediately after `joblib.load` on a preflighted pack. |
| 2026-10-02 | Accept only gate-anchored final packs for Phase 3B loading; hash bounded bytes and deserialize that same buffer. | Preflight and post-load validation bind executable local artifacts to the frozen task, schema, model, metadata, class order, and runtime. The real pack passed a bounded inference check on verified training rows without official-test access. |
| 2026-10-04 | Implement Phase 3C with one CLI pack-ID binding, explicit analysis and session-only bounded review. | Preserve evidence defaults, verified services, frozen queue policy and the Phase 3D boundary. |
| 2026-10-04 | Implement Phase 3D with independent uploaded truth, strict score-domain simulation and explicit allowlisted session-memory export. | Preserve original predictions and frozen evidence; make sample scope, undefined rates, formula safeguards and lifecycle invalidation explicit. |

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

1. Review and merge the v2.1.0 release closure PR after its final-head and PR CI pass.
2. Separately authorize tag/Release publication and follow
   `docs/release-handoff-v2.1.0.md`, resolving the actual merged main commit.
   The release remains unpublished; do not publish an image or start v3.0.
3. Optional evidence, not a Phase 3 blocker: the Apple Silicon reproduction
   selection record. Commit it only if the exact original file exists and its
   canonical digest equals the `reproduction_selection_sha256` already recorded
   by the official run (`90439d17…`). Never reconstruct or regenerate it. On
   2026-10-01 the original file was located in the maintainer's original local
   working clone and its canonical digest matched; it remains uncommitted
   because committing it would also require pinning it and deciding whether
   the dashboard should display it.
