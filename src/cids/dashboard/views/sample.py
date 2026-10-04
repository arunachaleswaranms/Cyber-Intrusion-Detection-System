"""Explicit synthetic demonstration preview/download, usable on a clean clone."""
import streamlit as st
from cids.workbench.synthetic_sample import load_sample


def render(repo_root):
    st.title("Synthetic feature sample")
    st.warning("Synthetic, non-sensitive and non-realistic. These eight arithmetic rows are not benchmark evidence and were not copied from official datasets.")
    st.markdown("No hosts, IP addresses, event timestamps or ground-truth labels are supplied. Inspect or download this contract-valid feature CSV, then upload it on **Local CSV analysis** and explicitly choose **Analyze CSV**. Predictions require a configured trusted model pack. Explanations additionally require verified CLI-prepared development backgrounds.")
    st.caption("The sample can demonstrate schema handling, independent model outputs and explanation mechanics. Its predictions cannot establish accuracy, attack realism, confidence, severity or operational risk.")
    try:
        data, frame = load_sample(repo_root)
    except Exception:
        st.error("The committed synthetic sample is unavailable or failed verification.")
        return
    if st.button("Preview synthetic sample"):
        st.dataframe(frame, hide_index=True)
    st.download_button("Download synthetic feature CSV", data, file_name="synthetic-features-v1.csv",
                       mime="text/csv", on_click="ignore")
