# v2.1 SHAP compatibility gate

Gate version: `cids-shap-compatibility-gate-v2`

Status: **TreeExplainer rejected; bounded PermutationExplainer selected-artifact gate pending**

## Purpose

The v2.1 design does not assume that SHAP supports the selected binary and
multiclass models correctly. The original interventional `TreeExplainer` route
failed additivity against the selected binary artifact. [ADR 0003](decisions/0003-v2.1-explanation-fallback.md)
therefore proposes a bounded, model-agnostic `PermutationExplainer` fallback.
This gate checks the real locally retained v2.0 final artifacts before any
explanation UI is approved.

It verifies:

- pinned SHAP `0.52.0` on the exact Python 3.12 model environment;
- binary and multiclass class-axis mapping;
- reconstruction of raw estimator outputs within `1e-5` absolute error;
- lossless aggregation from transformed one-hot fields to 42 source features;
- model-agnostic `PermutationExplainer` with one forward/reverse cycle and seed
  `42`;
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

An additional bounded synthetic fallback check used the same selected estimator
family and parameters with the actual transformed dimensions recorded by v2.0:

| Task | Shape | 256-row background / 10 explanations | Maximum additivity error |
|---|---:|---:|---:|
| Binary | `10 × 194` | 15.080 seconds | `1.15e-14` |
| Multiclass | `10 × 68 × 10` | 8.672 seconds | `3.11e-14` |

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
  --output artifacts/v2.1/shap-gate-selected-v2.json \
  --confirm TRUST_LOCAL_V2_ARTIFACTS
```

The confirmation phrase means only that these are artifacts the user created
locally. It does not make an artifact from another source safe.

Expected terminal status:

```text
SHAP compatibility gate: PASSED
Official test status: not_evaluated_by_gate
Wrote gate report: artifacts/v2.1/shap-gate-selected-v2.json
```

Preserve a copy for review without committing generated model files:

```bash
shasum -a 256 artifacts/v2.1/shap-gate-selected-v2.json
cp artifacts/v2.1/shap-gate-selected-v2.json \
  "$HOME/Downloads/cids-v2.1-shap-gate-selected-v2.json"
```

Upload that JSON report to the project conversation. If both tasks pass, ADR
0003 can be accepted and Phase 1 can close. If either task fails, do not build
per-record explanation UI; use only global permutation importance calculated on
development data.

## References

- [SHAP package](https://pypi.org/project/shap/) — version `0.52.0` publishes a
  Python 3.12+ Apple Silicon wheel.
- [SHAP TreeExplainer](https://shap.readthedocs.io/en/stable/generated/shap.TreeExplainer.html)
  — tree explanations, background-data behavior, and raw/probability outputs.
- [SHAP PermutationExplainer](https://shap.readthedocs.io/en/stable/generated/shap.PermutationExplainer.html)
  — model-agnostic local explanations and forward/reverse permutation behavior.
