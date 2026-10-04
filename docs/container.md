# Local container workflow

This image packages the offline, single-user research workbench. It has no
models, datasets, runtime resources, authentication or production IDS claim.
Registration and background/global-resource preparation remain explicit host CLI
operations; neither build nor ordinary startup performs them. Use Docker Engine
28+ / current Docker Desktop and Compose v2. The application runs non-root;
this does not imply the Docker daemon itself runs rootless.

## Base and build

```bash
docker buildx imagetools inspect python:3.12.14-slim-bookworm
docker compose build
```

On 2026-10-04 the official Python **3.12.14-slim-bookworm** registry index was
verified as `sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e`
and pinned in the Dockerfile. It lists linux/amd64, linux/arm64/v8, linux/arm/v7,
linux/386 and linux/ppc64le (plus attestations). This is manifest support, not
application qualification for every architecture. The workbench verification
scope is native Apple Silicon linux/arm64 and Linux CI linux/amd64; exact results
are in [release readiness](release-readiness-v2.1.md). No forced amd64 emulation
is needed on Apple Silicon. The complete existing dashboard/workbench/reproduction
pins are installed with pip 26.2.1; `requirements-container.txt` additionally
pins Linux-only Streamlit watchdog to 6.0.0. No existing pin or reproduction
environment is changed. The digest freezes base bytes; package index availability still
matters and requirements do not yet contain wheel hashes.

The context uses an explicit file allowlist in `.dockerignore`. New source/docs
files need a reviewed allowlist entry. Private files placed even inside source,
docs or results are excluded unless explicitly listed. Only the committed
UNSW-NB15 manifest is included, never raw dataset rows. Tests are mounted only by
the verification command and are absent from the runtime image. No Git history,
local environment, secrets, models, prepared resources, uploads or exports enter
the context/image. No image is published by this workflow or CI.

## Evidence and synthetic sample, without artifacts

From the repository root:

```bash
docker compose up -d --wait
curl --fail --max-time 5 http://127.0.0.1:8501/_stcore/health
docker compose ps
docker compose port workbench 8501
docker compose exec workbench python -m cids.dashboard.healthcheck
docker compose exec workbench python -m pip check
# Open http://127.0.0.1:8501; use Synthetic feature sample -> Preview synthetic sample.
docker compose down --timeout 15
```

Compose publishes **127.0.0.1:8501:8501**. Inside Docker the explicit
`python -m cids.dashboard.container` profile binds **0.0.0.0:8501**, because
container loopback cannot receive published-port traffic. The runtime exposure
guard permits only this exact address with `CIDS_LAUNCH_PROFILE=container-v1`, a
Docker marker and non-root execution. Ordinary host execution still refuses
non-loopback binding; telemetry must always be disabled. The profile is explicit
deployment intent, not authentication or proof of host mapping. The application
cannot independently inspect Docker's host-side publication. Host publication,
Docker daemon/network configuration and avoiding untrusted peers on the container
network control exposure. Do not use host networking, remote publication or a
shared/untrusted container network. See [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/).

The filesystem is read-only, with only a bounded 128 MiB `/tmp` tmpfs for runtime
home/cache/JIT needs. It is ephemeral, noexec/nosuid/nodev. All capabilities are
dropped; no-new-privileges, init/reaping, 2 CPUs, 2 GiB memory and 128 process
limits apply. Stop grants 15 seconds for graceful shutdown. Neither privileged
mode nor a Docker socket mount is used. Session uploads, prepared downloads and
explanation IPC stay in memory; tmpfs permits library runtime cache, not an
application data store. Clearing references is **not secure erasure**. Memory,
CPU and worker deadlines bound work; they do not guarantee latency on every host.
Streamlit usage telemetry and built-in dataframe download/copy remain disabled.
The health check uses Python's standard library, a 3-second local HTTP timeout,
16-byte read and fixed `ok` response; Docker bounds it to 5 seconds with three
retries. It verifies the server, not populated pages or trusted artifacts.

## Trusted local analysis

First use [model registration](model-pack-registration.md) on the host in the
pinned Python 3.12.14 environment. Models are executable trusted pickle inputs;
a hash does not establish safety. Never trust an unknown artifact. Set IDs and
absolute, non-symlink directories **outside the browser**:

```bash
export CIDS_MODEL_PACK_ID="<registered-64-hex-pack-id>"
export CIDS_PACK_DIR="$PWD/artifacts/v2.1/model-packs/$CIDS_MODEL_PACK_ID"
# Match the existing private files' owner. Never set CIDS_UID=0.
export CIDS_UID="$(id -u)" CIDS_GID="$(id -g)"
docker compose -f compose.yaml -f compose.analysis.yaml config
docker compose -f compose.yaml -f compose.analysis.yaml up -d --wait
# Open Local CSV analysis, upload only permitted non-benchmark feature CSVs,
# then explicitly Analyze CSV.
docker compose -f compose.yaml -f compose.analysis.yaml down --timeout 15
```

Each selected pack directory is mounted read-only at the existing app-controlled
`/app/artifacts/v2.1/model-packs/<id>`. Missing host directories fail before
startup (`create_host_path: false`); missing/tampered/incompatible/unreadable
contents produce safe unavailable states. Runtime IDs never permit arbitrary
browser paths or model uploads. Changing bindings requires a restart.

On native Linux, `CIDS_UID`/`CIDS_GID` must have read/traverse access to the mounted
private directory and read access to every file (registration uses private
permissions). Docker Desktop file sharing may translate host ownership, so verify
access with the command below. Preserve private permissions; use the matching
nonzero owner UID, or an administrator-approved narrow read ACL/private group
with directory traversal and file read access. Do not use world-writable files,
`chmod -R 777`, root execution, or copy artifacts into the image. Read-only mounts
prevent writes even when their owner runs the application. User namespace/rootless
remapping may require an appropriate mapped owner/ACL. An unreadable resource
remains unavailable until the host owner corrects access.

```bash
docker compose -f compose.yaml -f compose.analysis.yaml exec workbench \
  python -m cids.experiments.preflight_model_pack \
  --pack-dir "/app/artifacts/v2.1/model-packs/$CIDS_MODEL_PACK_ID"
```

## Local explanations and separate global reliance

Prefer verified prepared development partitions. If absent, only the explicitly
approved feature-only overlap-removal reconstruction may be used. Follow
[resource CLI preparation](explanation-resources.md#cli-preparation), adding
`--prepare-global` for the separate development permutation evidence. This is a
host CLI action, never container startup/browser work. It does not rerun the
official test or score/explain its rows. Keep the private generated resources
uncommitted and apply the same non-root read/traverse policy as packs.

```bash
export CIDS_EXPLANATION_RESOURCE_ID="<printed-64-hex-resource-id>"
export CIDS_RESOURCE_DIR="$PWD/artifacts/v2.1/explanation-resources/$CIDS_EXPLANATION_RESOURCE_ID"
docker compose -f compose.yaml -f compose.analysis.yaml -f compose.explanations.yaml config
docker compose -f compose.yaml -f compose.analysis.yaml -f compose.explanations.yaml up -d --wait
# Analyze the committed synthetic CSV, select one record, and explicitly request
# binary and raw-family explanations. Explainability -> Load configured global
# model reliance loads separately prepared development evidence.
docker compose -f compose.yaml -f compose.analysis.yaml -f compose.explanations.yaml down --timeout 15
```

Resources mount read-only at `/app/artifacts/v2.1/explanation-resources/<id>`.
They require the same pack/runtime/policy/provenance binding. Global reliance is
in-development because final models used train plus validation, not a held-out
benchmark or causal statement. A timeout kills/reaps its dedicated worker and
leaves existing analysis usable; a slow cold startup can exceed the 60-second
budget. A container OOM can kill the whole process and is a different limit.

## Repeatable verification

```bash
python3 scripts/verify_container.py
# Optional original-model check (only committed synthetic foreground):
CIDS_PHASE4_ORIGINAL_RESOURCE_ID="$CIDS_EXPLANATION_RESOURCE_ID" \
  PYTHONPATH=src python -m pytest -q -rs \
  tests/test_phase4_explanations.py::test_optional_original_pack_explains_synthetic_sample_only
```

The verifier builds/audits the actual filtered context, builds the image, checks
exact installed lock versions, runtime identity and read-only operation, runs the
workbench/dashboard suite under restricted non-root Docker with synthetic/test-only anchors,
then checks Compose publication, healthy startup and graceful stop. It never
mounts private host datasets/models/resources. Original trusted-resource and
browser gates are reported separately from representative tests.
