# v2.1 SHAP compatibility gate

Gate version: `cids-shap-compatibility-gate-v1`

Status: **Representative gate passed; selected local artifacts pending**

## Purpose

The v2.1 design does not assume that SHAP supports the selected binary and
multiclass models correctly. This gate checks the real locally retained v2.0
final artifacts before any explanation UI is approved.

It verifies:

- pinned SHAP `0.52.0` on the exact Python 3.12 model environment;
- binary and multiclass class-axis mapping;
- reconstruction of raw estimator outputs within `1e-5` absolute error;
- lossless aggregation from transformed one-hot fields to 42 source features;
- a deterministic 256-row prepared-training background;
- ten prepared-validation records per task;
- a maximum of 32 explained records and 60 seconds per task;
- no use of official-test records as explanation background or foreground.

SHAP explains the estimator's raw decision output in this gate. It does not
turn the model score into calibrated confidence and does not prove that a feature
caused an attack.

## Automated representative proof

The automated test suite trains representative binary and multiclass
`HistGradientBoostingClassifier` artifacts through the project's real
preprocessing and final-artifact code. It verifies SHAP dimensions, additivity,
class mapping, and aggregation back to the original schema.

An additional bounded synthetic shape check used the same selected estimator
family and parameters with the actual transformed dimensions recorded by v2.0:

| Task | Shape | 256-row background / 10 explanations | Maximum additivity error |
|---|---:|---:|---:|
| Binary | `10 × 194` | 0.123 seconds | `2.75e-08` |
| Multiclass | `10 × 68 × 10` | 13.176 seconds | `7.43e-08` |

These results establish a representative compatibility proof only. The gate is
not complete until it passes against Arun's two original local final artifacts.

## Run the selected-artifact gate on macOS

Do not modify the frozen v2.0 reproduction environment. Create a separate v2.1
environment from the repository root:

```bash
python3.12 -m venv "$HOME/.virtualenvs/cids-v2.1-workbench"

VENV_DIR="$HOME/.virtualenvs/cids-v2.1-workbench"

"$VENV_DIR/bin/python" -m pip install pip==26.2.1
"$VENV_DIR/bin/python" -m pip install -r requirements-workbench.txt
```

Confirm that the original ignored artifacts still exist:

```bash
ls -lh \
  artifacts/v2/official-test-v1/binary-hist_gradient_boosting.joblib \
  artifacts/v2/official-test-v1/multiclass-hist_gradient_boosting.joblib
```

Run the gate once. This command reads only the 42 official-test feature columns
required by the frozen duplicate-removal split policy. It never loads
official-test IDs or targets and never transforms, predicts, explains, scores,
or reports official-test rows:

```bash
PYTHONPATH=src caffeinate -i "$VENV_DIR/bin/python" \
  -m cids.experiments.run_shap_gate \
  --data-dir dataset/unsw-nb15/raw \
  --binary-artifact artifacts/v2/official-test-v1/binary-hist_gradient_boosting.joblib \
  --multiclass-artifact artifacts/v2/official-test-v1/multiclass-hist_gradient_boosting.joblib \
  --output artifacts/v2.1/shap-gate-selected-v1.json \
  --confirm TRUST_LOCAL_V2_ARTIFACTS
```

The confirmation phrase means only that these are artifacts the user created
locally. It does not make an artifact from another source safe.

Expected terminal status:

```text
SHAP compatibility gate: PASSED
Official test status: not_evaluated_by_gate
Wrote gate report: artifacts/v2.1/shap-gate-selected-v1.json
```

Preserve a copy for review without committing generated model files:

```bash
shasum -a 256 artifacts/v2.1/shap-gate-selected-v1.json
cp artifacts/v2.1/shap-gate-selected-v1.json \
  "$HOME/Downloads/cids-v2.1-shap-gate-selected-v1.json"
```

Upload that JSON report to the project conversation. If both tasks pass, the
SHAP decision can be accepted and Phase 1 can close. If either task fails, do not
build explanation UI; record the failure and decide the fallback in a new ADR.

## References

- [SHAP package](https://pypi.org/project/shap/) — version `0.52.0` publishes a
  Python 3.12+ Apple Silicon wheel.
- [SHAP TreeExplainer](https://shap.readthedocs.io/en/stable/generated/shap.TreeExplainer.html)
  — tree explanations, background-data behavior, and raw/probability outputs.
