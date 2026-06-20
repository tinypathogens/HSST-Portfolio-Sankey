import json
import pandas as pd
import re
from io import BytesIO
from pathlib import Path
import streamlit as st
import plotly.graph_objects as go
import storage


def apply_visual_style():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700;800&display=swap');

        html, body, [class*="css"]  {
            font-family: 'Source Sans 3', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }

        .main .block-container {
            max-width: 1080px;
            padding-top: 2.2rem;
            padding-left: 3.2rem;
            padding-right: 2.4rem;
        }

        h1 {
            color: #0a1428;
            font-size: 3.85rem;
            font-weight: 800;
            letter-spacing: 0.2px;
            margin-bottom: 0.35rem;
        }

        .main p {
            color: #4d5a6a;
            font-size: 1.14rem;
            line-height: 1.45;
        }

        hr.hero-divider {
            border: none;
            border-top: 1px solid #d4dae3;
            margin: 1.15rem 0 1.35rem 0;
        }

        div[data-testid="stAlert"] {
            background: #f4f7fb;
            border: 1px solid #dbe2ed;
            border-radius: 8px;
            color: #4d5a6a;
            padding-top: 0.35rem;
            padding-bottom: 0.35rem;
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #f6f8fb 0%, #f3f5f8 100%);
            border-right: 1px solid #d9e0ea;
        }

        section[data-testid="stSidebar"] .block-container {
            padding-top: 1.5rem;
            padding-left: 1.1rem;
            padding-right: 1.1rem;
        }

        section[data-testid="stSidebar"] h3 {
            margin-top: 0.2rem;
            margin-bottom: 0.45rem;
            color: #0f172a;
            font-weight: 700;
        }

        section[data-testid="stSidebar"] hr {
            border: none;
            border-top: 1px solid #d5dce7;
            margin: 0.85rem 0 0.95rem 0;
        }

        section[data-testid="stSidebar"] .stRadio > div {
            gap: 0.35rem;
        }

        section[data-testid="stSidebar"] .stRadio label {
            border-radius: 9px;
            border: 1px solid transparent;
            padding: 0.56rem 0.72rem;
            margin: 0;
            transition: background-color 120ms ease, border-color 120ms ease;
        }

        section[data-testid="stSidebar"] .stRadio label:hover {
            background: #eef3fa;
            border-color: #dbe6f5;
        }

        section[data-testid="stSidebar"] .stRadio label:has(input:checked) {
            background: #e8f0fb;
            border-color: #cdddf5;
            color: #005eb8;
            font-weight: 700;
        }

        section[data-testid="stSidebar"] .stDownloadButton button,
        section[data-testid="stSidebar"] .stButton button {
            border-radius: 8px;
            min-height: 2.45rem;
            font-weight: 600;
        }

        section[data-testid="stSidebar"] .stMetric {
            padding-top: 0.2rem;
            padding-bottom: 0.2rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="HSST Virology Portfolio Sankey", layout="wide")
apply_visual_style()
st.title("HSST Portfolio Mapper")
st.write("Map evidence items to HSST curriculum modules and SoP criteria.")
st.markdown("<hr class='hero-divider' />", unsafe_allow_html=True)
st.info("Evidence is stored locally on this computer. Nothing is uploaded online unless you choose to share it.")

storage.initialize_database()
specialty_registry = storage.load_specialty_registry_dataframe()
if specialty_registry.empty:
    specialty_registry = storage.refresh_specialty_registry_from_nshcs()

if "selected_specialty_code" not in st.session_state:
    if not specialty_registry.empty and storage.DEFAULT_SPECIALTY_CODE in set(specialty_registry["CurriculumCode"]):
        st.session_state.selected_specialty_code = storage.DEFAULT_SPECIALTY_CODE
    elif not specialty_registry.empty:
        st.session_state.selected_specialty_code = specialty_registry.iloc[0]["CurriculumCode"]
    else:
        st.session_state.selected_specialty_code = storage.DEFAULT_SPECIALTY_CODE

evidence = storage.load_evidence_dataframe(st.session_state.selected_specialty_code)

st.sidebar.markdown(
    """
    <div style="color:#005EB8; font-weight:700; text-align:left; line-height:1.2; margin-bottom:0.25rem; font-size:2.15rem;">
        National School<br>of Healthcare Science
    </div>
    <hr style="border:none; border-top:1px solid #005EB8; margin:0.25rem 0 0.9rem 0;" />
    """,
    unsafe_allow_html=True,
)


def natural_sort_key(value):
    parts = re.split(r"(\d+)", str(value))
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def safe_filename(text):
    text = str(text).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def dataframe_csv_bytes(frame):
    return frame.to_csv(index=False).encode("utf-8")


def dataframe_excel_bytes(curriculum_code):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        storage.load_evidence_items_dataframe(curriculum_code).to_excel(writer, sheet_name="Evidence Items", index=False)
        storage.load_evidence_dataframe(curriculum_code).to_excel(writer, sheet_name="Evidence Mappings", index=False)
        storage.load_curriculum_dataframe(curriculum_code).to_excel(writer, sheet_name="Curriculum", index=False)
        storage.load_sop_dataframe().to_excel(writer, sheet_name="SoP Criteria", index=False)
    output.seek(0)
    return output.getvalue()


def display_import_summary(summary):
    imported_items = int(summary.get("imported_items", 0) or 0)
    skipped_items = int(summary.get("skipped_items", 0) or 0)
    skipped_examples = summary.get("skipped_examples", []) or []

    st.markdown(
        f"Imported items: **{imported_items}**  \nSkipped items: **{skipped_items}**"
    )

    if skipped_examples:
        st.caption("Skipped examples: " + "; ".join(str(example) for example in skipped_examples[:5]))


def load_data(curriculum_code):
    curriculum = storage.load_curriculum_dataframe(curriculum_code)
    sop = storage.load_sop_dataframe()
    evidence = storage.load_evidence_dataframe(curriculum_code)
    return curriculum, sop, evidence


def calculate_portfolio_summary(curriculum, sop, evidence, evidence_items):
    mapped_evidence_ids = set(evidence["EOAID"].dropna().astype(str).tolist()) if not evidence.empty else set()
    total_evidence_items = len(evidence_items["EOAID"].dropna().astype(str).unique()) if not evidence_items.empty else 0

    mapped_curriculum_modules = len(
        evidence[evidence["MappingType"] == "Curriculum"]["TargetID"].dropna().astype(str).unique()
    ) if not evidence.empty else 0

    sop_domain_lookup = sop.set_index("SoPID")["DomainID"].to_dict() if not sop.empty else {}
    mapped_sop_domains = {
        sop_domain_lookup.get(str(target_id), "")
        for target_id in evidence[evidence["MappingType"] == "SoP"]["TargetID"].dropna().astype(str).tolist()
    } if not evidence.empty else set()
    mapped_sop_domains = {domain for domain in mapped_sop_domains if domain}

    unmapped_evidence_items = max(total_evidence_items - len(mapped_evidence_ids), 0)
    curriculum_total = len(curriculum)
    curriculum_coverage_pct = round((mapped_curriculum_modules / curriculum_total * 100), 1) if curriculum_total else 0.0

    return {
        "total_evidence_items": total_evidence_items,
        "mapped_curriculum_modules": mapped_curriculum_modules,
        "mapped_sop_domains": len(mapped_sop_domains),
        "unmapped_evidence_items": unmapped_evidence_items,
        "curriculum_coverage_pct": curriculum_coverage_pct,
    }


def prepare_sankey_data(evidence, curriculum, sop, selected_evidence_ids=None, selected_curriculum_code=None):
    debug_summary = {
        "selected_evidence_count": 0,
        "curriculum_links_count": 0,
        "sop_links_count": 0,
        "unique_curriculum_nodes": 0,
        "unique_sop_nodes": 0,
    }

    if evidence.empty:
        return [], [], debug_summary, {}, {}

    filtered = evidence.copy()
    for column in ["EOAID", "EOATitle", "EvidenceType", "MappingType", "TargetID"]:
        if column in filtered.columns:
            filtered[column] = filtered[column].fillna("").astype(str).str.strip()

    selected_ids = set()
    if selected_evidence_ids:
        selected_ids = {str(item).strip() for item in selected_evidence_ids if str(item).strip()}
        filtered = filtered[filtered["EOAID"].isin(selected_ids)].copy()
        debug_summary["selected_evidence_count"] = len(selected_ids)
    else:
        debug_summary["selected_evidence_count"] = filtered["EOAID"].nunique()

    if selected_curriculum_code and "CurriculumCode" in filtered.columns:
        target_code = str(selected_curriculum_code).strip()
        filtered = filtered[filtered["CurriculumCode"].fillna("").astype(str).str.strip() == target_code].copy()

    curriculum_ids = set(curriculum["CurriculumID"].fillna("").astype(str).tolist()) if not curriculum.empty else set()
    sop_ids = set(sop["SoPID"].fillna("").astype(str).tolist()) if not sop.empty else set()

    curriculum_links = filtered[
        (filtered["MappingType"] == "Curriculum")
        & filtered["TargetID"].isin(curriculum_ids)
        & filtered["TargetID"].map(storage.is_valid_module_code)
    ].copy()

    sop_links = filtered[
        (filtered["MappingType"] == "SoP")
        & filtered["TargetID"].isin(sop_ids)
    ].copy()

    debug_summary["curriculum_links_count"] = len(curriculum_links)
    debug_summary["sop_links_count"] = len(sop_links)
    debug_summary["unique_curriculum_nodes"] = curriculum_links["TargetID"].nunique() if not curriculum_links.empty else 0
    debug_summary["unique_sop_nodes"] = sop_links["TargetID"].nunique() if not sop_links.empty else 0

    filtered = pd.concat([curriculum_links, sop_links], ignore_index=True)
    if filtered.empty:
        return [], [], debug_summary, {}, {}

    curriculum_text = curriculum.set_index("CurriculumID")["CurriculumText"].to_dict()
    curriculum_ids = curriculum.set_index("CurriculumID").index.tolist()

    sop_text = sop.set_index("SoPID")["SoPText"].to_dict()
    sop_ids = sop.set_index("SoPID").index.tolist()

    evidence_titles = filtered.set_index("EOAID")["EOATitle"].to_dict()
    evidence_types = filtered.set_index("EOAID")["EvidenceType"].to_dict()

    links = []

    for _, row in filtered.iterrows():
        if row["MappingType"] == "Curriculum":
            source = row["TargetID"]
            target = row["EOAID"]
        elif row["MappingType"] == "SoP":
            source = row["EOAID"]
            target = row["TargetID"]
        else:
            continue

        links.append((source, target, row["Weight"]))

    if not links:
        return [], [], debug_summary, {}, {}

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

    return links, node_info, debug_summary, evidence_titles, evidence_types


def build_sankey(evidence, curriculum, sop, selected_evidence_ids=None, selected_curriculum_code=None):
    links, node_info, debug_summary, _, _ = prepare_sankey_data(
        evidence,
        curriculum,
        sop,
        selected_evidence_ids=selected_evidence_ids,
        selected_curriculum_code=selected_curriculum_code,
    )

    if not links:
        return None, [], debug_summary

    curriculum_text = curriculum.set_index("CurriculumID")["CurriculumText"].to_dict()
    sop_text = sop.set_index("SoPID")["SoPText"].to_dict()

    labels = list(dict.fromkeys([value for pair in links for value in pair[:2]]))

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

    return figure, node_info, debug_summary


def display_sankey_debug_summary(debug_summary):
    st.caption(
        " | ".join([
            f"Selected evidence: {debug_summary.get('selected_evidence_count', 0)}",
            f"Curriculum links: {debug_summary.get('curriculum_links_count', 0)}",
            f"SoP links: {debug_summary.get('sop_links_count', 0)}",
            f"Unique curriculum nodes: {debug_summary.get('unique_curriculum_nodes', 0)}",
            f"Unique SoP nodes: {debug_summary.get('unique_sop_nodes', 0)}",
        ])
    )


def run_sankey_filter_smoke_test():
    test_evidence = pd.DataFrame(
        [
            {"EOAID": "TEST-E1", "EOATitle": "Test evidence", "EvidenceType": "Evidence of Activity (EOA)", "MappingType": "Curriculum", "TargetID": "ABC001", "Weight": 1, "CurriculumCode": "TEST-CURR"},
            {"EOAID": "TEST-E1", "EOATitle": "Test evidence", "EvidenceType": "Evidence of Activity (EOA)", "MappingType": "Curriculum", "TargetID": "ABC002", "Weight": 1, "CurriculumCode": "TEST-CURR"},
            {"EOAID": "TEST-E1", "EOATitle": "Test evidence", "EvidenceType": "Evidence of Activity (EOA)", "MappingType": "SoP", "TargetID": "1", "Weight": 1, "CurriculumCode": "TEST-CURR"},
            {"EOAID": "TEST-E2", "EOATitle": "Other evidence", "EvidenceType": "Evidence of Activity (EOA)", "MappingType": "Curriculum", "TargetID": "ABC999", "Weight": 1, "CurriculumCode": "TEST-CURR"},
            {"EOAID": "TEST-E1", "EOATitle": "Test evidence", "EvidenceType": "Evidence of Activity (EOA)", "MappingType": "SoP", "TargetID": "99", "Weight": 1, "CurriculumCode": "TEST-CURR"},
            {"EOAID": "TEST-E1", "EOATitle": "Test evidence", "EvidenceType": "Evidence of Activity (EOA)", "MappingType": "Curriculum", "TargetID": "XYZ123", "Weight": 1, "CurriculumCode": "OTHER-CURR"},
        ]
    )

    test_curriculum = pd.DataFrame(
        [
            {"CurriculumID": "ABC001", "CurriculumText": "Module 1"},
            {"CurriculumID": "ABC002", "CurriculumText": "Module 2"},
        ]
    )

    test_sop = pd.DataFrame(
        [
            {"SoPID": "1", "SoPText": "Criterion 1"},
        ]
    )

    links, _, debug_summary, _, _ = prepare_sankey_data(
        test_evidence,
        test_curriculum,
        test_sop,
        selected_evidence_ids=["TEST-E1"],
        selected_curriculum_code="TEST-CURR",
    )

    expected = {
        "selected_evidence_count": 1,
        "curriculum_links_count": 2,
        "sop_links_count": 1,
        "unique_curriculum_nodes": 2,
        "unique_sop_nodes": 1,
    }

    passed = len(links) == 3 and all(debug_summary.get(key) == value for key, value in expected.items())
    return passed, debug_summary


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


def footer(curriculum_code):

    st.sidebar.markdown("---")

    st.sidebar.markdown("### Local Storage")
    st.sidebar.caption(f"Database: {storage.get_database_path()}")

    backup_file = st.sidebar.text_input("Backup filename", value="portfolio_backup.sqlite3")
    if st.sidebar.button("Backup portfolio", use_container_width=True):
        backup_path = storage.backup_database(backup_file)
        st.sidebar.success(f"Saved backup to {backup_path}")
        with open(backup_path, "rb") as backup_handle:
            st.sidebar.download_button(
                "Download backup file",
                data=backup_handle.read(),
                file_name=backup_path.name,
                mime="application/x-sqlite3",
                use_container_width=True,
            )

    restore_file = st.sidebar.file_uploader(
        "Restore portfolio from backup",
        type=["sqlite3", "db", "sqlite"],
    )
    if restore_file is not None and st.sidebar.button("Restore portfolio from backup", use_container_width=True):
        temp_path = Path(storage.get_backup_dir()) / restore_file.name
        temp_path.write_bytes(restore_file.getvalue())
        storage.restore_database(temp_path)
        st.sidebar.success("Backup restored. Reload the app to see the changes.")
        st.rerun()

    st.sidebar.download_button(
        "Export CSV (evidence mappings)",
        data=dataframe_csv_bytes(storage.load_evidence_dataframe(curriculum_code)),
        file_name="evidence_mappings.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.sidebar.download_button(
        "Export Excel workbook",
        data=dataframe_excel_bytes(curriculum_code),
        file_name="portfolio_export.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.sidebar.caption("Created by James Griffiths")
    st.sidebar.caption("GitHub: tinypathogens")

if "selected_evidence_type_value" not in st.session_state:
    st.session_state.selected_evidence_type_value = "Evidence of Activity (EOA)"

if "generate_sankey" not in st.session_state:
    st.session_state.generate_sankey = False

if "evidence_section_mode" not in st.session_state:
    st.session_state.evidence_section_mode = "Add evidence"

sidebar_section = st.sidebar.radio(
    "Navigation",
    ["🏠 Home", "📖 Curricula", "📄 Evidence Items", "🔗 Sankey View", "📊 Dashboard", "⚙️ Settings"],
    index=0,
    label_visibility="collapsed",
)

selected_display = None
specialty_row = {}
selected_specialty_code = st.session_state.selected_specialty_code
selected_needs_import = False

if sidebar_section == "📖 Curricula":
    st.sidebar.markdown("### Select specialty")
    if specialty_registry.empty:
        st.sidebar.info("No specialties are available yet. Refresh the registry from NSHCS.")
    else:
        specialty_registry = specialty_registry.copy()
        specialty_registry["DisplayLabel"] = specialty_registry.apply(
            lambda row: (
                f"{row['SpecialtyName']} ({row['CurriculumCode']})"
                if str(row.get("ImportStatus", "")).strip().lower() == "imported"
                else f"{row['SpecialtyName']} ({row['CurriculumCode']}) - curriculum structure not imported yet"
            ),
            axis=1,
        )
        display_options = specialty_registry["DisplayLabel"].tolist()
        default_display = specialty_registry.loc[
            specialty_registry["CurriculumCode"] == st.session_state.selected_specialty_code,
            "DisplayLabel",
        ]
        default_index = int(default_display.index[0]) if not default_display.empty else 0
        selected_display = st.sidebar.selectbox(
            "Select specialty",
            options=display_options,
            index=default_index if default_index < len(display_options) else 0,
            label_visibility="collapsed",
        )
        specialty_row = specialty_registry.loc[specialty_registry["DisplayLabel"] == selected_display].iloc[0].to_dict()
        selected_specialty_code = specialty_row["CurriculumCode"]
        st.session_state.selected_specialty_code = selected_specialty_code
        selected_import_status = str(specialty_row.get("ImportStatus", "")).strip().lower()
        selected_needs_import = selected_import_status != "imported"

        st.sidebar.caption(f"Selected: {specialty_row.get('SpecialtyName', selected_specialty_code)} | {specialty_row.get('CurriculumURL', '')}")

        if "auto_import_attempted_codes" not in st.session_state:
            st.session_state.auto_import_attempted_codes = []

        if selected_needs_import and selected_specialty_code not in st.session_state.auto_import_attempted_codes:
            st.session_state.auto_import_attempted_codes.append(selected_specialty_code)
            try:
                auto_summary = storage.import_specialty_from_source(selected_specialty_code, specialty_row.get("CurriculumURL"))
                if int(auto_summary.get("imported_items", 0) or 0) > 0:
                    st.rerun()
            except Exception:
                pass

        st.sidebar.markdown("### Curriculum import status")
        if selected_needs_import:
            st.sidebar.warning("This curriculum structure is not imported yet.")
        else:
            st.sidebar.success("This curriculum structure is already imported.")

        with st.sidebar.expander("Advanced settings", expanded=False):
            st.caption("The specialty registry is seeded automatically on first run from the NSHCS curriculum library.")

            if selected_needs_import and st.button("Import from NSHCS URL", use_container_width=True):
                try:
                    summary = storage.import_specialty_from_source(selected_specialty_code, specialty_row.get("CurriculumURL"))
                    if int(summary.get("imported_items", 0) or 0) > 0:
                        st.success(f"Imported {specialty_row.get('SpecialtyName', selected_specialty_code)}")
                        display_import_summary(summary)
                    else:
                        st.warning(f"No valid curriculum items were imported for {specialty_row.get('SpecialtyName', selected_specialty_code)}")
                        display_import_summary(summary)
                    st.rerun()
                except Exception as exc:
                    st.error(f"NSHCS import failed: {exc}")
                    st.info("You can use CSV/JSON import below as a fallback if you already have an exported curriculum file.")

            if selected_needs_import:
                csv_upload = st.file_uploader("Fallback import from CSV", type=["csv"], key="curriculum_csv_upload")
                if csv_upload is not None and st.button("Import CSV into selected specialty", use_container_width=True):
                    frame = pd.read_csv(BytesIO(csv_upload.getvalue()), dtype=str).fillna("")
                    summary = storage.import_specialty_from_dataframe(frame, curriculum_code=selected_specialty_code, source_url=csv_upload.name)
                    st.success(f"Imported CSV into {selected_specialty_code}")
                    display_import_summary(summary)
                    st.rerun()

                json_upload = st.file_uploader("Fallback import from JSON", type=["json"], key="curriculum_json_upload")
                if json_upload is not None and st.button("Import JSON into selected specialty", use_container_width=True):
                    payload = json.loads(json_upload.getvalue().decode("utf-8"))
                    frame = pd.DataFrame(payload if isinstance(payload, list) else payload.get("items", []))
                    summary = storage.import_specialty_from_dataframe(frame.fillna(""), curriculum_code=selected_specialty_code, source_url=json_upload.name)
                    st.success(f"Imported JSON into {selected_specialty_code}")
                    display_import_summary(summary)
                    st.rerun()
            else:
                st.caption("This curriculum structure is already imported.")

            template_frame = storage.export_curriculum_template()
            st.download_button(
                "Export curriculum template",
                data=template_frame.to_csv(index=False).encode("utf-8"),
                file_name="curriculum_template.csv",
                mime="text/csv",
                use_container_width=True,
            )

            if st.button("Run Sankey filter smoke test", use_container_width=True):
                passed, smoke_debug = run_sankey_filter_smoke_test()
                if passed:
                    st.success("Smoke test passed: 1 selected evidence item produced exactly 2 curriculum links + 1 SoP link.")
                else:
                    st.error("Smoke test failed: Sankey filtering did not match expected 2 curriculum links + 1 SoP link.")
                display_sankey_debug_summary(smoke_debug)

elif sidebar_section == "📄 Evidence Items":
    st.sidebar.markdown("### Evidence management controls")
    st.sidebar.radio(
        "Evidence tools",
        ["Add evidence", "Delete evidence"],
        key="evidence_section_mode",
        label_visibility="collapsed",
    )

elif sidebar_section == "🔗 Sankey View":
    st.sidebar.markdown("### Sankey scope")
    st.sidebar.radio(
        "Select Sankey view",
        [
            "Full portfolio",
            "Focus on selected evidence item(s)",
            "Focus by evidence type",
        ],
        key="sankey_view_mode",
        label_visibility="collapsed",
    )

    if st.session_state.sankey_view_mode == "Focus on selected evidence item(s)":
        st.sidebar.markdown("### Evidence Selection")
        st.session_state.selected_evidence_ids = st.sidebar.multiselect(
            "Select evidence items",
            options=get_evidence_items(evidence),
            default=None,
        )
    elif st.session_state.sankey_view_mode == "Focus by evidence type":
        st.sidebar.markdown("### Evidence Type")
        evidence_type_options = [
            "Evidence of Activity (EOA)",
            "Case-Based Discussion (CBD)",
            "Multi-Source Feedback (MSF)",
            "Training Plan Event",
        ]
        st.session_state.selected_evidence_type_value = st.sidebar.selectbox(
            "Select evidence type",
            options=evidence_type_options,
            index=evidence_type_options.index(st.session_state.selected_evidence_type_value)
            if st.session_state.selected_evidence_type_value in evidence_type_options
            else 0,
            label_visibility="collapsed",
        )

    st.sidebar.markdown("---")
    if st.sidebar.button("Generate Sankey", use_container_width=True):
        st.session_state.generate_sankey = True

elif sidebar_section == "⚙️ Settings":
    st.sidebar.markdown("### Local Storage")
    st.sidebar.caption(f"Database: {storage.get_database_path()}")

    backup_file = st.sidebar.text_input("Backup filename", value="portfolio_backup.sqlite3")
    if st.sidebar.button("Backup portfolio", use_container_width=True):
        backup_path = storage.backup_database(backup_file)
        st.sidebar.success(f"Saved backup to {backup_path}")
        with open(backup_path, "rb") as backup_handle:
            st.sidebar.download_button(
                "Download backup file",
                data=backup_handle.read(),
                file_name=backup_path.name,
                mime="application/x-sqlite3",
                use_container_width=True,
            )

    restore_file = st.sidebar.file_uploader(
        "Restore portfolio from backup",
        type=["sqlite3", "db", "sqlite"],
    )
    if restore_file is not None and st.sidebar.button("Restore portfolio from backup", use_container_width=True):
        temp_path = Path(storage.get_backup_dir()) / restore_file.name
        temp_path.write_bytes(restore_file.getvalue())
        storage.restore_database(temp_path)
        st.sidebar.success("Backup restored. Reload the app to see the changes.")
        st.rerun()

    st.sidebar.download_button(
        "Export CSV (evidence mappings)",
        data=dataframe_csv_bytes(storage.load_evidence_dataframe(selected_specialty_code)),
        file_name="evidence_mappings.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.sidebar.download_button(
        "Export Excel workbook",
        data=dataframe_excel_bytes(selected_specialty_code),
        file_name="portfolio_export.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

st.sidebar.caption("Created by James Griffiths")
st.sidebar.caption("GitHub: tinypathogens")

curriculum, sop, evidence = load_data(selected_specialty_code)

if specialty_registry is not None and not specialty_registry.empty:
    specialty_status = specialty_registry.loc[specialty_registry["CurriculumCode"] == selected_specialty_code, "ImportStatus"].astype(str)
    if not specialty_status.empty and specialty_status.iloc[0].strip().lower() != "imported":
        st.warning("This curriculum is listed but has not yet been imported. Please import it from the NSHCS curriculum library.")

selected_sidebar_section = sidebar_section
view_mode = st.session_state.get("evidence_section_mode", "Add evidence") if selected_sidebar_section == "📄 Evidence Items" else (
    st.session_state.get("sankey_view_mode", "Full portfolio") if selected_sidebar_section == "🔗 Sankey View" else (
        "Portfolio Dashboard" if selected_sidebar_section == "📊 Dashboard" else selected_sidebar_section
    )
)

selected_evidence = st.session_state.get("selected_evidence_ids", [])
selected_evidence_type = st.session_state.selected_evidence_type_value

evidence_items_df = storage.load_evidence_items_dataframe(selected_specialty_code)
portfolio_summary = calculate_portfolio_summary(curriculum, sop, evidence, evidence_items_df)

if selected_sidebar_section == "🏠 Home":
    st.markdown("## Portfolio Summary")
    summary_cols = st.columns(5)

    with summary_cols[0]:
        st.metric("Evidence items", portfolio_summary["total_evidence_items"])
    with summary_cols[1]:
        st.metric("Mapped curriculum modules", portfolio_summary["mapped_curriculum_modules"])
    with summary_cols[2]:
        st.metric("Mapped SoP domains", portfolio_summary["mapped_sop_domains"])
    with summary_cols[3]:
        st.metric("Unmapped evidence items", portfolio_summary["unmapped_evidence_items"])
    with summary_cols[4]:
        st.metric("Curriculum coverage", f"{portfolio_summary['curriculum_coverage_pct']}%")

    st.caption("Use the sidebar sections to move between curricula, evidence management, Sankey views, the dashboard, and settings.")

elif selected_sidebar_section == "📖 Curricula":
    st.markdown("## Curricula")
    if specialty_row:
        st.write(f"**Selected specialty:** {specialty_row.get('SpecialtyName', selected_specialty_code)}")
        st.write(f"**Curriculum URL:** {specialty_row.get('CurriculumURL', '')}")
        st.write(f"**Import status:** {specialty_row.get('ImportStatus', '')}")
    else:
        st.info("Select a specialty in the sidebar to view curriculum details.")

elif view_mode == "Add evidence":
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
        module_rows = curriculum[
            curriculum["ItemType"].fillna("").astype(str).str.lower().eq("module")
            & curriculum["CurriculumID"].fillna("").astype(str).map(storage.is_valid_module_code)
        ].copy()
        curriculum_options = [
            f"{cid}: {ctext}"
            for cid, ctext in zip(module_rows["CurriculumID"], module_rows["CurriculumText"])
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
                curriculum_ids = [option.split(":")[0].strip() for option in selected_curriculum]
                sop_ids = [option.split(":")[0].strip() for option in selected_sop]

                storage.upsert_evidence_item(
                    evidence_id=evidence_id,
                    evidence_title=evidence_title,
                    evidence_type=evidence_type,
                    curriculum_ids=curriculum_ids,
                    sop_ids=sop_ids,
                    curriculum_code=selected_specialty_code,
                )
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
                    storage.delete_evidence_item(delete_eoaid)
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

elif selected_sidebar_section == "🔗 Sankey View" and st.session_state.generate_sankey:
    if view_mode == "Full portfolio":
        st.markdown("### Full Portfolio")

        if evidence.empty:
            st.info("No evidence mappings available yet.")
        else:
            sankey_fig, node_info, debug_summary = build_sankey(
                evidence,
                curriculum,
                sop,
                selected_curriculum_code=selected_specialty_code,
            )
            display_sankey_debug_summary(debug_summary)
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
                sankey_fig, node_info, debug_summary = build_sankey(
                    evidence,
                    curriculum,
                    sop,
                    selected_evidence_ids=selected_evidence,
                    selected_curriculum_code=selected_specialty_code,
                )
                display_sankey_debug_summary(debug_summary)
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
            evidence_ids_for_type = filtered["EOAID"].dropna().astype(str).tolist()
            sankey_fig, node_info, debug_summary = build_sankey(
                evidence,
                curriculum,
                sop,
                selected_evidence_ids=evidence_ids_for_type,
                selected_curriculum_code=selected_specialty_code,
            )
            display_sankey_debug_summary(debug_summary)
            if sankey_fig is not None:
                st.plotly_chart(
                    sankey_fig,
                    use_container_width=True,
                    config={"displayModeBar": True},
                )
                display_sankey_export_html(sankey_fig, selected_evidence_type)
                st.markdown("---")
                display_node_details(node_info, curriculum, sop)

elif selected_sidebar_section == "⚙️ Settings":
    st.markdown("## Settings")
    st.info("Use the sidebar to manage backup, restore, and export options.")

else:
    st.info("Select a section from the sidebar to continue.")