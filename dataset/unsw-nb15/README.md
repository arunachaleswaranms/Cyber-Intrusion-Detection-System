# UNSW-NB15 prepared partitions

The dataset is not distributed in this repository. Download the prepared files
from the [official UNSW-NB15 page](https://research.unsw.edu.au/projects/unsw-nb15-dataset):

1. Open the source-files link on the official page.
2. Open `CSV Files/Training and Testing Sets`.
3. Download `UNSW_NB15_training-set.csv` and `UNSW_NB15_testing-set.csv`.
4. Place both files in `dataset/unsw-nb15/raw/`.

Verify both files before using them:

```bash
PYTHONPATH=src python -m cids.datasets.verify_manifest \
  --data-dir dataset/unsw-nb15/raw
```

The committed `manifest.json` pins the official filenames, byte sizes, record
counts, schema width, and SHA-256 hashes verified on 2026-09-05. Verification
fails closed if a file is missing, renamed, truncated, modified, or structurally
incompatible with the versioned schema.

Do not commit the downloaded CSV files.
