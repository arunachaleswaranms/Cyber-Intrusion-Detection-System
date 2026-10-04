# v2.1 release acceptance evidence

Phase 5 implemented; local and Linux CI verification passed. Independent
review/signoff is pending.
**Not release ready or published.** A build is not release acceptance.

Phase 4 merged through PR #6 at `ce7f37e2a0a33894ea5c83de40bdf5d065b7f947`.
Independent review: **588 passed / 4 skipped**, dependency check passed, no blocking
findings. All four post-merge CI jobs passed in [run 37191000174](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/actions/runs/37191000174).
Original-model explanation/global-resource integration and populated-view browser
QA were outstanding at handoff and are tracked separately below.

The following maps every [design acceptance criterion](v2.1-design.md#release-acceptance-criteria)
to evidence. Existing tests are reused without weakening production pack anchors.

| Criterion | Supporting tests/commands | State |
|---|---|---|
| Clean evidence mode, no dataset/model | `test_dashboard_app.py`, container Compose startup/AppTest | Verified locally |
| Frozen numbers/verified checksums | `test_workbench_evidence.py`, `test_workbench_catalog.py`, `test_official_results.py`, `test_workbench_gate_evidence.py`; unchanged results/config diff | Verified locally |
| No official rerun/rescore/threshold tuning | Frozen-file diff; preparation feature-only overlap tests; review/simulation operate only uploaded synthetic data | Preserved; no official evaluation command executed |
| Exact 42-feature upload contract and invalid cases | `test_workbench_contracts.py`, `test_unsw_nb15_schema.py`, `test_dashboard_analysis.py` | Verified locally |
| Bounded upload/parsing/explanations | Contract limits; `test_phase4_explanations.py` deadline/IPC/reaping; container resources | Verified locally |
| No browser artifact trust/selection/upload/download | `test_dashboard_analysis.py`, `test_dashboard_phase4.py`, registration/preflight tests | Verified locally |
| Preflight before deserialize/mismatch refusal | `test_workbench_model_pack.py`, `test_workbench_inference.py` | Verified locally |
| Artifact type/internal metadata binding | `test_workbench_inference.py` exact-buffer/type/runtime tests | Verified locally |
| Uncalibrated scores, no risk/confidence claims | Dashboard analysis/AppTest and notices | Verified locally |
| False positives only with ground truth | `test_workbench_review.py`, `test_dashboard_review_export.py` | Verified locally |
| Sequence/time language follows event_time | `test_workbench_analysis.py`, `test_dashboard_analysis.py` | Verified locally |
| No fabricated hosts/IPs/causality | Contracts, synthetic sample tests, attribution notices | Verified locally |
| Gated explanations/source mapping | Frozen accepted gate; `test_workbench_explanations.py`, `test_phase4_explanations.py`; original-pack integration separately below | Verified locally |
| Provenance and formula-safe JSON/CSV | `test_workbench_export.py`, `test_dashboard_review_export.py` | Verified locally |
| Safe non-realistic synthetic sample | `test_synthetic_sample.py`, `test_dashboard_phase4.py` | Verified locally |
| Unit/integration/Streamlit/Docker pass | Four unchanged CI jobs plus `container-packaging`; `scripts/verify_container.py` | Verified on Mac, native arm64 Docker and amd64 CI |
| Exact setup and honest current state | README, `container.md`, dashboard/resource docs, PROJECT_PLAN; independent review | Awaiting review |

## Verification record

Verified on 2026-10-04:

| Platform/environment | Passed | Skipped | Scope |
|---|---:|---:|---|
| macOS arm64, Python 3.12.14 base | 453 | 73 | Full suite; model/SHAP/Streamlit unavailable where expected |
| macOS arm64, reproduction lock | 508 | 18 | Full suite; no SHAP/Streamlit |
| macOS arm64, workbench lock | 520 | 13 | Full suite; no Streamlit |
| macOS arm64, dashboard lock | 614 | 0 | Full suite including original-pack synthetic explanations |
| Linux arm64, Docker Desktop native on Apple Silicon | 537 | 5 | Restricted workbench/dashboard suite with synthetic/test-only anchors |
| Linux arm64, original trusted pack/resources | 1 | 0 | Both actual isolated explanation tasks on committed synthetic foreground |
| Linux amd64 CI, Python 3.11 base | 452 | 74 | Full CI suite |
| Linux amd64 CI, reproduction environment | 506 | 20 | Full CI suite |
| Linux amd64 CI, workbench environment | 517 | 16 | Full CI suite |
| Linux amd64 CI, dashboard environment | 610 | 4 | Full CI suite; private original integrations absent |
| Linux amd64 CI, restricted container | 537 | 5 | Same context/runtime/read-only/health/stop/representative checks |
| macOS focused container profile/permissions | 22 | 0 | Narrow profile, launcher/probe and real permission failures |

All four host dependency checks, image dependency consistency/exact-lock probes,
`git diff --check`, frozen-file comparison, 106-file actual BuildKit context audit,
non-root/read-only probes, loopback publication, health and graceful shutdown
passed. No dataset/model/resource artifact or generated output is committed.
Host base skips: 53 pinned-model tests, 5 Phase 4 pinned-runtime tests, 2 SHAP
collection skips, 5 Streamlit collection/local-boundary skips and 8 new profile
cases needing Streamlit. Reproduction/workbench skips follow missing SHAP/Streamlit;
with the original resources supplied, dashboard has no skips. Container skips:
2 optional training-row integrations (training source not mounted), 1 optional
original-resource integration (tested separately), 1 case-insensitive filesystem
case and 1 Git-checkout assertion (neither Git nor private data enters the image).

Commands for the host matrix used `PYTHONPATH=src OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1`, the existing pinned environments, the verified local
training-copy binding for inherited Phase 3B regressions, and
`CIDS_PHASE4_ORIGINAL_RESOURCE_ID=985fb40fc3948cd139c3de2cd20bad041d546a8490ba805200e719ef53856941`.
The official-test foreground was never predicted, explained or scored. Frozen
configs, v2.0 results, gate JSON/checksums and the dataset manifest remain byte
unchanged relative to Phase 4.

The original registered pack `e2d4f329…2b18` was reused. No prepared CSV partitions
were available (the other local clone had split reports only), so the approved
CLI reconstructed frozen development partitions with the explicit
`--official-test-feature-reference --allow-test-feature-overlap` path and
`--prepare-global`. Source bytes were checksum verified; only test features
removed equivalent development observations, then were discarded. No test
IDs/targets or test prediction/explanation/scoring/tuning was used. Private
resource `985fb40f…6941` binds 256 prepared-training background rows/task and
separate global reliance on 256 prepared-validation rows/task, all 42 features,
3 repeats and seed 42. Resource outputs stay ignored/uncommitted.

The optional original-pack test passed on Mac and in Linux arm64 with the
existing private directories mounted read-only at controlled paths and UID/GID
501:20 matching their owner. Both actual workers explained `synthetic-0001`
after analysis of the eight committed synthetic rows. Both full source-feature
reconstruction/conservation checks passed. Both global bundles were validated
and loaded separately; no new benchmark was produced. Docker inspection
confirmed both bind mounts had `RW=false`; the documented CLI preflight passed.

## Browser checks and remaining gates

Chrome on macOS inspected the dark desktop analysis queue/selected record,
populated original binary and raw-family attribution views (including observed
values, signed contributions, baseline/output and correctness labels), both
separate global reliance tables and their development notices, and the prepared
JSON export view. Analysis and both explanation tasks also succeeded through the
restricted arm64 container UI. The browser connector file-upload permission was
disabled; the native macOS picker attached only the committed synthetic CSV,
without changing extension permissions. Broader theme/responsive/browser coverage
is not claimed. The real container missing-resource global view refused to load
and showed a fixed safe message. A temporary **test-only** loopback harness used
the existing sleeping synthetic worker with a 0.25-second deadline to inspect
the failed selected-explanation state. Analysis stayed visible and JSON export
remained preparable/downloadable. This harness was not packaged/committed, and
production's 60-second policy and trust anchors were unchanged. Worker termination/
reaping/IPC bounds are independently verified by the restricted-container suite.

All five jobs passed for implementation `45a6d7a6457497e893526f73136bdcf931e4466a`
in [Linux CI run 37193157065](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/actions/runs/37193157065),
including actual native `linux/amd64` image build/runtime qualification. The final
documentation head and its CI links are recorded in the review PR. Linux CI has
no private original model/resources; their actual integration was performed on
the maintainer's Mac and native arm64 Docker, not claimed on amd64.

Remaining release gate: **independent Phase 5 review and acceptance signoff**.
No known failing technical acceptance check remains. Other manifest architectures
are unqualified; broader theme/responsive/browser testing and original-artifact
integration on amd64 are not claimed. v2.1 is not release ready or published.

## Known product limitations

- Offline research workbench, not live IDS, production SOC system or calibrated
  threat detector. No capture/PCAP, flow extraction, authentication or remote hosting.
- Frozen v2.0 binary macro F1 **0.8663**, balanced accuracy **0.8595**, false-positive
  rate **0.2689**; multiclass macro F1 **0.5029**, balanced accuracy **0.5761**.
  Weak family performance/high false positives remain visible, not tuned away.
- Uploaded-sample labels support review only. Arbitrary uploads cannot prove data
  provenance; official-test uploads/tuning are prohibited. Scores are uncalibrated.
- Synthetic rows exercise mechanics, not realism/detection quality. Local
  attribution describes model influence, not causality. One-cycle permutation
  sampling/background choice and correlations limit interpretation. Global
  reliance is in-development, never held-out or uploaded-SHAP aggregation.
- Explicitly trusted pickle artifacts can execute code. Hashes establish identity,
  not safety. Read-only storage and dropped capabilities are deployment controls,
  not a sandbox for malicious trusted models. Session clear is not secure erasure.
- Application cannot prove host publication; operator must preserve loopback
  mapping. Health reports server availability, not populated-page correctness.
- Base digest/dependency versions are pinned; wheel hashes/offline wheelhouse are
  not provided. Other manifest architectures are unqualified without tests.
