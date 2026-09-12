# UNSW-NB15 preprocessing contract

Preprocessor identifier: `unsw-nb15-preprocessor-v1`

The v2.0 baseline uses models based on decision trees. The preprocessing contract
therefore preserves all 39 numerical features in their original units and one-hot
encodes the three categorical features: `proto`, `service`, and `state`.

## Fit boundary

The preprocessor accepts a `PreparedSplits` object produced by
`unsw-nb15-split-v1` and fits only `PreparedSplits.train`, or a verified subset of
those rows for a model whose training scope is narrower. It verifies the source
training-ID SHA-256 and every supplied subset row before fitting. Validation and
official test records are transformed only after the categorical vocabulary is
fixed.

The supervised baselines use the complete prepared training partition. The
Isolation Forest baseline uses only its normal-labelled subset, so even its
categorical vocabulary is not learned from known attacks.

Unseen validation or test categories are accepted and encoded as all-zero values
for that categorical group. They never extend the training vocabulary.

## Deliberate choices

- Numerical features are not standardized because the planned Random Forest,
  gradient-boosted trees, and Isolation Forest baselines do not require scaling.
- Keeping original numerical units makes later analyst explanations easier to
  interpret.
- Missing values are not imputed. The versioned dataset schema rejects null and
  non-finite inputs before preprocessing.
- The `id`, `attack_cat`, and `label` columns are excluded from model features.
- Output feature names and their digest are stored with the fitted artifact.
- Categorical vocabulary sizes, source and selected training row counts, training
  scope, split policy, schema version, task, and ID digests are stored as
  provenance metadata.

## Serialization safety

Artifacts use joblib because they contain fitted scikit-learn objects. Joblib is
pickle-based and can execute code while loading. Only load artifacts produced by
this project in a trusted environment; never load an untrusted downloaded model
or preprocessor.

Generated artifacts belong under `artifacts/` and must not be committed.
