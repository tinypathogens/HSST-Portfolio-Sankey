import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="HSST Portfolio Sankey",
    layout="wide"
)

st.title("HSST Virology Portfolio Sankey")

st.write(
    "This tool maps Evidence of Activity (EOA) submissions between the NSHCS Virology curriculum and the Standards of Proficiency."
)

# Load data files
curriculum = pd.read_csv("data/curriculum.csv")
sop = pd.read_csv("data/sop.csv")
evidence = pd.read_csv("data/evidence.csv")

# Sidebar
st.sidebar.title("View options")

view_mode = st.sidebar.radio(
    "Choose view mode",
    [
        "Full portfolio",
        "Focus on one EOA",
        "Focus on one curriculum module",
        "Focus on one SoP domain",
        "Focus on one SoP criterion",
        "Show gaps"
    ]
)
# Add new evidence form
st.subheader("Add New Evidence")

with st.form("add_evidence_form"):
    eoa_id = st.text_input("EOA ID", placeholder="EOA1")
    eoa_title = st.text_input("EOA Title", placeholder="FRCPath Part 1 Pass")

    st.markdown("### Curriculum Modules")

    curriculum_options = {
        f"{row['CurriculumID']} - {row['CurriculumText']}": row["CurriculumID"]
        for _, row in curriculum.iterrows()
    }

    selected_curriculum_labels = st.multiselect(
        "Select curriculum modules",
        options=list(curriculum_options.keys())
    )

    st.markdown("### SoP Criteria")

    sop_options = {
        f"{row['SoPID']} - {row['SoPText']}": row["SoPID"]
        for _, row in sop.iterrows()
    }

    selected_sop_labels = st.multiselect(
        "Select SoP criteria",
        options=list(sop_options.keys())
    )

    submitted = st.form_submit_button("Save Evidence")

    if submitted:
        if not eoa_id or not eoa_title:
            st.error("Please enter both an EOA ID and an EOA title.")
        else:
            new_rows = []

            for label in selected_curriculum_labels:
                new_rows.append({
                    "EOAID": eoa_id,
                    "EOATitle": eoa_title,
                    "MappingType": "Curriculum",
                    "TargetID": curriculum_options[label],
                    "Weight": 1
                })

            for label in selected_sop_labels:
                new_rows.append({
                    "EOAID": eoa_id,
                    "EOATitle": eoa_title,
                    "MappingType": "SoP",
                    "TargetID": sop_options[label],
                    "Weight": 1
                })

            if new_rows:
                new_data = pd.DataFrame(new_rows)
                evidence = pd.concat([evidence, new_data], ignore_index=True)
                evidence.to_csv("data/evidence.csv", index=False)
                st.success(f"{eoa_id}: {eoa_title} saved successfully.")
                st.rerun()
            else:
                st.warning("Please select at least one curriculum module or SoP criterion.")
st.subheader("Data loaded")

col1, col2, col3 = st.columns(3)

col1.metric("Curriculum modules", len(curriculum))
col2.metric("SoP criteria", len(sop))
col3.metric("Evidence mappings", len(evidence))

if evidence.empty:
    st.info("No evidence has been mapped yet.")
else:
    st.dataframe(evidence, use_container_width=True)

st.subheader("Selected view mode")
st.write(view_mode)
