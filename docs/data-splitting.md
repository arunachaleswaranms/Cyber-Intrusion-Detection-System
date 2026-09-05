# UNSW-NB15 data-splitting policy

Policy identifier: `unsw-nb15-split-v1`

The official test partition is an immutable final holdout. It is validated and
reported but never deduplicated, relabelled, sampled, or used to choose model
settings.

For each binary or multiclass experiment, the preparation pipeline performs the
following ordered operations on the official training partition:

1. Remove every training row whose 42-feature vector also occurs in the official
   test partition.
2. Find identical feature vectors with different values for the selected task's
   target and remove every row in those ambiguous groups.
3. Collapse remaining identical feature vectors to one record, retaining the
   earliest source row.
4. Split each target class independently into training and validation partitions
   by a SHA-256 rank derived from the policy version, seed, target and source ID.
5. Sort each resulting partition by source ID and record its ID digest, counts and
   removal statistics.

The policy is target-aware. Two identical feature vectors assigned to different
attack families are ambiguous for multiclass training. If both are attacks, they
are not contradictory for binary training and can be collapsed after confirming
their binary labels agree.

## Why not randomly split the supplied training CSV directly?

The official files contain repeated feature vectors, cross-partition overlap and
feature-identical records with conflicting labels. A naive row-level random split
can place equivalent observations on both sides and inflate validation results.

The official files pinned in `dataset/unsw-nb15/manifest.json` produced these
pre-cleaning diagnostics:

| Diagnostic | Count |
|---|---:|
| Training rows | 175,341 |
| Official test rows | 82,332 |
| Training rows overlapping official-test features | 10,279 |
| Redundant feature rows in the unmodified training partition | 74,301 |
| Redundant feature rows in the unmodified official test partition | 28,386 |
| Multiclass-conflicting feature groups in unmodified training | 1,772 |
| Multiclass-conflicting feature groups in unmodified official test | 575 |

Because removal categories are applied in order, the generated report is the
authoritative record of task-specific removal counts. It must accompany every
benchmark result.

With policy version `unsw-nb15-split-v1`, seed `42`, and a 20% validation
fraction, the pinned files produce:

| Result | Binary | Multiclass |
|---|---:|---:|
| Training rows overlapping official test and removed | 10,279 | 10,279 |
| Conflicting target groups removed | 131 | 1,536 |
| Rows removed from conflicting groups | 429 | 28,292 |
| Remaining redundant feature rows removed | 65,026 | 38,568 |
| Prepared training rows | 79,686 | 78,562 |
| Prepared validation rows | 19,921 | 19,640 |
| Untouched official test rows | 82,332 | 82,332 |
| Conflicting target groups retained in official test | 6 | 575 |

## Generate split reports

```bash
PYTHONPATH=src python -m cids.datasets.split_unsw_nb15 \
  --data-dir dataset/unsw-nb15/raw \
  --task binary \
  --report artifacts/splits/binary.json

PYTHONPATH=src python -m cids.datasets.split_unsw_nb15 \
  --data-dir dataset/unsw-nb15/raw \
  --task multiclass \
  --report artifacts/splits/multiclass.json
```

Generated reports and datasets are local artifacts and must not be committed.
