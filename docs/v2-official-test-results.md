# v2.0 official-test results

Status: **Completed once and frozen**

The guarded `unsw-nb15-final-evaluation-v1` protocol evaluated the two selected
Histogram Gradient Boosting models on the immutable official UNSW-NB15 test
partition once. The run started at `2026-09-12T08:39:12.491417+00:00` and
completed at `2026-09-12T08:39:38.040864+00:00`.

The official results are evidence for this fixed baseline, not input for another
v2.0 tuning cycle.

## Integrity and provenance

| Item | SHA-256 |
|---|---|
| Experiment configuration | `070c009c139f41bcf34d63c7a5fa1324c819ded7a5884b800cc1bdbfb34234d2` |
| Frozen model selection | `c00c668f4032c9630802200add755359a6bf639c6be41471ab286a3b2299d027` |
| Clean reproduction selection | `90439d175f9be42c776673ffd35c3dff41bec35fbd419f4b5be3ce88c44bdc50` |
| Final protocol | `c4fc000d24d27cada9740c1350c3b1e22d710cbd537353f33c9036a980ccb517` |
| Official results file | `302f92c7dc83419959c6962fdfe3d5426bfb69aedab79fce8c3298b8b1dfbb9a` |
| Run-state file | `c74d217b83c61818aebdd0c4ba42a737529496da829f370795e8131c26f42574` |

The run used Python 3.12.14, scikit-learn 1.8.0, NumPy 2.3.5, pandas
2.2.3, joblib 1.5.3, seed `42`, and the exact dependency versions in
[`requirements-reproduction.txt`](../requirements-reproduction.txt). The test
file contained 82,332 records and matched the pinned dataset SHA-256
`734fe6642edf758f7c94d7d9149426b49d202fe8e7bf0bef47392489c3c0a559`.

Machine-readable evidence is preserved under [`results/v2.0`](../results/v2.0).

## Headline results

| Metric | Binary detection | Attack-family classification |
|---|---:|---:|
| Accuracy | 0.8725 | 0.6945 |
| Balanced accuracy | 0.8595 | 0.5761 |
| Macro precision | 0.8992 | 0.5623 |
| Macro recall | 0.8595 | 0.5761 |
| Macro F1 | 0.8663 | 0.5029 |
| Weighted F1 | 0.8692 | 0.7366 |
| False-positive rate | 0.2689 | 0.0331 macro one-vs-rest |
| False-negative rate | 0.0120 | 0.4239 macro one-vs-rest |
| ROC-AUC | 0.9850 | 0.8858 macro one-vs-rest |
| PR-AUC | 0.9888 | 0.5285 macro one-vs-rest |

Prediction timing on Arun's Mac was approximately 0.004 ms per binary record
and 0.018 ms per multiclass record. These figures exclude model loading,
preprocessing, and probability scoring and are not a production throughput
benchmark.

## Validation-to-test change

The comparison below uses the clean Apple Silicon validation reproduction, so
the validation and official-test figures were produced on the same platform and
dependency environment.

| Task | Metric | Validation | Official test | Change |
|---|---|---:|---:|---:|
| Binary | Macro F1 | 0.9333 | 0.8663 | -0.0670 |
| Binary | Balanced accuracy | 0.9340 | 0.8595 | -0.0744 |
| Binary | False-positive rate | 0.0861 | 0.2689 | +0.1829 |
| Multiclass | Macro F1 | 0.7450 | 0.5029 | -0.2421 |
| Multiclass | Balanced accuracy | 0.8122 | 0.5761 | -0.2361 |
| Multiclass | Macro false-positive rate | 0.0170 | 0.0331 | +0.0161 |

The held-out performance drop is evidence that the development and official-test
partitions do not behave identically. It is reported as a limitation, not used
to revise the frozen v2.0 models.

## Binary error analysis

The binary confusion matrix uses rows as actual classes and columns as predicted
classes:

| Actual class | Predicted normal | Predicted attack |
|---|---:|---:|
| Normal | 27,049 | 9,951 |
| Attack | 545 | 44,787 |

The detector found 98.80% of attacks, missing 545 of 45,332 attack records. Its
attack precision was 81.82%. The operational weakness is alert volume: 26.89%
of normal records were classified as attacks. That false-positive rate is too
high for an unattended production IDS and would create substantial analyst
noise.

## Attack-family error analysis

| Class | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| Analysis | 677 | 0.0000 | 0.0000 | 0.0000 |
| Backdoor | 583 | 0.5067 | 0.0652 | 0.1155 |
| DoS | 4,089 | 0.3478 | 0.2059 | 0.2587 |
| Exploits | 11,132 | 0.8095 | 0.5739 | 0.6716 |
| Fuzzers | 6,062 | 0.2246 | 0.8713 | 0.3571 |
| Generic | 18,871 | 0.9928 | 0.9748 | 0.9837 |
| Normal | 37,000 | 0.9873 | 0.6194 | 0.7612 |
| Reconnaissance | 3,496 | 0.8710 | 0.8398 | 0.8551 |
| Shellcode | 378 | 0.2167 | 0.9286 | 0.3514 |
| Worms | 44 | 0.6667 | 0.6818 | 0.6742 |

Accuracy and weighted F1 obscure important failures. The classifier did not
correctly identify any Analysis records and detected only 6.52% of Backdoor and
20.59% of DoS records. Fuzzers and Shellcode had high recall but low precision,
showing that the model over-predicted those labels. Generic and Reconnaissance
were the strongest attack-family results.

The confusion matrix indicates that Analysis, Backdoor, DoS, and many normal
records were frequently predicted as Fuzzers. This explains both the low recall
for those classes and the Fuzzers precision of 22.46%.

## Interpretation and limitations

- The binary model is a useful offline research baseline, but its 26.89%
  false-positive rate prevents a production-readiness claim.
- The multiclass model does not generalize reliably across all attack families.
  Its macro F1 of 0.5029 is more representative than its 0.6945 accuracy.
- The prepared development data was cleaned of official-test overlaps,
  target-conflicting feature groups, and redundant feature rows. The official
  test was kept immutable and still contains 28,386 redundant feature rows and
  575 multiclass-conflicting feature groups. This is a likely contributor to the
  observed shift, but the run does not prove a single causal explanation.
- UNSW-NB15 is a synthetic, dated research dataset. Results do not establish
  effectiveness on current organizational traffic.
- The project consumes prepared CSV flow records. It does not capture packets,
  inspect live traffic, block connections, or automate response.
- No threshold, feature, class weight, model, or hyperparameter may be changed in
  v2.0 based on these official-test results.

Any later model-improvement study must use a new versioned experiment with
development-only evaluation and a separately defined final-evaluation policy.
The v2.1 dashboard may present these frozen models for analysis and education,
but must retain their documented limitations.
