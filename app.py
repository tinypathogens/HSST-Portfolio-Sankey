import pandas as pd
import re
import streamlit as st
import plotly.graph_objects as go
from pathlib import Path

DATA_DIR = Path("data")
CURRICULUM_FILE = DATA_DIR / "curriculum.csv"
SOP_FILE = DATA_DIR / "sop.csv"
EVIDENCE_FILE = DATA_DIR / "evidence.csv"

st.set_page_config(page_title="HSST Virology Portfolio Sankey", layout="wide")
st.title("HSST Virology Portfolio Sankey")
st.write("Map evidence items to HSST Virology curriculum modules and SoP criteria.")


def load_csv(path, columns=None):
    if not path.exists():
        return pd.DataFrame(columns=columns) if columns is not None else pd.DataFrame()
    return pd.read_csv(path, dtype=str)


def natural_sort_key(value):
    parts = re.split(r"(\d+)", str(value))
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def safe_filename(text):
    text = str(text).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def load_data():
    curriculum = load_csv(CURRICULUM_FILE)
    sop = load_csv(SOP_FILE)
    evidence = load_csv(EVIDENCE_FILE)

    required_columns = ["EOAID", "EOATitle", "EvidenceType", "MappingType", "TargetID", "Weight"]
    for column in required_columns:
        if column not in evidence.columns:
            evidence[column] = pd.NA

    evidence = evidence[required_columns].copy()
    evidence["Weight"] = pd.to_numeric(evidence["Weight"], errors="coerce").fillna(1).astype(int)
    evidence["EvidenceType"] = evidence["EvidenceType"].fillna("Unspecified").astype(str)

    return curriculum, sop, evidence


def save_evidence(df):
    df.to_csv(EVIDENCE_FILE, index=False)


def build_sankey(evidence, curriculum, sop):
    if evidence.empty:
        return None, []

    curriculum_text = curriculum.set_index("CurriculumID")["CurriculumText"].to_dict()
    curriculum_ids = curriculum.set_index("CurriculumID").index.tolist()

    sop_text = sop.set_index("SoPID")["SoPText"].to_dict()
    sop_ids = sop.set_index("SoPID").index.tolist()

    evidence_titles = evidence.set_index("EOAID")["EOATitle"].to_dict()
    evidence_types = evidence.set_index("EOAID")["EvidenceType"].to_dict()

    links = []

    for _, row in evidence.iterrows():
        if row["MappingType"] == "Curriculum":
            source = row["TargetID"]
            target = row["EOAID"]
        elif row["MappingType"] == "SoP":
            source = row["EOAID"]
            target = row["TargetID"]
        else:
            continue

        links.append((source, target, row["Weight"]))

labels = list(dict.fromkeys([value for pair in links for value in pair[:2]]))

    node_info = []
    for label in labels:
        if label in curriculum_ids:
            node_info.append({
                "display": label,
                "type": "Curriculum",
                "description": curriculum_text.get(label, ""),
            })
        elif label in sop_ids:
            node_info.append({
                "display": label,
                "type": "SoP",
                "description": sop_text.get(label, ""),
            })
        else:
            node_info.append({
                "display": label,
                "type": "Evidence",
                "description": evidence_titles.get(label, ""),
                "evidence_type": evidence_types.get(label, ""),
            })

    order = {"Curriculum": 0, "Evidence": 1, "SoP": 2}
    node_info = sorted(
        node_info,
        key=lambda item: (order.get(item["type"], 9), natural_sort_key(item["display"]))
    )

    labels = [item["display"] for item in node_info]

    hover_text = []
    for item in node_info:
        if item["type"] == "Evidence":
            hover_text.append(
                f"<b>{item['display']}</b><br>"
                f"{item.get('description', '')}<br>"
                f"{item.get('evidence_type', '')}"
            )
        else:
            hover_text.append(f"<b>{item['display']}</b><br>{item['description']}")

    source_indices = [labels.index(link[0]) for link in links]
    target_indices = [labels.index(link[1]) for link in links]
    values = [link[2] for link in links]

    node_colors = []
    for item in node_info:
        if item["type"] == "Curriculum":
            node_colors.append("#1f77b4")
        elif item["type"] == "Evidence":
            node_colors.append("#ff7f0e")
        elif item["type"] == "SoP":
            node_colors.append("#2ca02c")
        else:
            node_colors.append("#7f7f7f")

    link_colors = ["rgba(160, 160, 160, 0.32)" for _ in links]

    figure = go.Figure(
        data=[
            go.Sankey(
                arrangement="snap",
                node=dict(
                    pad=22,
                    thickness=18,
                    label=labels,
                    color=node_colors,
                    customdata=hover_text,
                    hovertemplate="%{customdata}<extra></extra>",
                ),
                link=dict(
                    source=source_indices,
                    target=target_indices,
                    value=values,
                    color=link_colors,
                ),
            )
        ]
    )

    figure.update_layout(
        title_text="Curriculum → Evidence → SoP Criterion",
        font_size=11,
        height=1000,
        margin=dict(l=20, r=20, t=50, b=20),
    )

    return figure, node_info


def display_node_details(node_info, curriculum, sop):
    if not node_info:
        return

    curriculum_nodes = [node["display"] for node in node_info if node["type"] == "Curriculum"]
    sop_nodes = [node["display"] for node in node_info if node["type"] == "SoP"]

    curriculum_filtered = curriculum[curriculum["CurriculumID"].isin(curriculum_nodes)].copy()
    sop_filtered = sop[sop["SoPID"].isin(sop_nodes)].copy()

    curriculum_filtered = curriculum_filtered.sort_values("CurriculumID", ascending=True)
    sop_filtered["SoPID_numeric"] = pd.to_numeric(sop_filtered["SoPID"], errors="coerce")
    sop_filtered = sop_filtered.sort_values("SoPID_numeric", ascending=True).drop(columns=["SoPID_numeric"])

    st.markdown("#### Reference Tables")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Curriculum Modules**")
        if curriculum_filtered.empty:
            st.info("No curriculum modules in this view.")
        else:
            display_cols = ["CurriculumID", "CurriculumText", "Stage", "Status"]
            available_cols = [col for col in display_cols if col in curriculum_filtered.columns]
            st.dataframe(curriculum_filtered[available_cols], use_container_width=True, hide_index=True)

    with col2:
        st.markdown("**SoP Criteria**")
        if sop_filtered.empty:
            st.info("No SoP criteria in this view.")
        else:
            display_cols = ["SoPID", "SoPText", "StandardID", "DomainID"]
            available_cols = [col for col in display_cols if col in sop_filtered.columns]
            st.dataframe(sop_filtered[available_cols], use_container_width=True, hide_index=True)


def display_sankey_export_html(figure, view_title):
    st.markdown("#### Download Sankey Diagram")

    html = figure.to_html(
        include_plotlyjs="cdn",
        full_html=True,
        config={
            "displayModeBar": True,
            "responsive": True,
            "toImageButtonOptions": {
                "format": "png",
                "filename": safe_filename(f"sankey_{view_title}"),
                "height": 1200,
                "width": 1800,
                "scale": 2,
            },
        },
    )

    st.download_button(
        label="📥 Download interactive HTML",
        data=html,
        file_name=f"{safe_filename(f'sankey_{view_title}')}.html",
        mime="text/html",
        use_container_width=True,
    )

    st.caption("The HTML file preserves interactivity, hover labels, and the Plotly toolbar.")


def get_evidence_items(evidence):
    if evidence.empty:
        return []
    items = evidence[["EOAID", "EOATitle"]].drop_duplicates()
    items = items.sort_values("EOAID")
    return items["EOAID"].tolist()


def calculate_kpis(evidence, curriculum, sop):
    unique_evidence = evidence[["EOAID", "EOATitle"]].drop_duplicates()
    total_evidence_items = len(unique_evidence)

    curriculum_with_evidence = evidence[evidence["MappingType"] == "Curriculum"]["TargetID"].unique()
    curriculum_coverage = len(curriculum_with_evidence)
    curriculum_coverage_pct = round((curriculum_coverage / len(curriculum) * 100) if len(curriculum) > 0 else 0, 1)

    sop_with_evidence = evidence[evidence["MappingType"] == "SoP"]["TargetID"].unique()
    sop_coverage = len(sop_with_evidence)
    sop_coverage_pct = round((sop_coverage / len(sop) * 100) if len(sop) > 0 else 0, 1)

    total_mappings = len(evidence)

    return {
        "total_evidence": total_evidence_items,
        "curriculum_coverage": curriculum_coverage,
        "curriculum_coverage_pct": curriculum_coverage_pct,
        "sop_coverage": sop_coverage,
        "sop_coverage_pct": sop_coverage_pct,
        "total_mappings": total_mappings,
    }


def plot_evidence_type_breakdown(evidence):
    if evidence.empty:
        return None

    type_counts = (
        evidence[["EOAID", "EOATitle", "EvidenceType"]]
        .drop_duplicates()["EvidenceType"]
        .value_counts()
    )

    fig = go.Figure(
        data=[
            go.Bar(
                x=type_counts.index,
                y=type_counts.values,
                text=type_counts.values,
                textposition="auto",
            )
        ]
    )

    fig.update_layout(
        title="Evidence Type Breakdown",
        xaxis_title="Evidence Type",
        yaxis_title="Count",
        height=400,
        showlegend=False,
    )

    return fig


def plot_curriculum_coverage(evidence, curriculum):
    if evidence.empty or curriculum.empty:
        return None

    curriculum_mappings = (
        evidence[evidence["MappingType"] == "Curriculum"]
        .groupby("TargetID")["EOAID"]
        .nunique()
        .reset_index()
    )
    curriculum_mappings.columns = ["CurriculumID", "EvidenceCount"]
    curriculum_mappings = curriculum_mappings.sort_values("EvidenceCount", ascending=False)

    curriculum_text_map = curriculum.set_index("CurriculumID")["CurriculumText"].to_dict()

    def make_label(cid):
        text = curriculum_text_map.get(cid, "")
        truncated = text[:30] + "..." if len(text) > 30 else text
        return f"{cid}: {truncated}"

    curriculum_mappings["Label"] = curriculum_mappings["CurriculumID"].apply(make_label)

    fig = go.Figure(
        data=[
            go.Bar(
                y=curriculum_mappings["Label"],
                x=curriculum_mappings["EvidenceCount"],
                orientation="h",
                text=curriculum_mappings["EvidenceCount"],
                textposition="auto",
            )
        ]
    )

    fig.update_layout(
        title="Curriculum Coverage",
        xaxis_title="Number of Evidence Items",
        yaxis_title="Curriculum Module",
        height=600,
        showlegend=False,
    )

    return fig


def plot_sop_coverage(evidence, sop):
    if evidence.empty or sop.empty:
        return None

    sop_mappings = (
        evidence[evidence["MappingType"] == "SoP"]
        .groupby("TargetID")["EOAID"]
        .nunique()
        .reset_index()
    )
    sop_mappings.columns = ["SoPID", "EvidenceCount"]
    sop_mappings = sop_mappings.sort_values("EvidenceCount", ascending=False)

    sop_text_map = sop.set_index("SoPID")["SoPText"].to_dict()

    def make_label(sopid):
        text = sop_text_map.get(sopid, "")
        truncated = text[:30] + "..." if len(text) > 30 else text
        return f"{sopid}: {truncated}"

    sop_mappings["Label"] = sop_mappings["SoPID"].apply(make_label)

    fig = go.Figure(
        data=[
            go.Bar(
                y=sop_mappings["Label"],
                x=sop_mappings["EvidenceCount"],
                orientation="h",
                text=sop_mappings["EvidenceCount"],
                textposition="auto",
            )
        ]
    )

    fig.update_layout(
        title="SoP Coverage",
        xaxis_title="Number of Evidence Items",
        yaxis_title="SoP Criterion",
        height=600,
        showlegend=False,
    )

    return fig


def display_curriculum_gaps(curriculum, evidence):
    curriculum_with_evidence = evidence[evidence["MappingType"] == "Curriculum"]["TargetID"].unique()
    curriculum_gaps = curriculum[~curriculum["CurriculumID"].isin(curriculum_with_evidence)].copy()
    curriculum_gaps = curriculum_gaps.sort_values("CurriculumID", ascending=True)

    if curriculum_gaps.empty:
        st.success("✅ All curriculum modules are covered!")
    else:
        st.warning(f"⚠️ {len(curriculum_gaps)} curriculum module(s) with no evidence mappings:")
        display_cols = ["CurriculumID", "CurriculumText", "Stage", "Status"]
        available_cols = [col for col in display_cols if col in curriculum_gaps.columns]
        st.dataframe(curriculum_gaps[available_cols], use_container_width=True, hide_index=True)


def display_sop_gaps(sop, evidence):
    sop_with_evidence = evidence[evidence["MappingType"] == "SoP"]["TargetID"].unique()
    sop_gaps = sop[~sop["SoPID"].isin(sop_with_evidence)].copy()
    sop_gaps["SoPID_numeric"] = pd.to_numeric(sop_gaps["SoPID"], errors="coerce")
    sop_gaps = sop_gaps.sort_values("SoPID_numeric", ascending=True).drop(columns=["SoPID_numeric"])

    if sop_gaps.empty:
        st.success("✅ All SoP criteria are covered!")
    else:
        st.warning(f"⚠️ {len(sop_gaps)} SoP criterion/criteria with no evidence mappings:")
        display_cols = ["SoPID", "SoPText", "StandardID", "DomainID"]
        available_cols = [col for col in display_cols if col in sop_gaps.columns]
        st.dataframe(sop_gaps[available_cols], use_container_width=True, hide_index=True)


def display_top_evidence_items(evidence):
    if evidence.empty:
        return

    top_evidence = evidence.groupby(["EOAID", "EOATitle"]).size().reset_index(name="MappingCount")
    top_evidence = top_evidence.nlargest(10, "MappingCount")

    if top_evidence.empty:
        return

    st.subheader("Top 10 Most Reused Evidence Items")
    st.dataframe(top_evidence, use_container_width=True, hide_index=True)


def footer():

    st.sidebar.markdown("---")

    st.sidebar.caption("Created by James Griffiths | GitHub: tinypathogens")

curriculum, sop, evidence = load_data()

st.sidebar.markdown("### View Mode")
view_mode = st.sidebar.radio(
    "Select view",
    [
        "Full portfolio",
        "Focus on selected evidence item(s)",
        "Focus by evidence type",
        "Portfolio Dashboard",
        "Add evidence",
        "Delete evidence",
    ],
    label_visibility="collapsed",
)

if "generate_sankey" not in st.session_state:
    st.session_state.generate_sankey = False

if "selected_evidence_type_value" not in st.session_state:
    st.session_state.selected_evidence_type_value = "Evidence of Activity (EOA)"

selected_evidence = []
selected_evidence_type = st.session_state.selected_evidence_type_value

if view_mode == "Focus on selected evidence item(s)":
    st.sidebar.markdown("### Evidence Selection")
    evidence_ids = get_evidence_items(evidence)
    selected_evidence = st.sidebar.multiselect(
        "Select evidence items",
        options=evidence_ids,
        default=None,
    )

elif view_mode == "Focus by evidence type":
    st.sidebar.markdown("### Evidence Type")
    evidence_type_options = [
        "Evidence of Activity (EOA)",
        "Case-Based Discussion (CBD)",
        "Multi-Source Feedback (MSF)",
        "Training Plan Event",
    ]
    selected_evidence_type = st.sidebar.selectbox(
        "Select evidence type",
        options=evidence_type_options,
        index=evidence_type_options.index(st.session_state.selected_evidence_type_value)
        if st.session_state.selected_evidence_type_value in evidence_type_options
        else 0,
        label_visibility="collapsed",
    )
    st.session_state.selected_evidence_type_value = selected_evidence_type

if view_mode not in ["Portfolio Dashboard", "Add evidence", "Delete evidence"]:
    st.sidebar.markdown("---")
    if st.sidebar.button("Generate Sankey", use_container_width=True):
        st.session_state.generate_sankey = True

st.sidebar.markdown("---")

st.sidebar.markdown("### Portfolio Summary")

st.sidebar.metric("Curriculum modules", len(curriculum))

st.sidebar.metric("SoP criteria", len(sop))

st.sidebar.metric("Evidence mappings", len(evidence))

if view_mode == "Add evidence":
    st.subheader("New evidence entry")

    with st.form("add_evidence_form"):
        evidence_id = st.text_input("Evidence ID", placeholder="EOA1")
        evidence_type = st.selectbox(
            "Evidence Type",
            [
                "Evidence of Activity (EOA)",
                "Case-Based Discussion (CBD)",
                "Multi-Source Feedback (MSF)",
                "Training Plan Event",
            ],
        )
        evidence_title = st.text_input("Evidence Title", placeholder="FRCPath Part 1 Pass")

        st.markdown("#### Curriculum modules")
        curriculum_options = [
            f"{cid}: {ctext}"
            for cid, ctext in zip(curriculum["CurriculumID"], curriculum["CurriculumText"])
        ]
        selected_curriculum = st.multiselect("Choose curriculum modules", options=curriculum_options)

        st.markdown("#### SoP criteria")
        sop_options = [
            f"{sid}: {stext}"
            for sid, stext in zip(sop["SoPID"], sop["SoPText"])
        ]
        selected_sop = st.multiselect("Choose SoP criteria", options=sop_options)

        submitted = st.form_submit_button("Save evidence")

        if submitted:
            evidence_id = evidence_id.strip()
            evidence_title = evidence_title.strip()

            if not evidence_id or not evidence_title:
                st.error("Evidence ID and title are required.")
            elif not selected_curriculum and not selected_sop:
                st.warning("Select at least one curriculum module or SoP criterion.")
            else:
                new_rows = []

                for option in selected_curriculum:
                    curriculum_id = option.split(":")[0].strip()
                    new_rows.append(
                        {
                            "EOAID": evidence_id,
                            "EOATitle": evidence_title,
                            "EvidenceType": evidence_type,
                            "MappingType": "Curriculum",
                            "TargetID": curriculum_id,
                            "Weight": 1,
                        }
                    )

                for option in selected_sop:
                    sop_id = option.split(":")[0].strip()
                    new_rows.append(
                        {
                            "EOAID": evidence_id,
                            "EOATitle": evidence_title,
                            "EvidenceType": evidence_type,
                            "MappingType": "SoP",
                            "TargetID": sop_id,
                            "Weight": 1,
                        }
                    )

                evidence = pd.concat([evidence, pd.DataFrame(new_rows)], ignore_index=True)
                evidence = evidence.drop_duplicates()
                save_evidence(evidence)
                st.success(f"Saved evidence {evidence_id}: {evidence_title}")
                st.rerun()

elif view_mode == "Delete evidence":
    st.subheader("Delete evidence item")

    if not evidence.empty:
        evidence_items = evidence[["EOAID", "EOATitle"]].drop_duplicates().sort_values("EOAID")
        evidence_options = [
            f"{eoaid}: {title}"
            for eoaid, title in zip(evidence_items["EOAID"], evidence_items["EOATitle"])
        ]

        selected_delete = st.selectbox(
            "Select evidence item to delete",
            options=evidence_options,
            key="delete_selectbox",
        )

        if selected_delete:
            delete_eoaid = selected_delete.split(":")[0].strip()
            delete_title = selected_delete.split(":", 1)[1].strip()

            st.info(f"**Evidence to delete:** {delete_eoaid} — {delete_title}")

            confirm_delete = st.checkbox(
                "I understand this will remove all mappings for this evidence item.",
                key="delete_confirmation",
            )

            if st.button("Delete selected evidence", type="secondary"):
                if confirm_delete:
                    evidence = evidence[evidence["EOAID"] != delete_eoaid]
                    save_evidence(evidence)
                    st.success(f"Deleted evidence item {delete_eoaid}: {delete_title}")
                    st.rerun()
                else:
                    st.error("Please confirm before deleting.")
    else:
        st.info("No evidence items to delete.")

elif view_mode == "Portfolio Dashboard":
    st.markdown("# Portfolio Dashboard")

    if evidence.empty:
        st.info("No evidence mappings available yet. Create some evidence items to see the dashboard.")
    else:
        kpis = calculate_kpis(evidence, curriculum, sop)

        st.markdown("## Key Performance Indicators")
        kpi_cols = st.columns(6)

        with kpi_cols[0]:
            st.metric("Total Evidence Items", kpis["total_evidence"])
        with kpi_cols[1]:
            st.metric("Curriculum Coverage", f"{kpis['curriculum_coverage']} / {len(curriculum)}")
        with kpi_cols[2]:
            st.metric("Curriculum %", f"{kpis['curriculum_coverage_pct']}%")
        with kpi_cols[3]:
            st.metric("SoP Coverage", f"{kpis['sop_coverage']} / {len(sop)}")
        with kpi_cols[4]:
            st.metric("SoP %", f"{kpis['sop_coverage_pct']}%")
        with kpi_cols[5]:
            st.metric("Total Mappings", kpis["total_mappings"])

        st.markdown("## Coverage Analysis")

        evidence_type_fig = plot_evidence_type_breakdown(evidence)
        if evidence_type_fig:
            st.plotly_chart(evidence_type_fig, use_container_width=True)

        st.markdown("### Curriculum Module Coverage")
        curriculum_fig = plot_curriculum_coverage(evidence, curriculum)
        if curriculum_fig:
            st.plotly_chart(curriculum_fig, use_container_width=True)

        st.markdown("### SoP Criterion Coverage")
        sop_fig = plot_sop_coverage(evidence, sop)
        if sop_fig:
            st.plotly_chart(sop_fig, use_container_width=True)

        st.markdown("## Gap Analysis")
        gap_cols = st.columns(2)

        with gap_cols[0]:
            st.markdown("### Curriculum Gaps")
            display_curriculum_gaps(curriculum, evidence)

        with gap_cols[1]:
            st.markdown("### SoP Gaps")
            display_sop_gaps(sop, evidence)

        st.markdown("---")
        display_top_evidence_items(evidence)

elif st.session_state.generate_sankey:
    if view_mode == "Full portfolio":
        st.markdown("### Full Portfolio")

        if evidence.empty:
            st.info("No evidence mappings available yet.")
        else:
            sankey_fig, node_info = build_sankey(evidence, curriculum, sop)
            if sankey_fig is not None:
                st.plotly_chart(
                    sankey_fig,
                    use_container_width=True,
                    config={"displayModeBar": True},
                )
                display_sankey_export_html(sankey_fig, "Full Portfolio")
                st.markdown("---")
                display_node_details(node_info, curriculum, sop)

    elif view_mode == "Focus on selected evidence item(s)":
        if not selected_evidence:
            st.info("Please select one or more evidence items in the sidebar.")
        elif evidence.empty:
            st.info("No evidence mappings available yet.")
        else:
            filtered = evidence[evidence["EOAID"].isin(selected_evidence)]

            if filtered.empty:
                st.info("No mappings found for the selected evidence items.")
            else:
                st.markdown(f"### Selected Evidence: {', '.join(selected_evidence)}")
                sankey_fig, node_info = build_sankey(filtered, curriculum, sop)
                if sankey_fig is not None:
                    st.plotly_chart(
                        sankey_fig,
                        use_container_width=True,
                        config={"displayModeBar": True},
                    )
                    display_sankey_export_html(sankey_fig, "Selected Evidence")
                    st.markdown("---")
                    display_node_details(node_info, curriculum, sop)

    elif view_mode == "Focus by evidence type":
        filtered = evidence[evidence["EvidenceType"] == selected_evidence_type]

        if filtered.empty:
            st.warning(f"⚠️ No evidence items found for type: **{selected_evidence_type}**")
        else:
            st.markdown(f"### Evidence Type: {selected_evidence_type}")
            sankey_fig, node_info = build_sankey(filtered, curriculum, sop)
            if sankey_fig is not None:
                st.plotly_chart(
                    sankey_fig,
                    use_container_width=True,
                    config={"displayModeBar": True},
                )
                display_sankey_export_html(sankey_fig, selected_evidence_type)
                st.markdown("---")
                display_node_details(node_info, curriculum, sop)

else:
    st.info("Click **Generate Sankey** in the sidebar to visualize the mappings.")

footer()