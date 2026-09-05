# ADR 0001: Select the v2.0 primary dataset

- Status: Accepted
- Date: 2026-09-05
- Decision owners: Arunachaleswaran M S
- Applies to: v2.0 modern ML baseline

## Context

The repaired KDD Cup 1999 implementation is a historical learning baseline. v2.0
needs a more representative network-intrusion dataset that supports attack-family
classification, security-relevant evaluation, reproducible experiments, and a
credible path toward analyst-facing explanations.

The choice is intentionally limited to UNSW-NB15 and CICIDS2017. Selecting one
primary dataset prevents two incompatible feature schemas and preprocessing paths
from expanding the first v2.0 release.

Neither dataset represents 2026 production traffic. The word "modern" in this
project means a substantial improvement over KDD Cup 1999, not proof of current
production detection effectiveness.

## Decision criteria

The primary dataset should provide:

1. Officially documented labels and attack families.
2. A manageable reproducible starting point for a laptop-based project.
3. Enough class diversity to demonstrate false-positive and minority-class analysis.
4. A feature schema suitable for classical tree-based models and explanations.
5. A path to future raw-traffic or flow analysis without requiring that capability
   in v2.0.
6. Clear provenance from the institution that created the dataset.

## Options considered

| Criterion | UNSW-NB15 | CICIDS2017 |
|---|---|---|
| Published records/features | 2,540,044 records and 49 features | PCAPs plus labelled flow CSVs with more than 80 flow features |
| Attack coverage | Nine published attack families plus normal traffic | Benign traffic and several attack scenarios across five capture days |
| Prepared baseline | Official training and testing CSV partitions are available | Labelled machine-learning CSV files are available, commonly combined and repartitioned by researchers |
| Initial implementation effort | Lower | Medium to high because of multiple files/days, labels, and flow-processing decisions |
| Laptop-friendly first iteration | Better using the prepared partitions | Possible, but requires stricter sampling and ingestion design |
| Future PCAP relevance | Raw capture and supporting files are published | Strong; raw PCAP and flow CSV artifacts are central to the dataset |
| Main risk | Age, synthetic testbed traffic, imbalance, and rare classes | Age, imbalance, duplicate/label-quality concerns, and feature-extractor reproducibility |

## Decision

Use **UNSW-NB15 as the only primary dataset for v2.0**.

Start with the official prepared training and testing CSV files. Preserve the
official test partition as the final holdout. Create a deterministic validation
partition from the training data, with label-aware splitting and duplicate checks.

Support two related tasks from the same canonical labels:

1. Binary classification: `normal` versus `attack`.
2. Multiclass classification: normal plus the published attack families.

The multiclass mapping will be defined in a separate, tested schema before model
training is implemented.

CICIDS2017 is not rejected. Reconsider it after the v2.0 baseline is reproducible,
either as an external comparison or during the v3.0 PCAP/flow design. Results from
different schemas must not be presented as a direct model comparison unless the
experimental methodology makes that comparison valid.

## Consequences

### Benefits

- v2.0 can focus on methodology instead of building two ingestion systems.
- Official prepared partitions reduce setup friction and make reproduction easier.
- Nine attack families create meaningful minority-class and false-negative analysis.
- The feature count remains practical for tree models and SHAP-based work later.
- Binary and multiclass tasks can share one versioned label taxonomy.

### Trade-offs

- The traffic is still generated in a research testbed and is not current.
- Rare classes may produce unstable metrics and require careful reporting.
- Strong results cannot be generalized to live enterprise networks.
- A future PCAP pipeline may require a new feature contract or retraining.

## Required safeguards

- Do not commit or redistribute the dataset from this repository.
- Record source URLs, expected filenames, sizes, and checksums in a dataset manifest.
- Detect exact duplicates before splitting or training.
- Fit preprocessing and feature selection only on the training partition.
- Never tune against the official test partition.
- Report per-family support and metrics alongside aggregate metrics.
- Report false-positive and false-negative rates for the binary task.
- Document any class weighting, resampling, or removed records.
- Never claim the model is a deployable or real-time IDS based on this dataset.

## Revisit this decision if

- Official UNSW-NB15 files become unavailable or their permitted use changes.
- Feature or label quality prevents a reproducible baseline.
- The project requirement changes from offline analysis to a specific flow source.
- v3.0 selects a flow extractor whose schema cannot be reconciled with this model.

## Authoritative dataset references

- [UNSW-NB15 dataset — UNSW Research](https://research.unsw.edu.au/projects/unsw-nb15-dataset)
- [CICIDS2017 dataset — Canadian Institute for Cybersecurity](https://www.unb.ca/cic/datasets/ids-2017.html)
