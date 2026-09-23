# v2.1 Phase 1 explanation-gate evidence

This directory preserves the unmodified machine-readable output from the SHAP
compatibility gate completed on Arun's Apple Silicon Mac on 2026-09-23.

- `shap-gate-selected-v2.json` records the accepted binary and multiclass
  selected-artifact checks.
- `SHA256SUMS` records the verified hash of the uploaded report.
- Local `.joblib` models remain excluded because they are executable
  pickle-based artifacts and are reproducible from the pinned v2.0 inputs.

The gate used only deterministic prepared-training backgrounds and
prepared-validation foregrounds. It did not load official-test targets or
explain, predict, or score official-test records.

See [`../../docs/shap-compatibility-gate.md`](../../docs/shap-compatibility-gate.md)
and [ADR 0003](../../docs/decisions/0003-v2.1-explanation-fallback.md) for the
decision, limits, and interpretation.
