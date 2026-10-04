# Synthetic feature sample v1

`synthetic-features-v1.csv` is eight deterministic, **synthetic, non-sensitive,
non-realistic** rows. It is not benchmark evidence. No official dataset row was
copied. There are no hosts, IP addresses, timestamps or target labels. The IDs
begin with `synthetic-`; they identify rows, not network assets.

Generation: for row index `i = 0..7` and numeric feature index `j` in the schema,
the value is `((i + 1) * (j + 1)) % 17`. Override duration with `(i + 1) / 10`,
alternate protocol `tcp` / `udp`, use service `-` and state `FIN`, and set
`is_ftp_login` and `is_sm_ips_ports` to zero. These arbitrary arithmetic values
are contract-valid and deliberately do not model realistic traffic.

From the repository root, install `requirements-dashboard.txt` in Python
3.12.14 and run `streamlit run dashboard/app.py`. Choose **Synthetic feature
sample** to preview/download it without any model or dataset. For local analysis,
configure the original trusted pack through the existing CLI registration
workflow, set `CIDS_MODEL_PACK_ID`, restart, upload this CSV on **Local CSV
analysis**, and explicitly select **Analyze CSV**.

Predictions are unavailable without that pack. Explanations additionally require
CLI-prepared frozen development resources and `CIDS_EXPLANATION_RESOURCE_ID`;
see [preparation and limits](../docs/explanation-resources.md). Select one record
and explicitly request either binary or multiclass attribution. Nothing about
this sample establishes detection quality, attack realism, generalization,
causality, calibrated confidence, severity or operational risk. It can exercise
schema validation, independent outputs, signed contributions and failure states.
Exports retain the Phase 3D allowlist and omit observed features and attributions.
