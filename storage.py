from __future__ import annotations

import html
import json
import shutil
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen

import pandas as pd


APP_NAME = "HSST Portfolio Sankey"
BASE_DIR = Path(__file__).resolve().parent
REFERENCE_DATA_DIR = BASE_DIR / "data"
SPECIALTY_REGISTRY_URL = "https://curriculumlibrary.nshcs.org.uk/hsst/specialties/"
DEFAULT_SPECIALTY_CODE = "HLS2-3-20"
DEFAULT_SPECIALTY_NAME = "Virology"


REGISTRY_COLUMNS = [
    "CurriculumCode",
    "SpecialtyName",
    "Division",
    "Version",
    "CurriculumURL",
    "ImportStatus",
    "ImportedAt",
    "LastRefreshedAt",
]

CURRICULUM_COLUMNS = [
    "CurriculumCode",
    "ItemType",
    "SectionName",
    "CurriculumID",
    "CurriculumText",
    "Stage",
    "Status",
    "NodeLabel",
    "ItemURL",
    "SourceURL",
    "SortOrder",
    "CreatedAt",
    "UpdatedAt",
]

PROGRAMME_COLUMNS = [
    "CurriculumCode",
    "SectionID",
    "SectionName",
    "SectionText",
    "SourceURL",
    "SortOrder",
    "CreatedAt",
    "UpdatedAt",
]

CURRICULUM_CODE_PATTERN = re.compile(r"^(?:[A-Z]{3}\d{3}|[A-Z]{3}\d+(?:-\d+)+)$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_user_data_dir() -> Path:
    home = Path.home()
    if str(home).startswith("/Users/"):
        base_dir = home / "Library" / "Application Support"
    elif home.drive:
        base_dir = home / "AppData" / "Roaming"
    else:
        base_dir = home / ".local" / "share"

    data_dir = base_dir / APP_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_database_path() -> Path:
    return get_user_data_dir() / "portfolio.sqlite3"


def get_attachments_dir() -> Path:
    attachments_dir = get_user_data_dir() / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    return attachments_dir


def get_backup_dir() -> Path:
    backup_dir = get_user_data_dir() / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def _strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _extract_table_cell_value(cell_html: str) -> str:
    label_match = re.search(
        r'<span[^>]*nhsuk-table-responsive__heading[^>]*>\s*[^<]*</span>\s*(.*)$',
        cell_html,
        flags=re.S,
    )
    content = label_match.group(1) if label_match else cell_html
    return _strip_tags(content)


def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _is_valid_curriculum_item_code(value: str) -> bool:
    return bool(CURRICULUM_CODE_PATTERN.match(str(value).strip().upper()))


def is_valid_module_code(code: str) -> bool:
    return _is_valid_curriculum_item_code(code)


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_definition: str) -> None:
    if _column_exists(connection, table_name, column_name):
        return

    column_definition = column_definition.strip()
    if not column_definition.lower().startswith(column_name.lower()):
        column_definition = f"{column_name} {column_definition}"

    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}")


def _drop_column_if_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> None:
    if _column_exists(connection, table_name, column_name):
        connection.execute(f'ALTER TABLE {table_name} DROP COLUMN "{column_name}"')


def _extract_registry_records(html_text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r'<div class="card card--specialty card--specialty-hsst.*?'
        r'<div class="card__code">\s*(?P<card_code>[^<]+?)\s*</div>.*?'
        r'<h3 class="card__title">(?P<specialty_name>[^<]+)</h3>.*?'
        r'<span class="card__tags">\s*(?P<division>[^<]+?)\s*</span>.*?'
        r'<a href="(?P<curriculum_url>[^"]+/hsst/specialty/(?P<curriculum_code>[^/]+)/?)">(?P<version>V\d+)</a>',
        re.S,
    )

    records: list[dict[str, str]] = []
    for match in pattern.finditer(html_text):
        record = match.groupdict()
        record["curriculum_code"] = record["curriculum_code"].rstrip("/")
        record["import_status"] = "Not imported"
        records.append(record)

    return records


def _extract_section_html(html_text: str, section_id: str) -> str:
    start_pattern = rf'<div id="{re.escape(section_id)}"[^>]*class="subsection"[^>]*>'
    start_match = re.search(start_pattern, html_text, flags=re.S)
    if not start_match:
        return ""

    remainder = html_text[start_match.end():]
    end_match = re.search(r'<div id="[^"]+"[^>]*class="subsection"[^>]*>|</article>', remainder, flags=re.S)
    return remainder[:end_match.start()] if end_match else remainder


def _extract_module_rows(section_html: str, curriculum_code: str, source_url: str, section_name: str, sort_start: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    row_matches = re.findall(r'<tr[^>]*>(.*?)</tr>', section_html, flags=re.S)
    sort_order = sort_start

    for row_html in row_matches:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, flags=re.S)
        if len(cells) < 3:
            continue

        item_code = _extract_table_cell_value(cells[0])
        item_title = _extract_table_cell_value(cells[1])
        item_status = _extract_table_cell_value(cells[2])
        if not item_code or not item_title:
            continue

        rows.append({
            "CurriculumCode": curriculum_code,
            "ItemType": "Module",
            "SectionName": section_name,
            "CurriculumID": item_code,
            "CurriculumText": item_title,
            "Stage": section_name,
            "Status": item_status,
            "NodeLabel": f"{item_code}: {item_title}",
            "ItemURL": "",
            "SourceURL": source_url,
            "SortOrder": str(sort_order),
        })
        sort_order += 1

    return rows


def _extract_programme_rows(html_text: str, curriculum_code: str, source_url: str) -> list[dict[str, str]]:
    programme_sections = [
        ("details", "Details"),
        ("programme-aim", "Programme aim"),
        ("expected-programme-outcomes", "Expected programme outcomes"),
        ("learning-teaching-methods", "Learning and teaching methods"),
        ("standards-of-proficiency", "Standards of proficiency"),
        ("programme-structure", "Programme structure"),
        ("entry-routes-requirements", "Entry routes and requirements"),
    ]

    rows: list[dict[str, str]] = []
    sort_order = 1
    for section_id, section_name in programme_sections:
        section_html = _extract_section_html(html_text, section_id)
        if not section_html:
            continue

        section_text = _strip_tags(section_html)
        if not section_text:
            continue

        rows.append({
            "CurriculumCode": curriculum_code,
            "SectionID": section_id,
            "SectionName": section_name,
            "SectionText": section_text,
            "SourceURL": source_url,
            "SortOrder": str(sort_order),
        })
        sort_order += 1

    return rows


def _parse_specialty_page(curriculum_code: str, specialty_name: str, division: str, version: str, curriculum_url: str, html_text: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    module_rows: list[dict[str, str]] = []

    for section_id, section_name, parser in [
        ("stage-one-modules", "Stage One", _extract_module_rows),
        ("stage-two-modules", "Stage Two", _extract_module_rows),
    ]:
        section_html = _extract_section_html(html_text, section_id)
        if section_html:
            module_rows.extend(parser(section_html, curriculum_code, curriculum_url, section_name, len(module_rows) + 1))

    items = pd.DataFrame(module_rows, columns=CURRICULUM_COLUMNS[:-2])
    if items.empty:
        items = pd.DataFrame(columns=CURRICULUM_COLUMNS[:-2])

    programme_rows = _extract_programme_rows(html_text, curriculum_code, curriculum_url)
    programme = pd.DataFrame(programme_rows, columns=PROGRAMME_COLUMNS[:-2])
    if programme.empty:
        programme = pd.DataFrame(columns=PROGRAMME_COLUMNS[:-2])

    return items, programme


def _summarize_curriculum_rows(raw_rows: list[dict[str, str]], curriculum_code: str) -> tuple[pd.DataFrame, dict[str, object]]:
    valid_rows: list[dict[str, str]] = []
    skipped_examples: list[str] = []
    skipped_count = 0

    for row in raw_rows:
        item_code = str(row.get("CurriculumID", "")).strip()
        item_title = str(row.get("CurriculumText", "")).strip()
        section_name = str(row.get("SectionName", "")).strip() or "Unknown section"
        source_url = str(row.get("SourceURL", "")).strip()

        reasons: list[str] = []
        if not item_code:
            reasons.append("blank item_code")
        elif not _is_valid_curriculum_item_code(item_code):
            reasons.append(f"invalid item_code '{item_code}'")

        if not item_title:
            reasons.append("blank item_title")

        if reasons:
            skipped_count += 1
            if len(skipped_examples) < 5:
                skipped_examples.append(f"{section_name}: {', '.join(reasons)}")
            continue

        row = row.copy()
        row["CurriculumCode"] = curriculum_code
        row["CurriculumID"] = item_code.upper()
        row["CurriculumText"] = item_title
        row["NodeLabel"] = row.get("NodeLabel") or f"{item_code.upper()}: {item_title}"
        row["SourceURL"] = source_url
        valid_rows.append(row)

    frame = pd.DataFrame(valid_rows, columns=CURRICULUM_COLUMNS[:-2])
    summary = {
        "curriculum_code": curriculum_code,
        "imported_items": len(valid_rows),
        "skipped_items": skipped_count,
        "skipped_examples": skipped_examples,
    }
    return frame, summary


def _write_curriculum_import(curriculum_code: str, specialty_name: str, division: str, version: str, curriculum_url: str, items_df: pd.DataFrame) -> dict[str, object]:
    timestamp = _utc_now()
    summary = {
        "curriculum_code": curriculum_code,
        "specialty_name": specialty_name,
        "division": division,
        "version": version,
        "curriculum_url": curriculum_url,
        "imported_items": int(len(items_df)),
        "skipped_items": 0,
        "skipped_examples": [],
        "import_status": "Not imported",
    }

    if items_df.empty:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO specialty_registry
                (curriculum_code, specialty_name, division, version, curriculum_url, import_status, imported_at, last_refreshed_at)
                VALUES (?, ?, ?, ?, ?, 'Not imported', NULL, ?)
                ON CONFLICT(curriculum_code) DO UPDATE SET
                    specialty_name = excluded.specialty_name,
                    division = excluded.division,
                    version = excluded.version,
                    curriculum_url = excluded.curriculum_url,
                    import_status = 'Not imported',
                    last_refreshed_at = excluded.last_refreshed_at
                """,
                (curriculum_code, specialty_name, division, version, curriculum_url, timestamp),
            )
        return summary

    items_to_store = items_df.copy().rename(columns={
        "CurriculumCode": "curriculum_code",
        "ItemType": "item_type",
        "SectionName": "section_name",
        "CurriculumID": "curriculum_id",
        "CurriculumText": "curriculum_text",
        "Stage": "stage",
        "Status": "status",
        "NodeLabel": "node_label",
        "ItemURL": "item_url",
        "SourceURL": "source_url",
        "SortOrder": "sort_order",
    })
    items_to_store["created_at"] = timestamp
    items_to_store["updated_at"] = timestamp

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO specialty_registry
            (curriculum_code, specialty_name, division, version, curriculum_url, import_status, imported_at, last_refreshed_at)
            VALUES (?, ?, ?, ?, ?, 'Imported', ?, ?)
            ON CONFLICT(curriculum_code) DO UPDATE SET
                specialty_name = excluded.specialty_name,
                division = excluded.division,
                version = excluded.version,
                curriculum_url = excluded.curriculum_url,
                import_status = 'Imported',
                imported_at = excluded.imported_at,
                last_refreshed_at = excluded.last_refreshed_at
            """,
            (curriculum_code, specialty_name, division, version, curriculum_url, timestamp, timestamp),
        )
        connection.execute("DELETE FROM specialty_curriculum_items WHERE curriculum_code = ?", (curriculum_code,))
        items_to_store.to_sql("specialty_curriculum_items", connection, if_exists="append", index=False)

    summary["import_status"] = "Imported"
    return summary


def _write_programme_items(curriculum_code: str, programme_df: pd.DataFrame) -> None:
    if programme_df.empty:
        return

    timestamp = _utc_now()
    items_to_store = programme_df.copy().rename(columns={
        "CurriculumCode": "curriculum_code",
        "SectionID": "section_id",
        "SectionName": "section_name",
        "SectionText": "section_text",
        "SourceURL": "source_url",
        "SortOrder": "sort_order",
    })
    items_to_store["created_at"] = timestamp
    items_to_store["updated_at"] = timestamp

    with get_connection() as connection:
        connection.execute("DELETE FROM specialty_programme_items WHERE curriculum_code = ?", (curriculum_code,))
        items_to_store.to_sql("specialty_programme_items", connection, if_exists="append", index=False)


def _normalize_specialty_tables(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT item_id, curriculum_code, item_type, section_name, curriculum_id, curriculum_text, stage, status,
               node_label, item_url, source_url, sort_order, created_at, updated_at
        FROM specialty_curriculum_items
        ORDER BY item_id
        """
    ).fetchall()

    if not rows:
        return

    programme_rows: list[tuple[str, str, str, str, str, str, str, str]] = []
    module_ids_to_delete: list[int] = []

    for row in rows:
        row_dict = dict(row)
        item_type = str(row_dict.get("item_type", "")).strip().lower()
        item_code = str(row_dict.get("curriculum_id", "")).strip()
        item_title = str(row_dict.get("curriculum_text", "")).strip()
        section_name = str(row_dict.get("section_name", "")).strip() or str(row_dict.get("stage", "")).strip() or "Programme"

        is_valid_module = item_type == "module" and _is_valid_curriculum_item_code(item_code) and bool(item_title)
        if is_valid_module:
            connection.execute(
                """
                UPDATE specialty_curriculum_items
                SET item_type = 'module'
                WHERE item_id = ?
                """,
                (row_dict["item_id"],),
            )
            continue

        if item_title or item_code:
            programme_rows.append(
                (
                    row_dict.get("curriculum_code", DEFAULT_SPECIALTY_CODE),
                    section_name,
                    item_code or section_name,
                    item_title or str(row_dict.get("node_label", "")).strip() or section_name,
                    str(row_dict.get("source_url", "")).strip(),
                    str(row_dict.get("sort_order", "")).strip(),
                    row_dict.get("created_at", _utc_now()),
                    row_dict.get("updated_at", _utc_now()),
                )
            )
        module_ids_to_delete.append(row_dict["item_id"])

    if programme_rows:
        connection.executemany(
            """
            INSERT OR REPLACE INTO specialty_programme_items
            (curriculum_code, section_name, section_id, section_text, source_url, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            programme_rows,
        )

    if module_ids_to_delete:
        connection.executemany(
            "DELETE FROM specialty_curriculum_items WHERE item_id = ?",
            [(item_id,) for item_id in module_ids_to_delete],
        )


def _load_local_virology_seed() -> pd.DataFrame:
    curriculum_file = REFERENCE_DATA_DIR / "curriculum.csv"
    if not curriculum_file.exists():
        return pd.DataFrame(columns=CURRICULUM_COLUMNS[:-2])

    curriculum = pd.read_csv(curriculum_file, dtype=str).fillna("")
    rows: list[dict[str, str]] = []
    for index, row in curriculum.iterrows():
        curriculum_id = str(row.get("CurriculumID", "")).strip()
        curriculum_text = str(row.get("CurriculumText", "")).strip()
        if not curriculum_id or not curriculum_text:
            continue
        stage = str(row.get("Stage", "")).strip()
        status = str(row.get("Status", "")).strip()
        node_label = str(row.get("NodeLabel", "")).strip() or f"{curriculum_id}: {curriculum_text}"
        rows.append({
            "CurriculumCode": DEFAULT_SPECIALTY_CODE,
            "ItemType": "Module",
            "SectionName": stage or "Modules",
            "CurriculumID": curriculum_id,
            "CurriculumText": curriculum_text,
            "Stage": stage,
            "Status": status,
            "NodeLabel": node_label,
            "ItemURL": "",
            "SourceURL": str(curriculum_file),
            "SortOrder": str(index + 1),
        })

    return pd.DataFrame(rows)


def refresh_specialty_registry_from_nshcs() -> pd.DataFrame:
    html_text = _fetch_html(SPECIALTY_REGISTRY_URL)
    records = _extract_registry_records(html_text)
    timestamp = _utc_now()

    with get_connection() as connection:
        existing = pd.read_sql_query(
            "SELECT curriculum_code AS CurriculumCode, import_status AS ImportStatus, imported_at AS ImportedAt FROM specialty_registry",
            connection,
            dtype=str,
        )
        existing_map = {row["CurriculumCode"]: row for _, row in existing.iterrows()} if not existing.empty else {}

        for record in records:
            current = existing_map.get(record["curriculum_code"], {})
            import_status = current.get("ImportStatus", record["import_status"])
            imported_at = current.get("ImportedAt")
            connection.execute(
                """
                INSERT INTO specialty_registry
                (curriculum_code, specialty_name, division, version, curriculum_url, import_status, imported_at, last_refreshed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(curriculum_code) DO UPDATE SET
                    specialty_name = excluded.specialty_name,
                    division = excluded.division,
                    version = excluded.version,
                    curriculum_url = excluded.curriculum_url,
                    import_status = excluded.import_status,
                    imported_at = COALESCE(specialty_registry.imported_at, excluded.imported_at),
                    last_refreshed_at = excluded.last_refreshed_at
                """,
                (
                    record["curriculum_code"],
                    record["specialty_name"],
                    record["division"],
                    record["version"],
                    record["curriculum_url"],
                    import_status,
                    imported_at,
                    timestamp,
                ),
            )

        connection.execute(
            "UPDATE specialty_registry SET last_refreshed_at = ? WHERE last_refreshed_at IS NULL",
            (timestamp,),
        )

    return load_specialty_registry_dataframe()


def load_specialty_registry_dataframe() -> pd.DataFrame:
    with get_connection() as connection:
        if not _table_exists(connection, "specialty_registry"):
            return pd.DataFrame(columns=REGISTRY_COLUMNS)

        registry = pd.read_sql_query(
            """
            SELECT curriculum_code AS CurriculumCode,
                   specialty_name AS SpecialtyName,
                   division AS Division,
                   version AS Version,
                   curriculum_url AS CurriculumURL,
                   import_status AS ImportStatus,
                   imported_at AS ImportedAt,
                   last_refreshed_at AS LastRefreshedAt
            FROM specialty_registry
            ORDER BY specialty_name
            """,
            connection,
            dtype=str,
        )

    if registry.empty:
        return pd.DataFrame(columns=REGISTRY_COLUMNS)

    return registry


def load_programme_level_dataframe(curriculum_code: str | None = None) -> pd.DataFrame:
    curriculum_code = str(curriculum_code).strip() if curriculum_code else DEFAULT_SPECIALTY_CODE
    with get_connection() as connection:
        if not _table_exists(connection, "specialty_programme_items"):
            return pd.DataFrame(columns=PROGRAMME_COLUMNS)

        programme = pd.read_sql_query(
            """
            SELECT curriculum_code AS CurriculumCode,
                   section_id AS SectionID,
                   section_name AS SectionName,
                   section_text AS SectionText,
                   source_url AS SourceURL,
                   sort_order AS SortOrder,
                   created_at AS CreatedAt,
                   updated_at AS UpdatedAt
            FROM specialty_programme_items
            WHERE curriculum_code = ?
            ORDER BY COALESCE(sort_order, 999999), section_name
            """,
            connection,
            params=(curriculum_code,),
            dtype=str,
        )

    if programme.empty:
        return pd.DataFrame(columns=PROGRAMME_COLUMNS)

    return programme


def get_specialty_registry_row(curriculum_code: str) -> dict[str, str] | None:
    curriculum_code = str(curriculum_code).strip()
    if not curriculum_code:
        return None

    registry = load_specialty_registry_dataframe()
    if registry.empty:
        return None

    match = registry[registry["CurriculumCode"] == curriculum_code]
    if match.empty:
        return None

    return match.iloc[0].to_dict()


def import_specialty_from_source(curriculum_code: str, curriculum_url: str | None = None) -> dict[str, object]:
    registry_row = get_specialty_registry_row(curriculum_code)
    curriculum_url = curriculum_url or (registry_row or {}).get("CurriculumURL")
    if not curriculum_url:
        raise ValueError(f"No curriculum URL is available for {curriculum_code}.")

    html_text = _fetch_html(curriculum_url)
    title_match = re.search(r'<h1 class="page__title">([^<]+)</h1>', html_text)
    page_title = _strip_tags(title_match.group(1)) if title_match else curriculum_code
    specialty_name = page_title.rsplit("[", 1)[0].strip() if "[" in page_title else page_title
    version_match = re.search(r'\[([^\]]+)\]</h1>', html_text)
    version = version_match.group(1).strip() if version_match else ((registry_row or {}).get("Version") or "V1")
    division = (registry_row or {}).get("Division") or ""

    module_df, programme_df = _parse_specialty_page(curriculum_code, specialty_name, division, version, curriculum_url, html_text)
    items_df, summary = _summarize_curriculum_rows(module_df.to_dict(orient="records"), curriculum_code)

    if items_df.empty and curriculum_code == DEFAULT_SPECIALTY_CODE:
        items_df, summary = _summarize_curriculum_rows(_load_local_virology_seed().to_dict(orient="records"), curriculum_code)
        summary["skipped_examples"] = summary.get("skipped_examples", [])

    summary.update(_write_curriculum_import(curriculum_code, specialty_name, division, version, curriculum_url, items_df))
    if not programme_df.empty:
        _write_programme_items(curriculum_code, programme_df)
    return summary


def import_specialty_from_csv(csv_path: str | Path, curriculum_code: str | None = None) -> dict[str, object]:
    csv_path = Path(csv_path).expanduser()
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    frame = pd.read_csv(csv_path, dtype=str).fillna("")
    return import_specialty_from_dataframe(frame, curriculum_code=curriculum_code, source_url=str(csv_path))


def import_specialty_from_json(json_path: str | Path, curriculum_code: str | None = None) -> dict[str, object]:
    json_path = Path(json_path).expanduser()
    if not json_path.exists():
        raise FileNotFoundError(f"JSON file not found: {json_path}")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    frame = pd.DataFrame(payload if isinstance(payload, list) else payload.get("items", []))
    return import_specialty_from_dataframe(frame.fillna(""), curriculum_code=curriculum_code, source_url=str(json_path))


def export_curriculum_template() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "CurriculumCode": "HLS2-3-20",
            "ItemType": "Module",
            "SectionName": "Stage One",
            "CurriculumID": "HLS210",
            "CurriculumText": "Antimicrobial chemotherapy",
            "Stage": "Stage One",
            "Status": "Compulsory",
            "NodeLabel": "HLS210: Antimicrobial chemotherapy",
            "ItemURL": "",
            "SourceURL": "https://curriculumlibrary.nshcs.org.uk/hsst/specialty/HLS2-3-20/",
            "SortOrder": 1,
        }
    ])


def import_specialty_from_dataframe(frame: pd.DataFrame, curriculum_code: str | None = None, source_url: str = "") -> dict[str, object]:
    if frame.empty:
        raise ValueError("The provided curriculum file contains no rows.")

    normalized = {str(column).strip().lower().replace(" ", "_"): column for column in frame.columns}
    curriculum_code = curriculum_code or str(frame.iloc[0].get(normalized.get("curriculumcode", "CurriculumCode"), DEFAULT_SPECIALTY_CODE)).strip() or DEFAULT_SPECIALTY_CODE

    def pick(row: pd.Series, *names: str, default: str = "") -> str:
        for name in names:
            if name in normalized:
                value = str(row.get(normalized[name], "")).strip()
                if value:
                    return value
        return default

    rows: list[dict[str, str]] = []
    timestamp = _utc_now()
    for index, row in frame.iterrows():
        item_code = pick(row, "curriculumid", "item_code", "code")
        item_text = pick(row, "curriculumtext", "item_title", "title", default="")
        if not item_code or not item_text:
            rows.append({
                "CurriculumCode": curriculum_code,
                "ItemType": pick(row, "itemtype", "item_type", default="Module"),
                "SectionName": pick(row, "stage", "section_name", default="Modules"),
                "CurriculumID": item_code,
                "CurriculumText": item_text,
                "Stage": pick(row, "stage", "section_name", default="Modules"),
                "Status": pick(row, "status", "item_status"),
                "NodeLabel": pick(row, "nodelabel", "node_label", default=f"{item_code}: {item_text}"),
                "ItemURL": pick(row, "itemurl", "item_url"),
                "SourceURL": pick(row, "sourceurl", "source_url", default=source_url),
                "SortOrder": pick(row, "sortorder", "sort_order", default=str(index + 1)),
            })
            continue
        section_name = pick(row, "stage", "section_name", default="Modules")
        item_type = pick(row, "itemtype", "item_type", default="Module")
        status = pick(row, "status", "item_status")
        node_label = pick(row, "nodelabel", "node_label", default=f"{item_code}: {item_text}")
        item_url = pick(row, "itemurl", "item_url")
        source = pick(row, "sourceurl", "source_url", default=source_url)
        sort_order = pick(row, "sortorder", "sort_order", default=str(index + 1))

        rows.append({
            "CurriculumCode": curriculum_code,
            "ItemType": item_type or "Module",
            "SectionName": section_name,
            "CurriculumID": item_code,
            "CurriculumText": item_text,
            "Stage": section_name,
            "Status": status,
            "NodeLabel": node_label,
            "ItemURL": item_url,
            "SourceURL": source,
            "SortOrder": sort_order,
            "CreatedAt": timestamp,
            "UpdatedAt": timestamp,
        })

    items_df, summary = _summarize_curriculum_rows(rows, curriculum_code)
    if items_df.empty:
        raise ValueError("No valid curriculum rows could be imported from the supplied file.")

    summary.update(_write_curriculum_import(curriculum_code, curriculum_code, "", "", source_url, items_df))
    return summary


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(get_database_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS curriculum_modules (
                curriculum_id TEXT PRIMARY KEY,
                curriculum_text TEXT NOT NULL,
                stage TEXT,
                status TEXT,
                node_label TEXT
            );

            CREATE TABLE IF NOT EXISTS sop_criteria (
                sop_id TEXT PRIMARY KEY,
                sop_text TEXT NOT NULL,
                standard_id TEXT,
                standard_text TEXT,
                domain_id TEXT,
                domain_text TEXT,
                criterion_node_label TEXT,
                standard_node_label TEXT,
                domain_node_label TEXT
            );

            CREATE TABLE IF NOT EXISTS evidence_items (
                evidence_id TEXT PRIMARY KEY,
                evidence_title TEXT NOT NULL,
                evidence_type TEXT NOT NULL DEFAULT 'Unspecified',
                curriculum_code TEXT NOT NULL DEFAULT 'HLS2-3-20',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence_mappings (
                mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
                evidence_id TEXT NOT NULL,
                curriculum_code TEXT NOT NULL DEFAULT 'HLS2-3-20',
                mapping_type TEXT NOT NULL CHECK (mapping_type IN ('Curriculum', 'SoP')),
                target_id TEXT NOT NULL,
                weight INTEGER NOT NULL DEFAULT 1 CHECK (weight > 0),
                created_at TEXT NOT NULL,
                FOREIGN KEY (evidence_id) REFERENCES evidence_items (evidence_id) ON DELETE CASCADE,
                UNIQUE (evidence_id, mapping_type, target_id)
            );

            CREATE TABLE IF NOT EXISTS evidence_files (
                file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                evidence_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                original_path TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (evidence_id) REFERENCES evidence_items (evidence_id) ON DELETE CASCADE,
                UNIQUE (evidence_id, original_path, stored_path)
            );

            CREATE TABLE IF NOT EXISTS specialty_registry (
                curriculum_code TEXT PRIMARY KEY,
                specialty_name TEXT NOT NULL,
                division TEXT,
                version TEXT,
                curriculum_url TEXT NOT NULL,
                import_status TEXT NOT NULL DEFAULT 'Not imported',
                imported_at TEXT,
                last_refreshed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS specialty_curriculum_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                curriculum_code TEXT NOT NULL,
                item_type TEXT NOT NULL,
                section_name TEXT NOT NULL,
                curriculum_id TEXT NOT NULL,
                curriculum_text TEXT NOT NULL,
                stage TEXT,
                status TEXT,
                node_label TEXT,
                item_url TEXT,
                source_url TEXT,
                sort_order INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (curriculum_code) REFERENCES specialty_registry (curriculum_code) ON DELETE CASCADE,
                UNIQUE (curriculum_code, item_type, curriculum_id, section_name)
            );

            CREATE TABLE IF NOT EXISTS specialty_programme_items (
                programme_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                curriculum_code TEXT NOT NULL,
                section_name TEXT NOT NULL,
                section_id TEXT NOT NULL,
                section_text TEXT NOT NULL,
                source_url TEXT,
                sort_order INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (curriculum_code) REFERENCES specialty_registry (curriculum_code) ON DELETE CASCADE,
                UNIQUE (curriculum_code, section_id)
            );
            """
        )

        _ensure_column(connection, "evidence_items", "curriculum_code", f"curriculum_code TEXT NOT NULL DEFAULT '{DEFAULT_SPECIALTY_CODE}'")
        _ensure_column(connection, "evidence_mappings", "curriculum_code", f"curriculum_code TEXT NOT NULL DEFAULT '{DEFAULT_SPECIALTY_CODE}'")
        _drop_column_if_exists(connection, "evidence_items", "TEXT")
        _drop_column_if_exists(connection, "evidence_mappings", "TEXT")

        _seed_reference_tables(connection)
        _seed_evidence_tables(connection)
        _seed_specialty_tables(connection)
        _normalize_specialty_tables(connection)


def _seed_specialty_tables(connection: sqlite3.Connection) -> None:
    registry_count = connection.execute("SELECT COUNT(*) FROM specialty_registry").fetchone()[0]
    if registry_count == 0:
        try:
            registry_rows = _extract_registry_records(_fetch_html(SPECIALTY_REGISTRY_URL))
            timestamp = _utc_now()
            if registry_rows:
                connection.executemany(
                    """
                    INSERT INTO specialty_registry
                    (curriculum_code, specialty_name, division, version, curriculum_url, import_status, imported_at, last_refreshed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            row["curriculum_code"],
                            row["specialty_name"],
                            row["division"],
                            row["version"],
                            row["curriculum_url"],
                            row.get("import_status", "Not imported"),
                            None,
                            timestamp,
                        )
                        for row in registry_rows
                    ],
                )
            else:
                connection.execute(
                    """
                    INSERT INTO specialty_registry
                    (curriculum_code, specialty_name, division, version, curriculum_url, import_status, imported_at, last_refreshed_at)
                    VALUES (?, ?, ?, ?, ?, 'Not imported', NULL, ?)
                    """,
                    (
                        DEFAULT_SPECIALTY_CODE,
                        DEFAULT_SPECIALTY_NAME,
                        "Life Sciences",
                        "V1",
                        f"https://curriculumlibrary.nshcs.org.uk/hsst/specialty/{DEFAULT_SPECIALTY_CODE}/",
                        timestamp,
                    ),
                )
        except (URLError, OSError):
            connection.execute(
                """
                INSERT INTO specialty_registry
                (curriculum_code, specialty_name, division, version, curriculum_url, import_status, imported_at, last_refreshed_at)
                VALUES (?, ?, ?, ?, ?, 'Not imported', NULL, ?)
                """,
                (
                    DEFAULT_SPECIALTY_CODE,
                    DEFAULT_SPECIALTY_NAME,
                    "Life Sciences",
                    "V1",
                    f"https://curriculumlibrary.nshcs.org.uk/hsst/specialty/{DEFAULT_SPECIALTY_CODE}/",
                    _utc_now(),
                ),
            )

    curriculum_count = connection.execute(
        "SELECT COUNT(*) FROM specialty_curriculum_items WHERE curriculum_code = ?",
        (DEFAULT_SPECIALTY_CODE,),
    ).fetchone()[0]
    if curriculum_count == 0:
        try:
            curriculum_url = f"https://curriculumlibrary.nshcs.org.uk/hsst/specialty/{DEFAULT_SPECIALTY_CODE}/"
            html_text = _fetch_html(curriculum_url)
            specialty_name_match = re.search(r'<h1 class="page__title">([^<]+)</h1>', html_text)
            page_title = _strip_tags(specialty_name_match.group(1)) if specialty_name_match else DEFAULT_SPECIALTY_NAME
            specialty_name = page_title.rsplit("[", 1)[0].strip() if "[" in page_title else page_title
            registry_df, raw_items = _parse_specialty_page(DEFAULT_SPECIALTY_CODE, specialty_name, "Life Sciences", "V1", curriculum_url, html_text)
            items_df, summary = _summarize_curriculum_rows(raw_items.to_dict(orient="records"), DEFAULT_SPECIALTY_CODE)

            if items_df.empty:
                items_df, summary = _summarize_curriculum_rows(_load_local_virology_seed().to_dict(orient="records"), DEFAULT_SPECIALTY_CODE)

            if not items_df.empty:
                items_to_store = items_df.rename(columns={
                    "CurriculumCode": "curriculum_code",
                    "ItemType": "item_type",
                    "SectionName": "section_name",
                    "CurriculumID": "curriculum_id",
                    "CurriculumText": "curriculum_text",
                    "Stage": "stage",
                    "Status": "status",
                    "NodeLabel": "node_label",
                    "ItemURL": "item_url",
                    "SourceURL": "source_url",
                    "SortOrder": "sort_order",
                }).assign(created_at=_utc_now(), updated_at=_utc_now())
                items_to_store.to_sql("specialty_curriculum_items", connection, if_exists="append", index=False)
                connection.execute(
                    """
                    UPDATE specialty_registry
                    SET specialty_name = ?, division = ?, version = ?, curriculum_url = ?, import_status = 'Imported', imported_at = ?, last_refreshed_at = ?
                    WHERE curriculum_code = ?
                    """,
                    (specialty_name, "Life Sciences", "V1", curriculum_url, _utc_now(), _utc_now(), DEFAULT_SPECIALTY_CODE),
                )
        except (URLError, OSError, ValueError):
            seed = _load_local_virology_seed()
            if not seed.empty:
                timestamp = _utc_now()
                seed.rename(columns={
                    "CurriculumCode": "curriculum_code",
                    "ItemType": "item_type",
                    "SectionName": "section_name",
                    "CurriculumID": "curriculum_id",
                    "CurriculumText": "curriculum_text",
                    "Stage": "stage",
                    "Status": "status",
                    "NodeLabel": "node_label",
                    "ItemURL": "item_url",
                    "SourceURL": "source_url",
                    "SortOrder": "sort_order",
                }).assign(created_at=timestamp, updated_at=timestamp).to_sql("specialty_curriculum_items", connection, if_exists="append", index=False)
                connection.execute(
                    """
                    INSERT INTO specialty_registry
                    (curriculum_code, specialty_name, division, version, curriculum_url, import_status, imported_at, last_refreshed_at)
                    VALUES (?, ?, ?, ?, ?, 'Imported', ?, ?)
                    ON CONFLICT(curriculum_code) DO UPDATE SET
                        import_status = 'Imported',
                        imported_at = excluded.imported_at,
                        last_refreshed_at = excluded.last_refreshed_at
                    """,
                    (
                        DEFAULT_SPECIALTY_CODE,
                        DEFAULT_SPECIALTY_NAME,
                        "Life Sciences",
                        "V1",
                        f"https://curriculumlibrary.nshcs.org.uk/hsst/specialty/{DEFAULT_SPECIALTY_CODE}/",
                        _utc_now(),
                        _utc_now(),
                    ),
                )


def _seed_reference_tables(connection: sqlite3.Connection) -> None:
    curriculum_count = connection.execute("SELECT COUNT(*) FROM curriculum_modules").fetchone()[0]
    if curriculum_count == 0:
        curriculum_file = REFERENCE_DATA_DIR / "curriculum.csv"
        if curriculum_file.exists():
            curriculum = pd.read_csv(curriculum_file, dtype=str).fillna("")
            rows = [
                (
                    str(row.get("CurriculumID", "")).strip(),
                    str(row.get("CurriculumText", "")).strip(),
                    str(row.get("Stage", "")).strip(),
                    str(row.get("Status", "")).strip(),
                    str(row.get("NodeLabel", "")).strip(),
                )
                for _, row in curriculum.iterrows()
                if str(row.get("CurriculumID", "")).strip()
            ]
            connection.executemany(
                """
                INSERT OR IGNORE INTO curriculum_modules
                (curriculum_id, curriculum_text, stage, status, node_label)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )

    sop_count = connection.execute("SELECT COUNT(*) FROM sop_criteria").fetchone()[0]
    if sop_count == 0:
        sop_file = REFERENCE_DATA_DIR / "sop.csv"
        if sop_file.exists():
            sop = pd.read_csv(sop_file, dtype=str).fillna("")
            rows = [
                (
                    str(row.get("SoPID", "")).strip(),
                    str(row.get("SoPText", "")).strip(),
                    str(row.get("StandardID", "")).strip(),
                    str(row.get("StandardText", "")).strip(),
                    str(row.get("DomainID", "")).strip(),
                    str(row.get("DomainText", "")).strip(),
                    str(row.get("CriterionNodeLabel", "")).strip(),
                    str(row.get("StandardNodeLabel", "")).strip(),
                    str(row.get("DomainNodeLabel", "")).strip(),
                )
                for _, row in sop.iterrows()
                if str(row.get("SoPID", "")).strip()
            ]
            connection.executemany(
                """
                INSERT OR IGNORE INTO sop_criteria
                (sop_id, sop_text, standard_id, standard_text, domain_id, domain_text,
                 criterion_node_label, standard_node_label, domain_node_label)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )


def _seed_evidence_tables(connection: sqlite3.Connection) -> None:
    evidence_count = connection.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0]
    if evidence_count != 0:
        return

    evidence_file = REFERENCE_DATA_DIR / "evidence.csv"
    if not evidence_file.exists():
        return

    evidence = pd.read_csv(evidence_file, dtype=str).fillna("")
    if evidence.empty:
        return

    evidence["Weight"] = pd.to_numeric(evidence.get("Weight", 1), errors="coerce").fillna(1).astype(int)
    evidence["EvidenceType"] = evidence.get("EvidenceType", "Unspecified").replace("", "Unspecified")

    item_rows = []
    mapping_rows = []
    for evidence_id, group in evidence.groupby("EOAID", sort=False):
        evidence_title = str(group.iloc[0].get("EOATitle", "")).strip()
        evidence_type = str(group.iloc[0].get("EvidenceType", "Unspecified")).strip() or "Unspecified"
        timestamp = _utc_now()

        item_rows.append((str(evidence_id).strip(), evidence_title, evidence_type, DEFAULT_SPECIALTY_CODE, timestamp, timestamp))

        for _, row in group.iterrows():
            mapping_type = str(row.get("MappingType", "")).strip()
            target_id = str(row.get("TargetID", "")).strip()
            if mapping_type not in {"Curriculum", "SoP"} or not target_id:
                continue
            mapping_rows.append(
                (
                    str(evidence_id).strip(),
                    DEFAULT_SPECIALTY_CODE,
                    mapping_type,
                    target_id,
                    int(row.get("Weight", 1) or 1),
                    timestamp,
                )
            )

    connection.executemany(
        """
        INSERT OR IGNORE INTO evidence_items
        (evidence_id, evidence_title, evidence_type, curriculum_code, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        item_rows,
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO evidence_mappings
        (evidence_id, curriculum_code, mapping_type, target_id, weight, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        mapping_rows,
    )


def load_curriculum_dataframe(curriculum_code: str | None = None) -> pd.DataFrame:
    curriculum_code = str(curriculum_code).strip() if curriculum_code else DEFAULT_SPECIALTY_CODE
    with get_connection() as connection:
        registry_row = None
        if _table_exists(connection, "specialty_registry"):
            registry_row = connection.execute(
                "SELECT import_status FROM specialty_registry WHERE curriculum_code = ?",
                (curriculum_code,),
            ).fetchone()

        if _table_exists(connection, "specialty_curriculum_items"):
            curriculum = pd.read_sql_query(
                """
                SELECT curriculum_code AS CurriculumCode,
                       item_type AS ItemType,
                       section_name AS SectionName,
                       curriculum_id AS CurriculumID,
                       curriculum_text AS CurriculumText,
                       stage AS Stage,
                       status AS Status,
                       node_label AS NodeLabel,
                       item_url AS ItemURL,
                       source_url AS SourceURL,
                       sort_order AS SortOrder,
                       created_at AS CreatedAt,
                       updated_at AS UpdatedAt
                FROM specialty_curriculum_items
                WHERE curriculum_code = ?
                ORDER BY COALESCE(sort_order, 999999), curriculum_id
                """,
                connection,
                params=(curriculum_code,),
                dtype=str,
            )
            if not curriculum.empty:
                curriculum["ItemType"] = curriculum["ItemType"].fillna("").astype(str).str.lower()
                curriculum["CurriculumID"] = curriculum["CurriculumID"].fillna("").astype(str)
                curriculum["CurriculumText"] = curriculum["CurriculumText"].fillna("").astype(str)
                curriculum = curriculum[
                    (curriculum["ItemType"] == "module")
                    & curriculum["CurriculumID"].map(_is_valid_curriculum_item_code)
                    & curriculum["CurriculumText"].str.strip().ne("")
                ].copy()
                if not curriculum.empty:
                    return curriculum

            if registry_row is not None and str(registry_row[0]).strip().lower() != "imported":
                return pd.DataFrame(columns=[
                    "CurriculumCode",
                    "ItemType",
                    "SectionName",
                    "CurriculumID",
                    "CurriculumText",
                    "Stage",
                    "Status",
                    "NodeLabel",
                    "ItemURL",
                    "SourceURL",
                    "SortOrder",
                    "CreatedAt",
                    "UpdatedAt",
                ])

        return pd.read_sql_query(
            """
            SELECT curriculum_id AS CurriculumID,
                   curriculum_text AS CurriculumText,
                   stage AS Stage,
                   status AS Status,
                   node_label AS NodeLabel
            FROM curriculum_modules
            ORDER BY curriculum_id
            """,
            connection,
            dtype=str,
        )


def load_sop_dataframe() -> pd.DataFrame:
    with get_connection() as connection:
        return pd.read_sql_query(
            """
            SELECT sop_id AS SoPID,
                   sop_text AS SoPText,
                   standard_id AS StandardID,
                   standard_text AS StandardText,
                   domain_id AS DomainID,
                   domain_text AS DomainText,
                   criterion_node_label AS CriterionNodeLabel,
                   standard_node_label AS StandardNodeLabel,
                   domain_node_label AS DomainNodeLabel
            FROM sop_criteria
            ORDER BY sop_id
            """,
            connection,
            dtype=str,
        )


def load_evidence_dataframe(curriculum_code: str | None = None) -> pd.DataFrame:
    curriculum_code = str(curriculum_code).strip() if curriculum_code else DEFAULT_SPECIALTY_CODE
    with get_connection() as connection:
        if _column_exists(connection, "evidence_items", "curriculum_code") and _column_exists(connection, "evidence_mappings", "curriculum_code"):
            evidence = pd.read_sql_query(
                """
                SELECT m.evidence_id AS EOAID,
                       i.evidence_title AS EOATitle,
                       i.evidence_type AS EvidenceType,
                       m.mapping_type AS MappingType,
                       m.target_id AS TargetID,
                       m.weight AS Weight,
                       i.curriculum_code AS CurriculumCode
                FROM evidence_mappings m
                INNER JOIN evidence_items i ON i.evidence_id = m.evidence_id
                                WHERE i.curriculum_code = ?
                                    AND m.curriculum_code = ?
                ORDER BY m.evidence_id, m.mapping_type, m.target_id
                """,
                connection,
                                params=(curriculum_code, curriculum_code),
                dtype=str,
            )
        else:
            evidence = pd.read_sql_query(
                """
                SELECT m.evidence_id AS EOAID,
                       i.evidence_title AS EOATitle,
                       i.evidence_type AS EvidenceType,
                       m.mapping_type AS MappingType,
                       m.target_id AS TargetID,
                       m.weight AS Weight
                FROM evidence_mappings m
                INNER JOIN evidence_items i ON i.evidence_id = m.evidence_id
                ORDER BY m.evidence_id, m.mapping_type, m.target_id
                """,
                connection,
                dtype=str,
            )

    if evidence.empty:
        return pd.DataFrame(columns=["EOAID", "EOATitle", "EvidenceType", "MappingType", "TargetID", "Weight"])

    evidence["Weight"] = pd.to_numeric(evidence["Weight"], errors="coerce").fillna(1).astype(int)
    evidence["EvidenceType"] = evidence["EvidenceType"].fillna("Unspecified").astype(str)
    return evidence


def load_evidence_items_dataframe(curriculum_code: str | None = None) -> pd.DataFrame:
    curriculum_code = str(curriculum_code).strip() if curriculum_code else DEFAULT_SPECIALTY_CODE
    with get_connection() as connection:
        if _column_exists(connection, "evidence_items", "curriculum_code"):
            evidence_items = pd.read_sql_query(
                """
                SELECT evidence_id AS EOAID,
                       evidence_title AS EOATitle,
                       evidence_type AS EvidenceType,
                       created_at AS CreatedAt,
                       updated_at AS UpdatedAt,
                       curriculum_code AS CurriculumCode
                FROM evidence_items
                WHERE curriculum_code = ?
                ORDER BY evidence_id
                """,
                connection,
                params=(curriculum_code,),
                dtype=str,
            )
        else:
            evidence_items = pd.read_sql_query(
                """
                SELECT evidence_id AS EOAID,
                       evidence_title AS EOATitle,
                       evidence_type AS EvidenceType,
                       created_at AS CreatedAt,
                       updated_at AS UpdatedAt
                FROM evidence_items
                ORDER BY evidence_id
                """,
                connection,
                dtype=str,
            )

    if evidence_items.empty:
        return pd.DataFrame(columns=["EOAID", "EOATitle", "EvidenceType", "CreatedAt", "UpdatedAt"])

    return evidence_items


def upsert_evidence_item(
    evidence_id: str,
    evidence_title: str,
    evidence_type: str,
    curriculum_ids: Iterable[str] | None = None,
    sop_ids: Iterable[str] | None = None,
    curriculum_code: str | None = None,
) -> None:
    evidence_id = str(evidence_id).strip()
    evidence_title = str(evidence_title).strip()
    evidence_type = str(evidence_type).strip() or "Unspecified"

    if not evidence_id or not evidence_title:
        raise ValueError("Evidence ID and title are required.")

    curriculum_code = str(curriculum_code).strip() if curriculum_code else DEFAULT_SPECIALTY_CODE
    timestamp = _utc_now()
    curriculum_ids = list(curriculum_ids or [])
    sop_ids = list(sop_ids or [])

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO evidence_items (evidence_id, evidence_title, evidence_type, curriculum_code, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_id) DO UPDATE SET
                evidence_title = excluded.evidence_title,
                evidence_type = excluded.evidence_type,
                curriculum_code = excluded.curriculum_code,
                updated_at = excluded.updated_at
            """,
            (evidence_id, evidence_title, evidence_type, curriculum_code, timestamp, timestamp),
        )

        if _column_exists(connection, "evidence_items", "curriculum_code"):
            connection.execute(
                """
                UPDATE evidence_items
                SET curriculum_code = ?
                WHERE evidence_id = ?
                """,
                (curriculum_code, evidence_id),
            )

        # Keep mappings in sync with the latest selection for this evidence item.
        connection.execute(
            """
            DELETE FROM evidence_mappings
            WHERE evidence_id = ?
            """,
            (evidence_id,),
        )

        mapping_rows = []
        for curriculum_id in curriculum_ids:
            curriculum_id = str(curriculum_id).strip()
            if curriculum_id:
                mapping_rows.append((evidence_id, curriculum_code, "Curriculum", curriculum_id, 1, timestamp))

        for sop_id in sop_ids:
            sop_id = str(sop_id).strip()
            if sop_id:
                mapping_rows.append((evidence_id, curriculum_code, "SoP", sop_id, 1, timestamp))

        if mapping_rows:
            connection.executemany(
                """
                INSERT OR IGNORE INTO evidence_mappings
                (evidence_id, curriculum_code, mapping_type, target_id, weight, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                mapping_rows,
            )


def delete_evidence_item(evidence_id: str) -> None:
    evidence_id = str(evidence_id).strip()
    if not evidence_id:
        return

    with get_connection() as connection:
        connection.execute("DELETE FROM evidence_items WHERE evidence_id = ?", (evidence_id,))


def list_evidence_file_records(evidence_id: str | None = None) -> pd.DataFrame:
    query = """
        SELECT file_id AS FileID,
               evidence_id AS EOAID,
               file_name AS FileName,
               original_path AS OriginalPath,
               stored_path AS StoredPath,
               created_at AS CreatedAt
        FROM evidence_files
    """
    params: tuple[str, ...] = ()
    if evidence_id:
        query += " WHERE evidence_id = ?"
        params = (str(evidence_id).strip(),)
    query += " ORDER BY evidence_id, file_name"

    with get_connection() as connection:
        records = pd.read_sql_query(query, connection, params=params, dtype=str)

    if records.empty:
        return pd.DataFrame(columns=["FileID", "EOAID", "FileName", "OriginalPath", "StoredPath", "CreatedAt"])

    return records


def add_evidence_file(evidence_id: str, original_path: str, stored_path: str | None = None) -> None:
    evidence_id = str(evidence_id).strip()
    original_path = str(original_path).strip()
    if not evidence_id or not original_path:
        raise ValueError("Evidence ID and original file path are required.")

    source_path = Path(original_path)
    file_name = source_path.name
    target_path = str(Path(stored_path).expanduser()) if stored_path else str(source_path.expanduser())
    timestamp = _utc_now()

    with get_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO evidence_files
            (evidence_id, file_name, original_path, stored_path, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (evidence_id, file_name, original_path, target_path, timestamp),
        )


def backup_database(backup_name: str | None = None) -> Path:
    database_path = get_database_path()
    if not database_path.exists():
        initialize_database()

    backup_dir = get_backup_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = backup_name.strip() if backup_name else f"portfolio_backup_{timestamp}.sqlite3"
    if not filename.endswith(".sqlite3"):
        filename = f"{filename}.sqlite3"

    backup_path = backup_dir / filename
    shutil.copy2(database_path, backup_path)
    return backup_path


def restore_database(backup_path: str | Path) -> Path:
    source_path = Path(backup_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Backup file not found: {source_path}")

    database_path = get_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, database_path)
    return database_path


def export_evidence_dataframe() -> pd.DataFrame:
    return load_evidence_dataframe()


def export_evidence_items_dataframe() -> pd.DataFrame:
    return load_evidence_items_dataframe()


def export_curriculum_dataframe() -> pd.DataFrame:
    return load_curriculum_dataframe()


def export_sop_dataframe() -> pd.DataFrame:
    return load_sop_dataframe()


def dataframe_to_excel_bytes() -> bytes:
    output_path = get_user_data_dir() / "portfolio_export.xlsx"
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        load_evidence_items_dataframe().to_excel(writer, sheet_name="Evidence Items", index=False)
        load_evidence_dataframe().to_excel(writer, sheet_name="Evidence Mappings", index=False)
        load_curriculum_dataframe().to_excel(writer, sheet_name="Curriculum", index=False)
        load_sop_dataframe().to_excel(writer, sheet_name="SoP Criteria", index=False)

    return output_path.read_bytes()


def dataframe_to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")