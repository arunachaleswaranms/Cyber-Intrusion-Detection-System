# Phase 4 explanation resources and synthetic demonstration

Status: Phase 4 merged by PR #6 at `ce7f37e`; independent review had no blocking
findings (588 passed / 4 skipped, dependency check passed); four post-merge jobs
passed. Phase 5 container packaging merged through PR #7 at `665a3ef`; all five
post-merge CI jobs passed. Independent review found no blocking issues; its
original-model and browser checks used implementer evidence rather than repeating
them. See [acceptance scope](release-readiness-v2.1.md). The release remains unpublished.

The accepted ADR 0003 / Phase 1 gate remains unchanged. No historical gate or
original official-test evaluation is rerun. Ordinary analysis, label-backed
review, threshold simulation and safe export remain usable without resources.
The dashboard never reads official dataset files or prepares backgrounds.

## Pinned local method

- SHAP **0.52.0 PermutationExplainer** explaining `decision_function` raw output;
  Independent development background, at most 256 rows per task.
- One forward/reverse cycle, seed 42; maximum 32 selected records per service
  request. The dashboard requests **one selected record** for one task per click.
- Binary output always explains **attack**, including a normal prediction.
  Multiclass maps every output through `classes_` and selects the independent raw
  predicted family, including normal; binary-gated triage is never substituted.
- All encoded shapes and finite values, predictions, class mapping, every class's
  reconstruction (`1e-5`), and the full 42-source-feature conservation (`1e-10`)
  must pass before display. All 42 signed contributions are shown; omitted sum is
  explicitly zero. Baseline, model output and explained class remain in **raw
  decision units**, separate from uncalibrated probability-model scores.
- Attributions describe features that **influenced this model output**. Independent
  perturbation can create implausible combinations of correlated features. One
  cycle limits attribution sampling. Values depend on the background; they do not
  establish causality, confidence, severity or operational risk.

## CLI preparation

Use the exact Python **3.12.14** dashboard/workbench environment. No new dependency
or model builder is needed. First register/preflight the original locally trusted
pack using [the existing workflow](model-pack-registration.md). This command uses
that same verified loader and does not add or change pack acceptance rules.

Prefer existing prepared partitions, if available. Supply four CSVs named
`binary-train.csv`, `binary-validation.csv`, `multiclass-train.csv` and
`multiclass-validation.csv` under one private CLI directory. They must be the
full original cleaned partitions (including training IDs/targets), in frozen row
order. They are checked against the frozen train/validation counts and ID digests
and **every row is matched to the checksum-verified original training source**.
They are input files only; full partitions/targets are never published as
runtime explanation resources.

```bash
source .venv-dashboard/bin/activate
export CIDS_MODEL_PACK_ID="<registered-64-hex-pack-id>"
PYTHONPATH=src python -m cids.experiments.prepare_explanation_resources \
  --pack-id "$CIDS_MODEL_PACK_ID" \
  --training-csv /private/path/UNSW_NB15_training-set.csv \
  --prepared-dir /private/path/prepared-development
```

If these verified prepared partitions are absent, the only permitted reconstruction
uses the existing approved frozen overlap-removal/split path. Explicitly enable
feature-only access to the pinned official-test source:

```bash
PYTHONPATH=src python -m cids.experiments.prepare_explanation_resources \
  --pack-id "$CIDS_MODEL_PACK_ID" \
  --training-csv /private/path/UNSW_NB15_training-set.csv \
  --official-test-feature-reference /private/path/UNSW_NB15_testing-set.csv \
  --allow-test-feature-overlap
```

The source bytes must match the committed frozen dataset hashes/sizes. The test
CSV is parsed with **only the 42 feature columns**: no targets or IDs. Its features
only remove equivalent training observations, then are discarded. Test rows
never reach preprocessing, predictions, explanations, metrics or tuning. No new
official-test result is produced. Prepared split ID/count checks must still pass.
No custom source manifest or browser path/URL/upload/trust shortcut exists.

The CLI deterministically samples each task's prepared **training** partition
using the accepted gate's target-stratified hash ranking. One row per observed
target is selected first, remaining slots follow the established hash order, and
selected rows are sorted by source ID. Split and explanation seed stay 42.

Output is private, non-executable CSV/JSON under the ignored, app-controlled
`artifacts/v2.1/explanation-resources/<resource-digest>/`. Background CSVs contain
**only the 42 required features**, never IDs, targets or raw full datasets. Files
are created mode 0600 in a private directory; publication follows complete writes.
Existing resource versions are verified and reused rather than overwritten.

The versioned manifest binds canonical resource identity, each file's SHA-256,
size and row count, both pack artifact hashes/sizes, pack ID/runtime, feature
schema, policy digest, seed, frozen dataset/split provenance, training scope and
sample ID digests. The startup digest anchors this locally prepared declaration;
the browser cannot independently prove arbitrary uploaded-data provenance.
Runtime checks reject symlinks (including controlled parents), nonregular files,
escaping filenames, files above 1 MiB/background or 32 KiB/JSON, changed descriptors,
digest mismatches, optional target columns, wrong pack/artifacts/runtime, invalid
schema/policy, or incompatible development provenance. There is no pickle/numpy
object resource loading. Registered pack manifests and rules are unchanged.

After preparation, use the digest printed by the CLI:

```bash
export CIDS_EXPLANATION_RESOURCE_ID="<printed-64-hex-resource-digest>"
PYTHONPATH=src streamlit run dashboard/app.py
```

Only these fixed startup IDs are accepted; restart after changing launch bindings.
Missing or incompatible resources produce `unsupported`, while the completed
analysis remains usable. Valid resources start `not_requested`; explicit successful
work becomes `available`; timeouts, worker errors and correctness failures become
`failed` with a fixed safe message and no fabricated attribution.

## Cancellation and session lifecycle

Each action starts a fresh dedicated Python subprocess worker, compatible with
macOS and independent of Streamlit's main-script bootstrap.
It revalidates the resource bundle and uses the existing verified model-pack
loader; no model or SHAP object is held in a global cache. The worker receives at
most 1 MiB of JSON containing selected feature rows only, not the full upload.
Responses use bounded JSON bytes (128 KiB maximum), never unpickled IPC results.
A parent deadline watchdog kills the worker even if IPC stalls; failure paths
terminate/kill, wait/reap and close pipes. The 60-second limit includes
worker startup/import, pack/resource checks and computation, not a post-hoc elapsed
check after unrestricted SHAP work. One cold startup may time out on slower hosts.

Every result binds full input digest, pack ID, resource/background digests,
policy digest, task/class, original record index and ID. Binary/family results are
separate. Replacement/removal, clear, invalid input, failed analysis, explicit
reanalysis and pack changes clear prior explanations. Resource/policy changes or
failed resource validation clear attributions while preserving analysis. Selection
changes discard old selected explanations (at most two task results are retained).
Navigation, filtering, simulation, preview and export never compute SHAP.

Observed strings are bounded to 200 characters for attribution presentation;
original features remain in session memory. Models, uploads and explanations are
not application-persisted or logged. Clear drops references; it is not secure
memory erasure. Built-in table downloads/copy stay disabled. The **Phase 3D export
schema and allowlist are unchanged**: downloads omit features, contributions and
new local explanation state. Their `explanation_status` belongs to the original
analysis snapshot and stays `not_requested`; the selected-record task states are
shown independently in the dashboard. Explicit explanation failures leave
predictions, labels, queue bands, sample metrics, simulation and prepared exports
unchanged.

## Explicit offline global model reliance

Add **`--prepare-global`** to either preparation command to compute the separate
global evidence path. It never computes SHAP. For each task, it samples at most
256 **prepared-validation** rows using the same deterministic target-stratified
policy, independently permutes each original feature before encoding, and measures
mean/std decrease in **macro F1 over all estimator classes, zero_division=0**.
There are exactly 3 repeats per feature and seed 42. Negative decreases are valid.
Task, partition, sample size, sample ID digest, seed, metric, method, file digest
and development provenance are recorded. Target columns are needed only during
this CLI calculation and are not written into its evidence outputs.

The selected final models were refit on training **plus validation**. This is
therefore in-development **global model reliance**, not a new held-out benchmark,
per-record explanation or causal claim. It remains distinct from frozen official
results and local SHAP. The Explainability page loads it only after **Load configured
global model reliance**; absent evidence is honestly unavailable. Default evidence
pages need neither SHAP import nor model/background loading, even with bindings
configured. Aggregated uploaded-record SHAP is never substituted.

## Safe sample and verification

[The committed synthetic CSV](../samples/synthetic-features-v1.csv) has eight
arithmetic rows with no official-data copies, hosts, IPs, timestamps or labels.
[Sample documentation](../samples/README.md) describes construction and local
preview/download/analysis. A clean clone can inspect/download it, but predictions
require a configured trusted pack and explanations additionally require verified
backgrounds. Its outputs exercise mechanics only; they establish no detection
quality or realism. No demo model builder or broader provenance acceptance exists.

```bash
PYTHONPATH=src python -m pytest -q -rs \
  tests/test_explanation_resources.py tests/test_phase4_explanations.py \
  tests/test_phase4_lifecycle.py tests/test_prepare_explanation_resources.py \
  tests/test_dashboard_phase4.py tests/test_synthetic_sample.py
python -m pip check
```

Representative tests use constructed/synthetic rows and explicitly substituted
**test-only** trust anchors. They exercise real preprocessing, selected estimators,
verified loading, subprocess/SHAP, resource validation, publication, timeout/error/partial
IPC cleanup, lifecycle, explicit actions, session isolation and unchanged exports.
They are not original-model integration or benchmark evidence. Optional original
integration uses only the committed synthetic foreground:

```bash
CIDS_PHASE4_ORIGINAL_RESOURCE_ID="$CIDS_EXPLANATION_RESOURCE_ID" \
  PYTHONPATH=src python -m pytest -q -rs \
  tests/test_phase4_explanations.py::test_optional_original_pack_explains_synthetic_sample_only
```

Run only when the original trusted pack and compatible CLI-prepared resources
exist. No test foreground is scored or explained. Exact implementation verification
counts, skips and browser visual QA limits are recorded in [dashboard.md](dashboard.md).

## Container resources (Phase 5)

Use the separate [trusted-resource Compose workflow](container.md#local-explanations-and-separate-global-reliance).
It mounts only the configured digest directory read-only at the existing controlled
path, with a nonzero UID able to traverse/read the private host files. No root or
world-writable permission workaround is permitted. Preparation remains a host CLI
action; global reliance requires `--prepare-global`. Session data stays in memory;
clearing references is not secure erasure. Original-model and container integration
results are tracked in [release acceptance](release-readiness-v2.1.md).
