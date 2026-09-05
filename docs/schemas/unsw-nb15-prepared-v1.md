# UNSW-NB15 prepared schema v1

This contract applies to the official prepared training and testing CSV
partitions selected for v2.0 in
[ADR 0001](../decisions/0001-v2-primary-dataset.md).

Schema identifier: `unsw-nb15-prepared-v1`

## Column roles

| Role | Columns |
|---|---|
| Row identifier | `id` |
| Categorical model features | `proto`, `service`, `state` |
| Numerical model features | The remaining 39 feature columns defined in `src/cids/datasets/unsw_nb15.py` |
| Multiclass target | `attack_cat` |
| Binary target | `label` |

The prepared files contain 45 columns: one row identifier, 42 model features,
one attack-family target, and one binary target. The identifier is never a model
feature.

## Canonical attack families

| Canonical value | Binary label |
|---|---:|
| `normal` | 0 |
| `analysis` | 1 |
| `backdoor` | 1 |
| `dos` | 1 |
| `exploits` | 1 |
| `fuzzers` | 1 |
| `generic` | 1 |
| `reconnaissance` | 1 |
| `shellcode` | 1 |
| `worms` | 1 |

Values are trimmed and case-normalized. The published plural value `Backdoors`
is accepted as an alias of the canonical `backdoor`. Other unknown values fail
validation rather than silently creating a new class.

## Validation invariants

- All 45 expected columns must exist and no unrecognized columns are accepted.
- Column names must be unique.
- IDs must be present and unique within each partition.
- Categorical features must be non-null and non-empty.
- Numerical features must be numeric, non-null, and finite.
- The binary label must be `0` or `1`.
- `normal` must map to `0`; every attack family must map to `1`.
- Validation returns a new canonical frame and does not mutate input data.

These checks establish format integrity. Cross-partition duplicate detection and
train/validation/test isolation are separate safeguards and must run before model
training.
