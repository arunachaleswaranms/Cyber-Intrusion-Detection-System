# v2.1 evidence dashboard (Phase 2)

Status: **Implemented; evidence mode only**

The dashboard presents the frozen v2.0 benchmark and the accepted v2.1
explanation gate. It reads committed, non-executable evidence, verifies it on
every page view, and shows where each number came from. It does not load a
model, read the UNSW-NB15 CSV files, make predictions, or recompute any
official result.

> Offline research artifact, not a production IDS. There is no authentication;
> the server listens on `127.0.0.1` only.

## Launch

Requires Python 3.12 (the pinned environments use 3.12.14). From the repository
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
"magic" rendering. No dataset, model artifact, or network access is needed.

Streamlit only reads that file from the current directory. The app therefore
re-checks the policy at startup and **refuses to render** if the server is not
bound to loopback or telemetry is enabled. To launch from elsewhere, pass
`--server.address 127.0.0.1 --browser.gatherUsageStats false`.

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
└── formatting.py                # Deterministic text formatting
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

Non-UI logic is tested in every CI environment. `tests/test_dashboard_app.py`
uses Streamlit's `AppTest` to render every page from committed evidence and in
degraded states; it is skipped where Streamlit is not installed and runs in the
`dashboard-phase-2` CI job. The tests also check that:

- no recorded metric value appears as a literal in the dashboard source;
- a re-pinned edit to the evidence changes the displayed value;
- pages render with `joblib.load` and `pickle.load` disabled;
- the services import neither Streamlit nor SHAP;
- the app refuses to render when bound beyond loopback or with telemetry on;
- a matching edit to per-class and macro F1 is still detected, and a code defect
  in the consistency checks raises instead of being reported as bad evidence.

## Validation performed for Phase 2

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

- Evidence mode only. No trusted inference, upload, review queue, or export
  (Phase 3).
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
