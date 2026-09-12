# v2.0 one-time official-test protocol

Protocol: `unsw-nb15-final-evaluation-v1`

Canonical protocol SHA-256:
`c4fc000d24d27cada9740c1350c3b1e22d710cbd537353f33c9036a980ccb517`

Status: **Completed once on 2026-09-12; do not rerun**

## Purpose

This protocol prevents the official UNSW-NB15 test partition from becoming an
iterative tuning dataset. The selected model names, parameters, preprocessing,
training scope, and test procedure are pinned before final metrics are observed.

The final run performed these steps:

1. Verify the official CSV files against the committed manifest.
2. Verify a clean validation reproduction against the recorded selection.
3. Verify the experiment, selection, and final-protocol hashes.
4. Recombine the cleaned training and validation partitions.
5. Refit preprocessing on that combined development partition.
6. Train fresh selected Histogram Gradient Boosting models for binary and
   multiclass tasks.
7. Evaluate both models on the immutable official test partition.
8. Persist final model artifacts, metrics, provenance, and completion state.

## Safeguards

- The command requires the exact confirmation phrase
  `EVALUATE_OFFICIAL_TEST_ONCE`.
- The output directory must not already exist.
- The reproduced selection must be a separate generated file, not the committed
  selection record.
- Reproduced winners, candidate order, ranking rules, artifact versions, and
  configuration must match the committed record exactly. Selected validation
  metrics may differ by at most `0.005` absolute to accommodate bounded
  cross-platform numerical variation.
- Any configuration, selection, protocol, manifest, schema, or split mismatch
  stops the run before model evaluation.
- If execution fails after starting, `run_state.json` remains `in_progress` for
  investigation instead of silently pretending the run completed.

These controls make accidental reruns difficult, but Git cannot technically stop
someone from copying the repository and choosing a different output directory.
The single-run rule therefore also depends on preserving the committed result and
not using test performance for another tuning cycle.

## Step 1: clean validation reproduction

From the repository root, create a new Python 3.12 environment and generated
artifact directory. The benchmark lock file is intentionally separate from the
general development requirements:

```bash
python3.12 -m venv .venv-reproduction
source .venv-reproduction/bin/activate
python -m pip install pip==26.2.1
python -m pip install -r requirements-reproduction.txt

REPRO_DIR="artifacts/v2/reproduction-v1"
```

Run every frozen candidate:

```bash
PYTHONPATH=src python -m cids.experiments.train_supervised \
  --data-dir dataset/unsw-nb15/raw \
  --task binary \
  --output-dir "$REPRO_DIR/binary"

PYTHONPATH=src python -m cids.experiments.train_supervised \
  --data-dir dataset/unsw-nb15/raw \
  --task multiclass \
  --output-dir "$REPRO_DIR/multiclass"

PYTHONPATH=src python -m cids.experiments.train_anomaly \
  --data-dir dataset/unsw-nb15/raw \
  --output-dir "$REPRO_DIR/anomaly"

PYTHONPATH=src python -m cids.experiments.select_models \
  --binary-supervised-report "$REPRO_DIR/binary/validation_results.json" \
  --multiclass-supervised-report "$REPRO_DIR/multiclass/validation_results.json" \
  --anomaly-report "$REPRO_DIR/anomaly/validation_results.json" \
  --output "$REPRO_DIR/model-selection.json"
```

Expected reproduced winners:

```text
binary: hist_gradient_boosting
multiclass: hist_gradient_boosting
Official test status: sealed
```

The reproduction gate compares the generated selection with the committed
selection. Both model names, candidate orders, ranking rules, and artifact
versions must be identical. Every selected metric must be within the protocol's
absolute tolerance of `0.005`. See
[`model-selection.md`](model-selection.md) for the recorded Apple Silicon
reproduction and its split fingerprints.

## Step 2: recorded one-time final run

The following invocation was executed once after Step 1 succeeded. It is
preserved as provenance and must not be run again for v2.0:

```bash
FINAL_DIR="artifacts/v2/official-test-v1"

PYTHONPATH=src python -m cids.experiments.evaluate_official_test \
  --data-dir dataset/unsw-nb15/raw \
  --reproduction-selection "$REPRO_DIR/model-selection.json" \
  --output-dir "$FINAL_DIR" \
  --confirm EVALUATE_OFFICIAL_TEST_ONCE
```

Do not rerun or tune after seeing these results. The original
`official_test_results.json` is preserved as repository evidence. Generated
`.joblib` artifacts remain local and must not be committed.

The completed run state and unmodified machine-readable result are preserved in
[`results/v2.0`](../results/v2.0). See
[`v2-official-test-results.md`](v2-official-test-results.md) for the benchmark
summary, limitations, and error analysis.
