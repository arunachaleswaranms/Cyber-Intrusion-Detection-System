"""Presentation of separately bound binary/family local explanation state."""
import pandas as pd
import streamlit as st
from cids.workbench.explanation_service import FAILURE_MESSAGE, UNAVAILABLE_MESSAGE


def render(session, resources, prefix):
    st.subheader("Explicit selected-record explanations")
    st.caption("One selected record per action. SHAP 0.52.0 PermutationExplainer • independent prepared-training background • one forward/reverse cycle • seed 42 • 60 seconds per task. No work occurs on navigation, filtering, simulation or export.")
    st.caption("Signed features influenced this model output. Raw decision units are separate from the uncalibrated probability-model scores above. Independent perturbations can produce implausible combinations of correlated features; one cycle provides limited sampling. Exports omit attribution data and retain the original analysis snapshot's explanation_status.")
    if resources is None:
        st.info(UNAVAILABLE_MESSAGE)
    else:
        with st.expander("Explanation background provenance and binding"):
            st.json({"resource_id": resources.resource_id, "model_pack_id": resources.manifest["model_pack_id"],
                     "policy_sha256": resources.manifest["policy_sha256"],
                     "tasks": {task: {key: entry[key] for key in ("provenance", "background", "background_sample_id_sha256")}
                               for task, entry in resources.manifest["tasks"].items()}})
    for task, title in (("binary", "Binary attack-class raw output"), ("multiclass", "Independent raw predicted family output")):
        st.markdown("**" + title + "**")
        if task == "binary":
            st.caption("The explained class is attack even when the original binary prediction is normal.")
        if st.button("Explain selected record — " + task, disabled=resources is None,
                     key=prefix + "explain_" + task):
            with st.spinner("Computing bounded explanation in an isolated worker…"):
                session.explain_selected(task, resources)
        state = session.explanation_status(task)
        st.caption("explanation_status: " + state + " · task: " + task)
        if state == "failed":
            st.warning(FAILURE_MESSAGE)
        value = session.explanations.get(task) if state == "available" else None
        if value is None:
            continue
        st.caption(f"Record sequence: {value.record_index + 1} · Input SHA-256: {value.input_sha256}")
        st.text("Record ID: " + value.record_id[:200])  # Uploaded identity is plain text, never Markdown.
        st.caption(f"Pack: {value.model_pack_id} · Resource: {value.resource_id} · Background SHA-256: {value.background_sha256} · Policy: {value.policy_sha256}")
        st.dataframe(pd.DataFrame([{"Explained class": value.explained_class,
                                  "Baseline output (raw decision units)": value.baseline_output,
                                  "Model output (raw decision units)": value.model_output}]), hide_index=True)
        st.dataframe(pd.DataFrame([{"Source feature": item.feature, "Observed value (max 200 characters)": item.observed_value,
                                  "Signed contribution (raw decision units)": item.contribution}
                                 for item in value.contributions]), hide_index=True)
        st.caption(f"All 42 source features shown; omitted contribution: 0. Baseline + full signed sum reconstructs output. Maximum independent additivity error: {value.max_additivity_error:.3g} (limit 1e-5); aggregation error: {value.max_aggregation_error:.3g} (limit 1e-10).")
