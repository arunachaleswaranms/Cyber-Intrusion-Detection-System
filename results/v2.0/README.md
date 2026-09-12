# v2.0 official-test evidence

This directory preserves the machine-readable output from the single guarded
UNSW-NB15 official-test evaluation completed on 2026-09-12.

- `official-test-results.json` is the unmodified evaluation report produced by
  the runner.
- `run-state.json` is the unmodified completion record produced by the same run.
- `SHA256SUMS` records the hashes calculated on Arun's Mac before the files were
  transferred into the repository.

The local `.joblib` model artifacts are intentionally excluded. Joblib uses a
pickle-based format, model binaries are reproducible from the pinned inputs, and
untrusted pickle artifacts must never be loaded.

See [`../../docs/v2-official-test-results.md`](../../docs/v2-official-test-results.md)
for interpretation, limitations, and error analysis. These results are frozen;
they must not be used to tune the v2.0 models or justify another test run.
