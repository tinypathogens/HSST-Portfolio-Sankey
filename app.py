import pandas as pd
import streamlit as st
import plotly.graph_objects as go
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
filtered_evidence = evidence.copy()

if view_mode == "Focus on one EOA":
    if evidence.empty:
        st.sidebar.info("No EOAs available yet.")
    else:
        eoa_options = (
            evidence[["EOAID", "EOATitle"]]
            .drop_duplicates()
            .assign(Display=lambda x: x["EOAID"] + ": " + x["EOATitle"])
        )

        selected_eoa = st.sidebar.selectbox(
            "Select EOA",
            options=eoa_options["Display"].tolist()
        )

        selected_eoa_id = eoa_options.loc[
            eoa_options["Display"] == selected_eoa,
            "EOAID"
        ].iloc[0]

        filtered_evidence = evidence[
            evidence["EOAID"] == selected_eoa_id
        ]
        
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
# Build Sankey diagram
st.subheader("Portfolio Sankey Diagram")

if evidence.empty:
    st.info("Add evidence above to generate a Sankey diagram.")
else:
    curriculum_mappings = evidence[evidence["MappingType"] == "Curriculum"]
    sop_mappings = evidence[evidence["MappingType"] == "SoP"]

    links = []

    for _, row in curriculum_mappings.iterrows():
        source = row["TargetID"]
        target = f"{row['EOAID']}: {row['EOATitle']}"
        links.append((source, target, row["Weight"]))

    for _, row in sop_mappings.iterrows():
        source = f"{row['EOAID']}: {row['EOATitle']}"
        target = row["TargetID"]
        links.append((source, target, row["Weight"]))

    labels = list(pd.unique([item for link in links for item in link[:2]]))

    source_indices = [labels.index(link[0]) for link in links]
    target_indices = [labels.index(link[1]) for link in links]
    values = [link[2] for link in links]

    fig = go.Figure(
        data=[
            go.Sankey(
                node=dict(
                    pad=20,
                    thickness=18,
                    label=labels
                ),
                link=dict(
                    source=source_indices,
                    target=target_indices,
                    value=values
                )
            )
        ]
    )

    fig.update_layout(
        title_text="Curriculum → EOA → SoP Criterion",
        font_size=11,
        height=700
    )

    st.plotly_chart(fig, use_container_width=True)