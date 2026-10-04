# v2.1 evidence dashboard and local analysis (Phases 2 and 3C)

Status: **Evidence mode remains the default; opt-in Phase 3C analysis implemented**

The dashboard presents the frozen v2.0 benchmark and the accepted v2.1
explanation gate. It reads committed, non-executable evidence, verifies it on
every page view, and shows where each number came from. Evidence pages do not load a
model, read raw UNSW-NB15 CSV files, make predictions, or recompute any
official result. A separate local analysis page accepts bounded feature CSVs
and calls the existing Phase 3B services only after an explicit action.

> Offline research artifact, not a production IDS. There is no authentication;
> the server listens on `127.0.0.1` only.

## Launch

Requires Python **3.12.14** for analysis; evidence mode needs Python 3.12. From the repository
root:

```bash
python3.12 -m venv .venv-dashboard
source .venv-dashboard/bin/activate
python -m pip install pip==26.2.1
python -m pip install -r requirements-dashboard.txt
streamlit run dashboard/app.py
```

Open the URL Streamlit prints (default `http://127.0.0.1:8501`). Start it from
the repository root so `.streamlit/config.toml` applies: that file disables
usage telemetry, binds to loopback, runs headless, and disables Streamlit
"magic" rendering. No dataset, model artifact, or network access is needed for evidence mode.

Streamlit only reads that file from the current directory. The app therefore
re-checks the policy at startup and **refuses to render** if the server is not
bound to loopback or telemetry is enabled. To launch from elsewhere, pass
`--server.address 127.0.0.1 --browser.gatherUsageStats false` and
`--client.disableDataExport true`.

`requirements-dashboard.txt` layers Streamlit 1.64.0 and its complete dependency
closure on top of `requirements-workbench.txt` without changing any workbench
or v2.0 reproduction pin. The lock was verified to reproduce an identical
environment (`pip freeze`) and to pass `pip check`.

## Where the numbers come from

| Evidence component | Committed file(s) | Verification | Supports |
|---|---|---|---|
| v2.0 official-test results (required) | `results/v2.0/official-test-results.json`, `run-state.json`, `SHA256SUMS` | SHA-256 pinned in code and in `SHA256SUMS`; report and run state must agree | Every official-test metric, confusion matrix, and split count |
| Frozen experiment configuration | `configs/v2-baseline-v1.json` | Canonical digest must equal `experiment_config_sha256` recorded by the official run | Ranking rule, split seed and fraction |
| Frozen model-selection record | `configs/v2-model-selection-v1.json` | Canonical digest must equal `model_selection_sha256` | Validation metrics that selected each model |
| Final evaluation protocol | `configs/v2-final-evaluation-v1.json` | Canonical digest must equal `final_protocol_sha256` | One-run guard and reproduction tolerance |
| Dataset manifest | `dataset/unsw-nb15/manifest.json` | Filenames, sizes, record counts and SHA-256 must equal the run's `dataset_files` | Dataset identity |
| v2.1 workbench policy | `configs/v2.1-workbench-v2.json` | Phase 1 schema validation | Explanation bounds and tolerances |
| v2.1 explanation-gate report | `results/v2.1/shap-gate-selected-v2.json`, `SHA256SUMS` | SHA-256 pinned; policy digest, class order, transformed width and library versions must agree with v2.0 | Explanation feasibility and correctness |

Each metric tile's help text names its evaluation stage and the exact JSON
pointer it was read from. Each result page has a "Sources" expander listing
every displayed metric with full precision. Percentages in explanatory text are
recorded rates (for example `false_positive_rate`), not values recomputed in
page code; record counts come directly from the recorded confusion matrix.

The Evidence & provenance page also runs 30 internal-consistency checks. Per
class, they derive precision, recall and F1 from the report's own confusion
matrix and compare them with the stored values. They then check accuracy,
balanced accuracy, macro and weighted averages, attack-class metrics,
one-vs-rest false-positive and false-negative rates, per-family detection rates,
split counts, and cross-task agreement. Missing report structure is shown as a
failed check. Code defects are not caught and still raise.

## Evaluation stages

Numbers are always tagged with one of three stages, and the pages never compare
them without saying so:

- **Official test**: the single guarded run; models refit on train plus
  validation and scored once on the immutable official partition.
- **Validation (model selection)**: the frozen selection record; models fit on
  the training split only and scored on the validation split.
- **Explanation gate**: correctness checks on development data only. The report
  contains no feature attributions and no official-test data.

The validation → official-test comparison uses the frozen, committed
selection record. `docs/v2-official-test-results.md` quotes the later Apple
Silicon reproduction record instead (for example binary macro F1 0.9333 rather
than 0.9314). That record's digest (`90439d17…`) is stored in the official
report, but the file itself is a local artifact that is not committed, so the
dashboard cannot verify or display it. The final protocol required the two
records to agree within ±0.005 on every selection metric before the test could
be unsealed.

## Pages

| Page | Content |
|---|---|
| Overview | Model identity, evidence health, stage legend, official-test headlines for both tasks, validation → test comparison with refit caveat, evaluation context, limitations |
| Binary detection | Headline and secondary metrics, row-normalized confusion matrix with exact counts, per-class metrics, missed attacks by family, recorded timing with caveats |
| Attack families | Headline metrics, flagged weaknesses (presentation rule shown on the page), precision/recall per class, 10×10 confusion matrix, largest misclassifications, binary detection versus family attribution |
| Explainability | What SHAP values mean and do not mean, gate result and bounds, and an explicit statement that attributions are not available in evidence mode |
| Evidence & provenance | Component health, pinned files, recorded digests, dataset identity, run timestamps, model identity, data lineage, consistency checks, verification commands |
| Local CSV analysis | Separate opt-in upload, explicit analysis, independent outputs, bounded queue filters/counts/order and single-record detail |

## Configure one registered pack outside the browser

Use the Phase 3A [registration CLI](model-pack-registration.md) to create a
trusted `maintainer_final_v2` pack. The only startup binding is the environment
variable `CIDS_MODEL_PACK_ID`, containing one lowercase 64-hex pack ID. It maps
to the fixed app-controlled directory `artifacts/v2.1/model-packs/<ID>` under
this checkout. Symlinked binding paths are refused. The browser has no pack
selector, model uploader, arbitrary artifact path/URL, or trust acknowledgement
control. Changing the binding requires changing the launch environment and
restarting the process.

```bash
# From the repository root, in the pinned Python 3.12.14 dashboard environment:
PYTHONPATH=src python -m cids.experiments.preflight_model_pack \
  --pack-dir artifacts/v2.1/model-packs/<model_pack_id>
CIDS_MODEL_PACK_ID=<model_pack_id> streamlit run dashboard/app.py \
  --server.address 127.0.0.1 --browser.gatherUsageStats false \
  --client.disableDataExport true
```

Without the variable, evidence mode starts normally and the analysis page says
analysis is unavailable. Invalid packs and runtime mismatches also disable that
page while evidence remains usable. Binding a pack does not authorize startup
loading. The analysis page preflights without deserialization; **Analyze CSV**
is the only scoring action and calls `load_model_pack()` followed by `infer()`.
Every explicit action reloads through verified checks. Completed results may be
reused on display reruns; models are not retained or cached.

## Input, privacy and session lifecycle

One uncompressed UTF-8 CSV is accepted, independently of the extension filter:
maximum **10,485,760 bytes (10 MiB)** and **50,000 data rows**. The upload's
reported byte size is checked before reading; the actual read is bounded to the
limit plus one byte. Parsing uses the versioned workbench policy and
`parse_inference_csv()`, with strict quoting and field-count checks before
pandas conversion. Duplicate, missing and unknown columns, invalid values and
inconsistent optional labels are rejected. Validation messages describe the
repair without echoing private values, IDs, unknown headers or raw tracebacks.

The exact 42 `FEATURE_COLUMNS` are listed in the page's required-columns
expander. Only `id`, `event_time`, `label`, `attack_cat` are optional. Supplied
IDs stay text (including leading zeros), are trimmed and must be non-null,
non-empty and unique. Absent IDs become `record-000001` etc. Timestamps require
ISO 8601 with an explicit offset and are normalized to UTC. Label/family rules
are unchanged; labels are validated but never used for error analysis here.

Before scoring, unknown categorical row counts are shown separately for each
model and each applicable feature. Values themselves are not echoed in the
warning. The verified fitted `OneHotEncoder(handle_unknown="ignore")` maps
unknown categories to all-zero indicators for that categorical feature; no
vocabulary, preprocessing or classification rule is altered.

The application holds validated features and predictions only in the owning
Streamlit session. It never writes upload bytes, raw rows or predictions to
disk or application logs, derives a path from the uploaded filename, or places
session data/models in global caches. Streamlit's uploader holds bytes in
memory; analysis holds a validated frame and provenance-bound results.

Replacement (including a new upload of the same bytes), invalid replacement,
removal, changed pack binding, invalid pack, analysis failure and **Clear
analysis** remove the previous result and all derived counts/selections/views.
Clear also replaces the uploader widget with an empty one. Input SHA-256 and
model-pack ID must match before a result can be displayed. Widget state uses a
new revision after invalidation, avoiding stale selections and filters. Sessions
do not share uploaded data or predictions. Navigation can discard Streamlit's
uploader widget, so returning with no upload clears completed analysis.

Clear drops application references; it is **not secure memory erasure**.
Python, Streamlit and the allocator may retain copies until memory is reclaimed
or the process ends. This is a local offline research UI, without authentication
or a remote/multi-user deployment claim.

## Research queue and record views

Each row displays its original record sequence, stable ID, binary prediction,
**Attack model score (uncalibrated)**, independent raw attack-family prediction,
**Family model score (uncalibrated)**, triage family, queue band and pack ID.
Independent family output is retained even when binary says normal.

The frozen policy remains:

| Band | Rule |
|---|---|
| `not_alerted` | Binary normal, regardless of raw family output |
| `model_disagreement` | Binary attack + raw family normal |
| `review` | Other binary attacks with attack score below 0.90 |
| `higher_score_review` | Other binary attacks with attack score at least 0.90 |

Bands organize research review, not threat severity or business risk. The
broader **Models disagree (either direction)** indicator also includes binary
normal + raw attack family; those records stay `not_alerted`. The 0.90 boundary
is frozen display policy and does not change classification.

Counts cover each queue band, both binary predictions and broader disagreements.
Filters select bands, binary outputs and disagreements. Ordering is original
sequence, descending uncalibrated attack score, or UTC timestamp when supplied.
Ties preserve original sequence. Filtering/sorting carries original row indices,
keeping IDs, outputs and selected features aligned. There is no fabricated time:
without `event_time` the view says **Record sequence**; with it, the page labels
a **Timestamp view** and **Timestamp (UTC)**. Tables show at most 200 records per
page and detail selection is limited to that page. Detail shows one result and
42 aligned features; strings longer than 200 characters are truncated only for
display. Full identities remain in session and selection uses original indices.

Streamlit's built-in table CSV download and clipboard-copy actions are disabled
by `client.disableDataExport = true`. The analysis page refuses to render data
if that control is off, and clears previous results. Launches from outside the
repository must pass `--client.disableDataExport true`.

Phase 3C did not infer errors from predictions. Phase 3D now adds uploaded-label
review, ephemeral simulation and explicit export below. Without uploaded truth,
predictions are never called measured detections or true/false positives.
`explanation_status` stays `not_requested`. Phase 3D is implemented, awaiting
independent review, not merged or released. Phase 4 follows Phase 3D merge;
packaging/release remain Phase 5.

## Uploaded-label review and ephemeral simulation

All new measured metrics are **derived from the uploaded sample**, separate
from frozen benchmark evidence. Binary review requires uploaded `label` (0 =
normal, 1 = attack); it shows TP/TN/FP/FN counts and a 2×2 confusion matrix
(actual normal/attack rows, predicted normal/attack columns). Full-sample
metrics include explicit numerators and denominators:

| Metric | Numerator | Denominator |
|---|---|---|
| Precision | TP | TP + FP (predicted attacks) |
| Recall | TP | TP + FN (actual attacks) |
| F1 | 2 × TP | 2 × TP + FP + FN |
| FPR | FP | FP + TN (actual normals) |
| FNR | FN | FN + TP (actual attacks) |

A zero denominator means **Unavailable**, with an explanation, never a silent
zero. Single-class samples retain their defined rates; undefined ones remain
unavailable. Defined zero recall/F1 is still zero when its denominator is positive.
Metrics cover the full upload and do not change with review filters.

Family review independently requires uploaded `attack_cat`. It compares actual
family against `family_prediction_raw`, even for binary-normal rows; it never
uses binary-gated triage family. Counts and per-record correct/misclassified
categories are sample-derived. Family-only input does not synthesize binary
labels. Neither column means prediction review only, without measured-error or
threshold controls. Actual/predicted labels, binary/family categories, bands,
inclusive attack-score range and disagreement filters compose on original row
indices. Ordering, 200-row pages, timestamps and bounded detail preserve alignment.

**Ephemeral, sample-specific threshold simulation** is enabled only with
uploaded binary labels. It uses completed attack model scores on the **full
current uploaded sample**, including filtered-out records, to show simulated
alerts, confusion matrix and the same explicit-denominator metrics. The pinned
scikit-learn 1.8.0 `HistGradientBoostingClassifier.predict` implementation was
inspected: classes `(0, 1)`, raw margin strictly `> 0`, exact ties normal. The
binary sigmoid score boundary is **0.50**. Simulation starts there and uses
`attack_model_score > threshold`; score equality is normal. It compares stored
scores only; floating-point sigmoid rounding near 0.50 can differ from the
estimator's raw-margin decision. Original predictions remain authoritative.
The separate frozen **0.90** queue boundary remains unchanged.

**Reset simulation to baseline** restores 0.50. No model is loaded or scored
for review, simulation or export reruns. No predictions, review categories,
queue bands, fitted models, configuration or evidence are mutated. Scores are
uncalibrated; this is not an optimal-threshold recommendation. No official-test
partition is read or scored in these checks. The page warns against uploading
official-test rows or selecting thresholds using benchmark evidence. Arbitrary
feature rows alone cannot establish uploaded-data provenance.

## Explicit JSON/CSV export contract

Choose **Export scope**, **Export format** (JSON by default), and optionally
**Include ephemeral simulation in export**, then **Prepare export**. Only this
explicit action generates bytes. A dedicated **Download prepared JSON/CSV**
control then appears. Built-in dataframe download/copy remains disabled and
fail-closed. No upload filename becomes an application path; fixed download
names are `cids-review.json` and `cids-review.csv`.

`full_analysis` exports original sequence order. `current_filtered_review`
exports all matching pages in the current stable review order, including zero
matches. Export controls state the scope/count; selected detail and page do
not limit export. Changing scope, format, applicable filters/order or simulation
discards stale prepared bytes and download state. All analysis transitions
(replacement including same bytes/new upload and invalid replacement, removal,
clear, explicit reanalysis, validation/inference failure and changed/invalid
pack binding) clear simulation and prepared exports. A new analysis starts at
baseline. Sessions share no application-owned upload/result/export state.
Bytes are held in session memory and served through Streamlit's memory download
mechanism; no application logging, disk persistence or global data caching.
Clearing references does not securely erase Python/Streamlit/allocator copies.
Downloaded files are under the user's control.

The `cids-review-export-v1` allowlist is defined by `METADATA_FIELDS` and
`RECORD_FIELDS` in `src/cids/workbench/export.py`:

| Metadata fields | Meaning |
|---|---|
| `export_schema_version`, `input_sha256`, `model_pack_id`, `provenance_type` | Version and binding; pack provenance is `maintainer_final_v2`, not an uploaded-data provenance claim |
| `export_scope`, `record_count`, `full_analysis_record_count`, `ordering` | Explicit exported scope/count versus full upload, stable ordering |
| `notices` | Research/uncalibrated-score, provenance, undefined-metric and memory/CSV limitations |
| `original_sample_metrics`, `exported_scope_metrics` | Original binary metrics for full upload and exported scope; null without binary truth |
| `simulation` | Optional ephemeral report with threshold, baseline, strict comparison rule, full-sample scope, alert count and sample metrics; null when omitted |

| Per-record fields | Meaning |
|---|---|
| `record_sequence`, `record_id`, `event_time_utc` | Original 1-based sequence, stable full ID, supplied normalized UTC time or null |
| `binary_prediction`, `attack_model_score` | Original binary prediction and uncalibrated attack score |
| `family_prediction_raw`, `family_model_score`, `triage_family` | Independent raw family, its uncalibrated score and separate frozen triage result |
| `queue_band`, `models_disagree`, `explanation_status` | Frozen band, both-direction disagreement and `not_requested` |
| `actual_binary_label`, `binary_error`, `actual_family_label`, `family_error` | Only uploaded truth and its independent review categories; null without corresponding truth |
| `simulated_binary_decision` | Separate optional 0/1 decision at the exported simulation threshold; null when omitted |

All 42 raw features, contributions, model/artifact contents, filesystem paths,
upload filenames and unrelated session data are omitted. Original outputs stay
distinct from simulated decisions. Reports include count/matrix/metric metadata;
each undefined metric `value` is JSON `null` with a zero denominator and reason,
meaning unavailable, not measured zero. JSON uses strict `allow_nan=False`;
NaN/Infinity are rejected, never emitted.

CSV repeats allowlisted metadata in each record row; nested notices/metric/
simulation objects use strict JSON within quoted cells. A zero-match export
contains one metadata-only CSV row with count 0 and empty record fields. Missing
per-record values are empty cells; undefined metrics remain null inside the
nested JSON. Every string cell passes formula neutralization: an apostrophe is
prefixed for `=`, `+`, `-`, `@`, tab or carriage return, including initiators
behind leading Unicode whitespace/control characters. Genuine typed numeric
fields stay numeric representations, without apostrophes. Standard CSV quoting
handles quotes, delimiters and embedded line breaks. JSON preserves original
IDs; sanitized CSV IDs may gain an apostrophe. Downstream spreadsheets/tools
may transform safeguards, so JSON remains the default.

## Degraded states

The catalog loads each component independently and classifies it as
`verified`, `missing`, `failed` (integrity or validation failure), or `skipped`
(a prerequisite is unavailable).

- If the official-test evidence is missing or fails verification, every result
  page shows the failure and no metric; nothing is substituted.
- If only the selection record fails, the validation comparison is hidden and
  the reason is shown; official-test pages still work.
- If the gate report is missing or fails, only the Explainability page degrades.
- If verified evidence still violates a display contract, for example an
  unexpected class label, the page shows the violation and stops rendering
  rather than substituting values.
- Missing per-class values are listed as not recorded, never as weaknesses.
- Programming errors (for example `KeyError`) are not caught as evidence status.

## Architecture

```text
dashboard/app.py                 # Entry point: adds src/ to sys.path, calls main()
src/cids/dashboard/              # The only package that imports Streamlit
├── app.py                       # Page registry, navigation, sidebar
├── components.py                # Shared tiles, badges, tables, error panels
├── charts.py                    # Altair specifications and palettes
└── views/                       # One module per page: render(catalog)
src/cids/workbench/              # Framework-independent services
├── integrity.py                 # Pinned-digest and strict-JSON primitives
├── evidence.py                  # Phase 1 v2.0 loader (now uses integrity.py)
├── gate_evidence.py             # v2.1 gate report loader and validator
├── catalog.py                   # Component loading, digest bindings, health
├── reporting.py                 # Stages, metric definitions, traceable values
├── confusion.py                 # Confusion matrices and consistency checks
├── formatting.py                # Deterministic text formatting
├── analysis.py                  # Session lifecycle, binding and bounded queue indices
├── review.py                    # Uploaded-label review and score-only simulation (3D)
└── export.py                    # Allowlisted in-memory JSON/CSV serialization (3D)
```

The design document placed page code in `dashboard/`; it lives in
`src/cids/dashboard/` instead so pages are importable and testable like the rest
of the package, while `dashboard/app.py` stays the documented entry point.

Evidence is re-verified on every Streamlit rerun (about 7 ms) instead of being
cached, so an on-disk change can never be masked by stale memory.

## Tests

```bash
pytest -q
```

Non-UI logic is tested in every CI environment. `tests/test_dashboard_app.py`,
`tests/test_dashboard_analysis.py` and `tests/test_dashboard_review_export.py`
use Streamlit's `AppTest` to render every page from committed evidence and in
degraded states; it is skipped where Streamlit is not installed and runs in the
`dashboard-phase-2` CI job. The tests also check that:

- no recorded metric value appears as a literal in the dashboard source;
- a re-pinned edit to the evidence changes the displayed value;
- pages render with `joblib.load` and `pickle.load` disabled;
- the services import neither Streamlit nor SHAP;
- the app refuses to render when bound beyond loopback or with telemetry on;
- a matching edit to per-class and macro F1 is still detected, and a code defect
  in the consistency checks raises instead of being reported as bad evidence.

## Validation performed for Phase 3D (2026-10-04)

Implemented on `cids-v2.1-phase3d-review-export`, based on Phase 3C merge
`9d81a3c4136f7062aca3c238c0d041e722dd1330`; awaiting independent review,
not merged or released. No dependency or CI matrix changes.

All four existing local environments ran Python **3.12.14**. Full suites used
`CIDS_PHASE3B_TRAINING_CSV=/private/tmp/cids-phase3b-training.csv` to execute the
optional original-pack training-row gates in pinned environments.

| Environment | Full suite | Exact skips |
|---|---|---|
| Base (`/private/tmp/cids-phase3b-base`) | 325 passed, 59 skipped | 53 pinned-runtime model cases; 4 Streamlit modules/checks; 2 SHAP modules/checks |
| Reproduction (`/private/tmp/cids-phase3b-reproduction`) | 378 passed, 6 skipped | 4 Streamlit modules/checks; 2 SHAP modules/checks |
| Workbench (`/private/tmp/cids-phase3b-workbench`) | 387 passed, 4 skipped | 4 Streamlit modules/checks |
| Dashboard (`/private/tmp/cids-phase3b-dashboard`) | 464 passed, no skips | None |

Streamlit skips are `test_dashboard_app.py`, `test_dashboard_analysis.py`,
`test_dashboard_review_export.py`, and the dashboard-control check in
`test_workbench_model_pack_registration.py`. SHAP skips are
`test_workbench_explanations.py` and the gate-version check in
`test_workbench_gate_evidence.py`. Base runtime skips are the same 53 cases in
`test_workbench_inference.py`: base model libraries do not match the pack lock.
These local base results use Python 3.12.14; the preserved GitHub `test` job
provides Python 3.11 coverage on the pushed head.

Focused contract/session/review/export/UI/inference suite: **188 passed, no
skips**. This includes all truth-column combinations, known binary matrices,
independent family errors, undefined and defined-zero rates, exact estimator
tie behavior, score boundaries/reset, unchanged original records, composed
filters/sorting/pagination/detail, explicit exports/default JSON, allowlists,
provenance/scope, strict JSON, adversarial CSV IDs and whitespace/control
variants, all lifecycle transitions, cross-session isolation and no extra
loading/scoring on display/simulation/export reruns. Existing evidence-only
clean-root navigation and loopback/telemetry/export guards remain covered.
One pre-existing AppTest fixture was corrected to restore real preflight
regardless of module execution order.

All four environments passed `python -m pip check`. Full suites passed with
one existing loky physical-core-discovery warning each; reproduction also
emitted 46 sklearn parallel-configuration warnings (47 warnings total). These
are warnings, not failures/skips. Dependency checks emitted only the local
non-writable pip-cache warning. `git diff --check` passed. Frozen configurations,
results/evidence, dataset manifest, dependency locks and workflow were unchanged.

The ignored registered original pack
`e2d4f329b894a1b68b70af377ffc94441e02d024de27e7c351384d3e25692b18`
passed direct/UI equality on **16 training-partition rows**. The training copy
was verified at 32,293,018 bytes and SHA-256
`bec7dd5ec88dc2a0ccc7a07879d338395ed7421750f675fd0339e07dfe0648fa`
before parsing. The UI then exercised simulation/reset/export with loading and
scoring forbidden and preserved the same original result. Synthetic fixtures
cover the rest; no official-test rows were read, scored or used for tuning.

Reproduce focused checks in the pinned dashboard environment:

```bash
python -m pytest -q tests/test_workbench_contracts.py \
  tests/test_workbench_analysis.py tests/test_workbench_review.py \
  tests/test_workbench_export.py tests/test_workbench_inference.py \
  tests/test_dashboard_analysis.py tests/test_dashboard_review_export.py
python -m pytest -q -ra
python -m pip check
git diff --check
```

Without the optional explicitly verified training copy and local registered
artifacts, original-pack gates skip with their stated reasons. This does not
substitute for those executed local checks. AppTest covers interactions;
Phase 3D real-browser visual QA remains unperformed. Clearing references is
not memory erasure; scores are uncalibrated and upload provenance unverified.
Phase 4 follows Phase 3D merge.

## Validation performed for Phase 3C (2026-10-04)

Implementer-reported local verification follows. All four existing local
environments used Python **3.12.14**. Full suites ran
with `CIDS_PHASE3B_TRAINING_CSV=/private/tmp/cids-phase3b-training.csv` so the
optional original-pack gate actually executed in each pinned model environment.

| Environment | Full suite | Exact skips |
|---|---|---|
| Base (`/private/tmp/cids-phase3b-base`) | 272 passed, 58 skipped | 53 pinned-runtime model cases; 3 Streamlit checks/modules; 2 SHAP checks/modules |
| Reproduction (`/private/tmp/cids-phase3b-reproduction`) | 325 passed, 5 skipped | 3 Streamlit checks/modules; 2 SHAP checks/modules |
| Workbench (`/private/tmp/cids-phase3b-workbench`) | 334 passed, 3 skipped | 3 Streamlit checks/modules |
| Dashboard (`/private/tmp/cids-phase3b-dashboard`) | 394 passed, no skips | None |

The three Streamlit skips outside the dashboard environment are
`test_dashboard_app.py`, `test_dashboard_analysis.py`, and the dashboard-control
check in `test_workbench_model_pack_registration.py`. The two SHAP skips are
`test_workbench_explanations.py` and the gate-version check in
`test_workbench_gate_evidence.py`. Base runtime skips are the 53 parametrized
cases in `test_workbench_inference.py`; its installed model libraries do not
match the pinned pack runtime. Pinned workbench/dashboard inference tests
executed. Every full suite emitted one existing loky physical-core-discovery
warning, falling back to logical cores; this was not a failure or skip.

Focused contract/session/UI/inference verification: **118 passed, no skips**.
All four environments passed `python -m pip check`; `git diff --check` passed.
The four existing CI jobs and dependency locks were preserved. These are the
implementer's local results, separate from the independent review below.

The registered original pack `e2d4f329b894a1b68b70af377ffc94441e02d024de27e7c351384d3e25692b18`
passed both direct inference and the Streamlit AppTest analysis page on exactly
**16 training-partition rows**, with identical `PredictionRecord` tuples and
unchanged results on a display rerun. Before parsing those rows, the source
copy's 32,293,018-byte size and SHA-256
`bec7dd5ec88dc2a0ccc7a07879d338395ed7421750f675fd0339e07dfe0648fa`
were verified against the committed training manifest. No official-test raw
file or record was accessed or scored, and no frozen evidence was edited.

A temporary configured-pack server passed `/_stcore/health` (`ok`) and `lsof`
confirmed `127.0.0.1:8503` only. Analysis interactions were verified through
AppTest; real-browser visual inspection of the new page was not performed
(the browser surface was unavailable). Clear removes references rather than
securely erasing memory.

Phase 3C was pushed and independently reviewed at
`b60a703b52a24ebef3e3903b51408d1151968baa`, with **no blocking findings**.
Independent tests: **391 passed / 3 skipped**; dependency check passed.
All four GitHub CI jobs (`test`, `reproduction-environment`, `workbench-phase-1`,
`dashboard-phase-2`) passed on that commit. The independent reviewer could not
repeat original-model integration checks requiring ignored local artifacts;
the original-pack checks above remain separately reported by the implementer.
New-page browser visual QA remains unperformed. Phase 3C merged through PR #4
at `9d81a3c4136f7062aca3c238c0d041e722dd1330`; all four post-merge CI jobs
passed in [CI run 37180576999](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/actions/runs/37180576999).

## Validation performed for Phase 2

- A fresh `git clone` of the branch, with no `artifacts/` directory and no
  dataset, passed the complete suite (including every Streamlit page test)
  and started a healthy loopback-only server.
- Full suite in the pinned workbench environment (Python 3.12.14, no Streamlit),
  in the dashboard environment (Python 3.12.14 with `requirements-dashboard.txt`),
  and in a Python 3.11 environment matching the base CI job.
- The dashboard was served locally and every page was inspected in Chrome in
  both dark and light themes. This found and fixed a heatmap that failed in the
  browser but passed `AppTest`, a theme/palette mismatch, and several truncation
  and axis-label problems. The browser console showed no errors afterwards.
- The server was confirmed to listen on `127.0.0.1` only when started from the
  repository root. When started elsewhere it listened on all interfaces, which
  is why the startup guard exists.
- Two independent code reviews (general, and error handling) were run on the
  change. Their material findings were fixed and covered by tests: a manifest
  crash path, overclaiming consistency checks, page-level recomputation,
  fail-open network and telemetry settings, and unrecorded-value handling.

## Known limitations

- Local analysis requires an already registered original pack and the exact
  pinned runtime. Clean clones provide evidence mode and a disabled analysis
  page. Phase 3D sample review/simulation/export requires explicit local analysis
  and uploaded truth where applicable; it does not establish upload provenance.
- No feature attributions. The gate report stores diagnostics only; global and
  per-record explanations are Phase 4.
- The official-test report records artifact filenames but not artifact hashes;
  model digests shown come from the v2.1 gate.
- The Apple Silicon reproduction record is not committed and cannot be displayed.
- Degraded states are tested with `AppTest`; only the fully verified state was
  inspected in a real browser.
- Charts depend on Streamlit's bundled Vega-Lite renderer; `AppTest` cannot
  detect client-side rendering failures, so visual checks remain manual.
- When started outside the repository root without the loopback and telemetry
  flags, the page refuses to render, but Streamlit has already bound the port on
  all interfaces and serves that refusal. A launcher script or container
  (Phase 5) would enforce the binding itself.
- Missing values in numeric tables render as Streamlit's empty-cell marker
  rather than the words "not recorded"; they are never shown as zero.
- Docker packaging, the non-root image, and release checks are Phase 5.
