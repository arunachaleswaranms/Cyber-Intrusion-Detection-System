# v2.1 trusted model-pack registration (Phase 3A)

Status: **Phase 3A registration and preflight implemented; Phase 3B verified
loading and inference implemented separately.**

Phase 3A adds one command-line action. It registers the maintainer's original
v2.0 final binary and multiclass artifacts into an app-controlled local model
pack, then preflights the result. It does not load a model, make a
prediction, accept an upload, or change the Streamlit dashboard. Verified
deserialization and inference are implemented in Phase 3B outside this CLI.

## Trust boundary

`.joblib` files are pickle-based. Loading one can execute arbitrary code, and
**a matching SHA-256 does not make an arbitrary pickle safe**. A hash shows
only that a file is the same file that was recorded earlier.

The Phase 3A trust model is:

1. The maintainer explicitly trusts a local source by running the CLI with the
   exact confirmation phrase. The browser can never make this decision.
2. Each source's SHA-256 must equal the selected-artifact digest recorded by
   the accepted, checksum-verified v2.1 explanation gate
   ([`results/v2.1/shap-gate-selected-v2.json`](../results/v2.1/shap-gate-selected-v2.json)).
   These are the artifacts that the maintainer created in the single v2.0
   official run and that the gate already examined.
3. The registrar copies those bytes into an app-controlled pack under fixed,
   app-owned filenames.
4. Phase 3B `load_model_pack()` runs `preflight_model_pack()` before any
   deserialization and checks the exact bounded bytes that it loads.
5. Phase 3B validates the deserialized object type, fitted state, and internal
   metadata against the manifest and frozen contracts. Registration itself
   remains free of deserialization.

Registration never deserializes either artifact. Tests run the registrar with
`joblib.load`, `pickle.load` and `pickle.loads` replaced by functions that
fail, and statically check that the registration and preflight modules
reference no deserializer or prediction call.

## Prerequisites

- The pinned model environment: Python `3.12.14` with
  [`requirements-workbench.txt`](../requirements-workbench.txt) (or the
  dashboard lock, which layers Streamlit on top of it without changing any
  model pin). The registrar refuses any other runtime.
- The two original final artifacts written by the guarded v2.0 official run.
  In the original working clone they are:

  ```text
  artifacts/v2/official-test-v1/binary-hist_gradient_boosting.joblib
  artifacts/v2/official-test-v1/multiclass-hist_gradient_boosting.joblib
  ```

These files are not committed and must never be rebuilt, reproduced, or
re-evaluated for this step. If they are lost, a `maintainer_final_v2` pack
cannot be registered. A later `development_demo_v1` builder is a separate,
not-yet-implemented path.

Before registering, you may compare the files with the digests the gate
recorded:

```bash
shasum -a 256 \
  artifacts/v2/official-test-v1/binary-hist_gradient_boosting.joblib \
  artifacts/v2/official-test-v1/multiclass-hist_gradient_boosting.joblib

python3 -c 'import json; r = json.load(open("results/v2.1/shap-gate-selected-v2.json")); print({t: v["artifact_sha256"] for t, v in r["tasks"].items()})'
```

The registrar does this comparison itself; it reads the expected digests only
from the gate report, after verifying that report's pinned checksum.

## Register on macOS

From the repository root, with the pinned environment active:

```bash
PYTHONPATH=src python -m cids.experiments.register_model_pack \
  --binary-artifact artifacts/v2/official-test-v1/binary-hist_gradient_boosting.joblib \
  --multiclass-artifact artifacts/v2/official-test-v1/multiclass-hist_gradient_boosting.joblib \
  --pack-root artifacts/v2.1/model-packs \
  --confirm REGISTER_TRUSTED_LOCAL_V2_MODEL_PACK
```

`--pack-root` defaults to `artifacts/v2.1/model-packs` under the repository and
may be omitted. If the artifacts live in another clone, pass their absolute
paths; source paths are never recorded in the pack.

On success the command prints `Model-pack registration: PASSED`, the
`model_pack_id`, both artifact digests and sizes, and confirms that preflight
passed without deserializing anything. Any refusal prints
`Model-pack registration: REFUSED` with the reason and exits with status 2.

### Maintainer registration record

On 2026-10-01 the original final artifacts were registered on the maintainer's
Apple Silicon Mac in the pinned Python 3.12.14 environment. The sources were
read from the original working clone, and the output went to the default
ignored pack root:

```text
Model-pack registration: PASSED
Model pack ID: e2d4f329b894a1b68b70af377ffc94441e02d024de27e7c351384d3e25692b18
binary: binary.joblib, 613790 bytes, sha256 4f0364cee99e05d595110ca29a51c0fb7f4c500527dfed426f115ebfc8a84482
multiclass: multiclass.joblib, 5484398 bytes, sha256 ea49309a6e20c448379deef8145bdb103fff59a8825b3d93747f4139fa142308
Trust anchor: matches the accepted v2.1 explanation-gate evidence
```

The separate preflight command then passed, and a second registration of the
same artifacts was refused. The pack itself stays local and uncommitted.

## What registration checks

In order, before anything is written:

1. The confirmation phrase matches exactly (case, spacing, and wording).
2. The registration policy
   [`configs/v2.1-model-pack-registration-v1.json`](../configs/v2.1-model-pack-registration-v1.json)
   matches its pinned canonical digest.
3. The host runtime equals the pinned model environment.
4. The gate evidence passes its pinned checksum and semantic validation.
5. Each source exists, is a regular file, is not a symlink, is not reached
   through a symlinked directory, and is 1 byte to 256 MiB.
6. The two inputs are not the same file (including hard links).
7. Each source's SHA-256 equals the gate's digest for that task.
8. The pack root is a real directory, is not a symlink, is not reached through
   a symlink, is not writable by group or other users, and lies under the
   ignored `artifacts/` directory when it is inside the repository.
9. The pack root holds no interrupted registration (`.registering-*`), no
   symlink, no unreadable or partial pack, and no pack already registering the
   same artifacts.

## Pack layout and manifest

```text
artifacts/v2.1/model-packs/
└── <model_pack_id>/          # 64-hex directory name equals the manifest ID
    ├── manifest.json         # read-only
    ├── binary.joblib         # read-only copy of the binary source
    └── multiclass.joblib     # read-only copy of the multiclass source
```

The manifest uses the existing Phase 1 schema `cids-trusted-model-pack-v1`;
no schema change was needed. It records:

| Field | Value |
|---|---|
| `provenance_type` | `maintainer_final_v2` |
| `created_at_utc`, `trust.acknowledged_at_utc` | Timezone-aware UTC ISO 8601 timestamps |
| `trust` | `acknowledged: true`, `method: explicit_local_cli` |
| `runtime` | The frozen Python and library versions |
| `contracts` | Frozen schema, preprocessor, experiment, selection and protocol versions and digests, and `unsw-nb15-final-supervised-v1` |
| `artifacts.<task>` | App-owned filename, exact SHA-256, and size in bytes |
| `creation_config_sha256` | Canonical digest of the registration policy (below) |
| `model_pack_id` | SHA-256 of the canonical (sorted-key, compact) JSON of every other manifest field |

Because `model_pack_id` covers the timestamps, registering the same artifacts
at a different time would produce a different ID. The registrar therefore
also refuses a second pack containing the same artifact digests.

### `creation_config_sha256`

This is the SHA-256 of the canonical JSON of
`configs/v2.1-model-pack-registration-v1.json`. The policy is versioned and
contains no host-specific paths. It fixes the confirmation phrase, the trust
method, the trust anchor (gate version and the gate report's pinned digest),
the default pack root, the app-owned filenames, the artifact size limit, and
the rule that registration must not deserialize. The code pins its digest
`2daeacfe…f533`, and preflight requires every `maintainer_final_v2` manifest to
record exactly that value. Changing any policy rule therefore requires a new
policy version, and packs made under the old policy fail closed.

## Atomic creation and failure behavior

1. Both sources are opened once, without following symlinks, and hashed.
2. A private staging directory `.registering-<random>` is created inside the
   pack root (same filesystem, mode `0700`).
3. The already-open sources are copied into it under the app-owned names. The
   bytes actually written are re-hashed, so a source changed after its first
   check is refused.
4. The manifest is written and the staging directory is preflighted.
5. The final name `<model_pack_id>` is claimed with an exclusive `mkdir`, and
   the staging directory is renamed onto that empty placeholder. An existing
   pack is never overwritten.
6. `preflight_model_pack()` runs on the finished pack before success is
   reported.

If any step fails, including a keyboard interrupt, the registrar removes only
the three files it creates and then removes its own staging directory with a
non-recursive `rmdir`. If anything unexpected is inside, that directory is
left in place and the error names it for manual inspection. If the final
preflight fails, the pack is renamed back to its staging name before cleanup.
After a hard crash, a leftover `.registering-*` directory is not named by a
pack ID, so it fails preflight and blocks the next registration until you
remove it.

## Inspect and preflight a registered pack

```bash
ls -l artifacts/v2.1/model-packs/
cat artifacts/v2.1/model-packs/<model_pack_id>/manifest.json

PYTHONPATH=src python -m cids.experiments.preflight_model_pack \
  --pack-dir artifacts/v2.1/model-packs/<model_pack_id>
```

Preflight verifies the following without deserializing: manifest schema, trust
acknowledgement, UTC timestamps, runtime, contracts, the directory name equal
to `model_pack_id`, the app-owned regular-file artifacts contained in the
pack, sizes, SHA-256 values, the pinned registration-policy digest, and (for
`maintainer_final_v2`) agreement with the checksum-verified gate evidence. It
prints `Model-pack preflight: PASSED` or exits with status 2.

## Version control

`artifacts/` is ignored by Git, so packs, staging directories, and `.joblib`
files are never committed. Tests assert this with `git check-ignore`. Before
committing anything, confirm with:

```bash
git status --short --ignored artifacts/
```

## Remove a local pack manually

The application never deletes a pack. To remove one, check the exact directory
first, then delete only that directory:

```bash
ls -l artifacts/v2.1/model-packs/<model_pack_id>
rm -rf artifacts/v2.1/model-packs/<model_pack_id>
```

The artifact and manifest files are read-only (`0444`), which is why `-f` is
needed. Remove an interrupted `.registering-*` directory the same way after
inspecting it. Never run this with an empty or wildcard ID.

## Phase 3B loading boundary

- `load_model_pack()` calls `preflight_model_pack()` immediately before loading.
- It reads each artifact into a bounded memory buffer, compares that buffer's
  byte count and SHA-256 with the preflighted manifest, then deserializes that
  same buffer. File replacement after preflight fails before deserialization.
- It validates exact final artifact types, task slots, fitted components, class
  order, parameters, runtime, and internal metadata. Both tasks must pass
  before a usable pack is returned.
- The service accepts only the accepted gate-anchored `maintainer_final_v2`
  artifacts. Hash agreement proves identity and does not make pickle safe.

## Not implemented by Phase 3A or 3B

- CSV upload, dashboard inference mode, or any dashboard change (3C)
- Review queue UI (3C), label-backed review, threshold simulation, or export (3D)
- Feature attribution and synthetic samples (Phase 4)
- `development_demo_v1` model building
- Docker (Phase 5)

## Residual risks

- A user can still deliberately trust a malicious local artifact. The gate
  anchor only narrows `maintainer_final_v2` to the two artifacts recorded by
  the accepted gate.
- Anyone who can edit the repository's code and committed evidence can change
  the anchor. The anchor guards against mistakes and later local tampering, not
  against a compromised checkout.
- Preflight checks only the manifest and the two app-owned artifact files. It
  ignores any extra file in a pack directory, because only those fixed names
  are ever read.
- The refusal message for a wrong confirmation names the expected phrase,
  matching the existing SHAP-gate CLI. The phrase records intent; it is not a
  secret.
- Sources and pack roots under macOS `/tmp` or `/var` are refused because
  those paths resolve through `/private`. Pass the resolved `/private/...`
  path.
- Python exposes no portable no-replace rename. The registrar instead claims
  the final name with an exclusive `mkdir` and renames onto its own empty
  placeholder. Another local process could only interfere by writing into
  that placeholder, which makes the rename fail closed.
