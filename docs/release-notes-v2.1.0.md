# CIDS v2.1.0 release notes

CIDS v2.1 adds a local analyst workbench around the frozen v2.0 research evidence.
**Published as stable v2.1.0 on 2026-10-04.** Phases 1–5 are implemented,
reviewed and merged; independent Phase 5 review found no blocking issues.
Implementation acceptance and verification scope are recorded in [release readiness](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/blob/main/docs/release-readiness-v2.1.md).
[v2.1.0](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/releases/tag/v2.1.0) was published as a stable GitHub Release on
2026-10-04 at `ed2e38a9014ee52756276bb0707d0de09ea3df35`. Release closure
[PR #8](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/pull/8) is merged; all five closure
post-merge jobs passed in [run 37207887388](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/actions/runs/37207887388).
The project is paused for maintenance; no next-version implementation is authorized.

- Evidence dashboard derives metrics, exact tables, family weaknesses and
  provenance from checksum-verified committed results; no dataset/model needed.
- Trusted CLI-registered model packs support bounded 42-feature CSV analysis,
  independent binary/family outputs, research queue and label-backed review.
  Scores are explicitly uncalibrated; missing truth creates no false positives.
- Temporary uploaded-sample threshold simulation preserves original predictions
  and frozen bands. Explicit session-only JSON/CSV export carries provenance,
  excludes raw features/artifacts and neutralizes spreadsheet formulas.
- Explicit bounded binary/raw-family explanations use verified prepared
  development backgrounds, isolated workers, deadlines and source-feature checks.
  Separately prepared global reliance is in-development, not a held-out metric.
  The arithmetic synthetic sample is non-sensitive and non-realistic.
- Local Docker packaging pins Python 3.12.14 and existing dashboard dependencies,
  runs non-root with loopback host publication, read-only filesystem/artifact
  mounts, ephemeral tmpfs and bounded resources. Registration/preparation stay
  outside normal startup and the browser. Tested on macOS arm64 host, native
  Linux arm64 Docker Desktop and native Linux amd64 CI. Original trusted-artifact
  integration ran on macOS/arm64 Docker; amd64 container checks used representative
  synthetic artifacts. No image is published.

Frozen v2.0 results are unchanged: binary macro F1 0.8663, balanced accuracy
0.8595 and FPR 0.2689; multiclass macro F1 0.5029 and balanced accuracy 0.5761.
False positives and weak family generalization remain limitations. No official
test rerun, benchmark tuning, retraining or calibration occurred.

This remains an offline research workbench, not a live IDS, production SOC system
or calibrated threat detector. No live capture/PCAP, remote hosting, multi-user
authentication or operational response is supplied. Attributions are model
influence, not causality; synthetic outputs prove no detection quality. Explicit
trust of executable model files remains necessary. Clearing session references
is not secure erasure. Broader theme/responsive/browser coverage, other manifest
architectures and original-artifact integration on amd64 remain unqualified. See
the acceptance record for exact verification results and the
[maintainer handoff](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/blob/main/docs/release-handoff-v2.1.0.md) for the completed publication record and historical procedure.
