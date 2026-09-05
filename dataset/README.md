# Dataset setup

This repository does not commit the KDD Cup traffic files. Download the original
files from the [UCI KDD Cup 1999 archive](https://kdd.ics.uci.edu/databases/kddcup99/kddcup99.html):

- `kddcup.data_10_percent.gz` — training baseline
- `corrected.gz` — held-out test data

Place both files in this directory. The loader reads the original headerless,
comma-separated gzip files directly, so no conversion or renaming is required.

KDD Cup 1999 is retained only to preserve and repair the original college project.
It should not be treated as representative of current production network traffic.
