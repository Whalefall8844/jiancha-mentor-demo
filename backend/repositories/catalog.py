from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..database import get_connection, transaction


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _row(row) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("metadata_json", "content_json"):
        if key in data:
            data[key.removesuffix("_json")] = json.loads(data.pop(key) or "{}")
    return data


def _rows(rows) -> list[dict[str, Any]]:
    return [_row(row) for row in rows]


def list_projects() -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT p.*,
                (SELECT COUNT(*) FROM sites s WHERE s.project_id = p.id) AS site_count,
                (SELECT COUNT(*) FROM visits v WHERE v.project_id = p.id) AS visit_count,
                (SELECT MAX(v.updated_at) FROM visits v WHERE v.project_id = p.id) AS last_visit_updated_at
            FROM projects p
            ORDER BY p.updated_at DESC, p.code
            """
        ).fetchall()
    return _rows(rows)


def get_project(project_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _row(row)


def get_project_by_code(code: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM projects WHERE code = ?", (code.strip(),)).fetchone()
    return _row(row)


def create_project(*, code: str, name: str, sponsor: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    project_id = uuid4().hex
    rule_pack_id = uuid4().hex
    timestamp = _now()
    payload = json.dumps(metadata or {}, ensure_ascii=False)
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO projects (id, code, name, sponsor, status, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (project_id, code.strip(), name.strip(), sponsor.strip(), payload, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO rule_packs (id, project_id, name, version, effective_from, content_json, status, created_at, updated_at)
            VALUES (?, ?, ?, 'V1.0', ?, ?, 'draft', ?, ?)
            """,
            (
                rule_pack_id,
                project_id,
                f"{code.strip()} IMV 规则包",
                timestamp[:10],
                json.dumps({"task_template": "imv_15_table", "language_style": "cn_gcp"}, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
    return get_project(project_id) or {}


def update_project(project_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"code", "name", "sponsor", "status"}
    fields = [(key, str(value).strip()) for key, value in patch.items() if key in allowed]
    metadata = patch.get("metadata")
    if metadata is not None:
        fields.append(("metadata_json", json.dumps(metadata, ensure_ascii=False)))
    if not fields:
        return get_project(project_id)
    fields.append(("updated_at", _now()))
    assignments = ", ".join(f"{key} = ?" for key, _ in fields)
    with transaction() as connection:
        connection.execute(f"UPDATE projects SET {assignments} WHERE id = ?", (*[value for _, value in fields], project_id))
    return get_project(project_id)


def list_sites(project_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT s.*,
                (SELECT COUNT(*) FROM visits v WHERE v.site_id = s.id) AS visit_count,
                (SELECT COUNT(*) FROM subject_codes sc WHERE sc.site_id = s.id) AS subject_count
            FROM sites s
            WHERE s.project_id = ?
            ORDER BY s.code
            """,
            (project_id,),
        ).fetchall()
    return _rows(rows)


def get_site(site_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
    return _row(row)


def get_site_by_project_and_code(project_id: str, code: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM sites WHERE project_id = ? AND code = ?", (project_id, code.strip())
        ).fetchone()
    return _row(row)


def create_site(*, project_id: str, code: str, name: str, pi_name: str = "", ethics_date: str = "", protocol_version: str = "", icf_version: str = "") -> dict[str, Any]:
    site_id = uuid4().hex
    timestamp = _now()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO sites (id, project_id, code, name, pi_name, ethics_date, protocol_version, icf_version, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (site_id, project_id, code.strip(), name.strip(), pi_name.strip(), ethics_date.strip(), protocol_version.strip(), icf_version.strip(), timestamp, timestamp),
        )
    return get_site(site_id) or {}


def update_site(site_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"code", "name", "pi_name", "ethics_date", "protocol_version", "icf_version", "status"}
    fields = [(key, str(value).strip()) for key, value in patch.items() if key in allowed]
    if not fields:
        return get_site(site_id)
    fields.append(("updated_at", _now()))
    assignments = ", ".join(f"{key} = ?" for key, _ in fields)
    with transaction() as connection:
        connection.execute(f"UPDATE sites SET {assignments} WHERE id = ?", (*[value for _, value in fields], site_id))
    return get_site(site_id)


def list_templates(*, include_non_active: bool = False) -> list[dict[str, Any]]:
    condition = "" if include_non_active else "WHERE status = 'active'"
    with get_connection() as connection:
        rows = connection.execute(f"SELECT * FROM templates {condition} ORDER BY name, version DESC").fetchall()
    return _rows(rows)


def get_template(template_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
    return _row(row)


def create_template(
    *,
    name: str,
    version: str,
    docx_path: str,
    table_count: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    template_id = uuid4().hex
    timestamp = _now()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO templates (id, name, version, docx_path, table_count, metadata_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (
                template_id,
                name.strip(),
                version.strip() or "V1.0",
                docx_path,
                table_count,
                json.dumps(metadata or {}, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
    return get_template(template_id) or {}


def list_template_mappings(template_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM template_mappings WHERE template_id = ? ORDER BY table_index",
            (template_id,),
        ).fetchall()
    return _rows(rows)


def get_template_mapping(template_id: str, mapping_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM template_mappings WHERE template_id = ? AND id = ?",
            (template_id, mapping_id),
        ).fetchone()
    return _row(row)


def replace_template_mappings(template_id: str, mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timestamp = _now()
    with transaction() as connection:
        connection.execute("DELETE FROM template_mappings WHERE template_id = ?", (template_id,))
        for position, mapping in enumerate(mappings, start=1):
            table_index = int(mapping.get("table_index", position))
            connection.execute(
                """
                INSERT INTO template_mappings (id, template_id, table_index, field_key, target_description, required, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    template_id,
                    table_index,
                    str(mapping.get("field_key") or f"table_{table_index}").strip(),
                    str(mapping.get("target_description") or f"表 {table_index}").strip(),
                    1 if mapping.get("required") else 0,
                    timestamp,
                ),
            )
    return list_template_mappings(template_id)


def update_template_mapping(template_id: str, mapping_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    fields: list[tuple[str, Any]] = []
    for key in ("field_key", "target_description"):
        if key in patch:
            fields.append((key, str(patch[key]).strip()))
    if "required" in patch:
        fields.append(("required", 1 if patch["required"] else 0))
    if not fields:
        return get_template_mapping(template_id, mapping_id)

    with transaction() as connection:
        template = connection.execute("SELECT status FROM templates WHERE id = ?", (template_id,)).fetchone()
        if template is None:
            return None
        if template["status"] not in {"draft", "rejected"}:
            raise ValueError("仅草稿或已退回模板可修改映射；已提交或已启用版本请新建草稿版本")
        assignments = ", ".join(f"{key} = ?" for key, _ in fields)
        cursor = connection.execute(
            f"UPDATE template_mappings SET {assignments} WHERE template_id = ? AND id = ?",
            (*[value for _, value in fields], template_id, mapping_id),
        )
        if cursor.rowcount:
            connection.execute("UPDATE templates SET updated_at = ? WHERE id = ?", (_now(), template_id))
    return get_template_mapping(template_id, mapping_id)


def list_template_field_slots(template_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM template_field_slots WHERE template_id = ? ORDER BY target_kind, table_index, created_at, id",
            (template_id,),
        ).fetchall()
    return _rows(rows)


def _require_editable_template(connection, template_id: str) -> bool:
    template = connection.execute("SELECT status FROM templates WHERE id = ?", (template_id,)).fetchone()
    if template is None:
        return False
    if template["status"] not in {"draft", "rejected"}:
        raise ValueError("仅草稿或已退回模板可修改报告填写位；已提交或已启用版本请新建草稿版本")
    return True


def create_template_field_slot(template_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    timestamp = _now()
    slot_id = uuid4().hex
    table_index = int(payload.get("table_index") or 0)
    target_kind = str(payload.get("target_kind") or "table_cell").strip() or "table_cell"
    with transaction() as connection:
        if not _require_editable_template(connection, template_id):
            return None
        connection.execute(
            """
            INSERT INTO template_field_slots (
                id, template_id, table_index, target_kind, label, field_key, target_locator, value_source, required, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slot_id,
                template_id,
                table_index,
                target_kind,
                str(payload.get("label") or (f"表 {table_index} 填写位" if table_index else "报告填写位")).strip(),
                str(payload.get("field_key") or f"table_{table_index}").strip(),
                str(payload.get("target_locator") or "").strip(),
                str(payload.get("value_source") or "confirmed_text").strip(),
                1 if payload.get("required") else 0,
                timestamp,
            ),
        )
        connection.execute("UPDATE templates SET updated_at = ? WHERE id = ?", (timestamp, template_id))
        row = connection.execute("SELECT * FROM template_field_slots WHERE id = ?", (slot_id,)).fetchone()
    return _row(row)


def replace_template_field_slots(template_id: str, slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timestamp = _now()
    with transaction() as connection:
        connection.execute("DELETE FROM template_field_slots WHERE template_id = ?", (template_id,))
        for position, slot in enumerate(slots, start=1):
            target_kind = str(slot.get("target_kind") or "table_cell").strip() or "table_cell"
            table_index = int(slot.get("table_index") or (position if target_kind == "table_cell" else 0))
            connection.execute(
                """
                INSERT INTO template_field_slots (
                    id, template_id, table_index, target_kind, label, field_key, target_locator, value_source, required, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    template_id,
                    table_index,
                    target_kind,
                    str(slot.get("label") or (f"表 {table_index} 填写位" if table_index else "报告填写位")).strip(),
                    str(slot.get("field_key") or f"table_{table_index}").strip(),
                    str(slot.get("target_locator") or "").strip(),
                    str(slot.get("value_source") or "confirmed_text").strip(),
                    1 if slot.get("required") else 0,
                    timestamp,
                ),
            )
    return list_template_field_slots(template_id)


def update_template_field_slot(template_id: str, slot_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    fields: list[tuple[str, Any]] = []
    for key in ("table_index", "target_kind", "label", "field_key", "target_locator", "value_source"):
        if key in patch:
            value = int(patch[key]) if key == "table_index" else str(patch[key]).strip()
            fields.append((key, value))
    if "required" in patch:
        fields.append(("required", 1 if patch["required"] else 0))
    with transaction() as connection:
        if not _require_editable_template(connection, template_id):
            return None
        if fields:
            assignments = ", ".join(f"{key} = ?" for key, _ in fields)
            cursor = connection.execute(
                f"UPDATE template_field_slots SET {assignments} WHERE template_id = ? AND id = ?",
                (*[value for _, value in fields], template_id, slot_id),
            )
            if cursor.rowcount:
                connection.execute("UPDATE templates SET updated_at = ? WHERE id = ?", (_now(), template_id))
        row = connection.execute("SELECT * FROM template_field_slots WHERE id = ? AND template_id = ?", (slot_id, template_id)).fetchone()
    return _row(row)


def delete_template_field_slot(template_id: str, slot_id: str) -> bool:
    with transaction() as connection:
        if not _require_editable_template(connection, template_id):
            return False
        cursor = connection.execute(
            "DELETE FROM template_field_slots WHERE template_id = ? AND id = ?", (template_id, slot_id)
        )
        if cursor.rowcount:
            connection.execute("UPDATE templates SET updated_at = ? WHERE id = ?", (_now(), template_id))
    return bool(cursor.rowcount)


def update_template_control(template_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"status", "submitted_at", "submitted_by", "reviewed_at", "reviewed_by", "review_note"}
    fields = [(key, str(value).strip()) for key, value in patch.items() if key in allowed]
    if "metadata" in patch:
        fields.append(("metadata_json", json.dumps(patch["metadata"], ensure_ascii=False)))
    if not fields:
        return get_template(template_id)
    fields.append(("updated_at", _now()))
    assignments = ", ".join(f"{key} = ?" for key, _ in fields)
    with transaction() as connection:
        connection.execute(f"UPDATE templates SET {assignments} WHERE id = ?", (*[value for _, value in fields], template_id))
    return get_template(template_id)


def update_template_document(
    template_id: str,
    *,
    docx_path: str,
    table_count: int,
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    with transaction() as connection:
        template = connection.execute("SELECT status FROM templates WHERE id = ?", (template_id,)).fetchone()
        if template is None:
            return None
        if template["status"] not in {"draft", "rejected"}:
            raise ValueError("仅修订草稿或已退回模板可替换 Word 文件")
        connection.execute(
            """
            UPDATE templates
            SET docx_path = ?, table_count = ?, metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (docx_path, table_count, json.dumps(metadata, ensure_ascii=False), _now(), template_id),
        )
    return get_template(template_id)


def list_rule_packs(project_id: str, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    condition = "project_id = ?" if include_inactive else "project_id = ? AND status = 'active'"
    with get_connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM rule_packs WHERE {condition} ORDER BY effective_from DESC, version DESC",
            (project_id,),
        ).fetchall()
    return _rows(rows)


def get_rule_pack(rule_pack_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM rule_packs WHERE id = ?", (rule_pack_id,)).fetchone()
    return _row(row)


def create_rule_pack(
    *,
    project_id: str,
    name: str,
    version: str,
    effective_from: str = "",
    effective_to: str = "",
    content: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rule_pack_id = uuid4().hex
    timestamp = _now()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO rule_packs (id, project_id, name, version, effective_from, effective_to, content_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (
                rule_pack_id,
                project_id,
                name.strip(),
                version.strip() or "V1.0",
                effective_from.strip(),
                effective_to.strip(),
                json.dumps(content or {}, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
    return get_rule_pack(rule_pack_id) or {}


def update_rule_pack(rule_pack_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"name", "version", "effective_from", "effective_to"}
    fields = [(key, str(value).strip()) for key, value in patch.items() if key in allowed]
    if "content" in patch:
        fields.append(("content_json", json.dumps(patch["content"], ensure_ascii=False)))
    if not fields:
        return get_rule_pack(rule_pack_id)
    fields.append(("updated_at", _now()))
    assignments = ", ".join(f"{key} = ?" for key, _ in fields)
    with transaction() as connection:
        rule_pack = connection.execute("SELECT status FROM rule_packs WHERE id = ?", (rule_pack_id,)).fetchone()
        if rule_pack is None:
            return None
        if rule_pack["status"] not in {"draft", "rejected"}:
            raise ValueError("仅草稿或已退回规则包可编辑；已提交或已启用版本请新建草稿版本")
        connection.execute(f"UPDATE rule_packs SET {assignments} WHERE id = ?", (*[value for _, value in fields], rule_pack_id))
    return get_rule_pack(rule_pack_id)


def update_rule_pack_control(rule_pack_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"status", "submitted_at", "submitted_by", "reviewed_at", "reviewed_by", "review_note"}
    fields = [(key, str(value).strip()) for key, value in patch.items() if key in allowed]
    if not fields:
        return get_rule_pack(rule_pack_id)
    fields.append(("updated_at", _now()))
    assignments = ", ".join(f"{key} = ?" for key, _ in fields)
    with transaction() as connection:
        connection.execute(f"UPDATE rule_packs SET {assignments} WHERE id = ?", (*[value for _, value in fields], rule_pack_id))
    return get_rule_pack(rule_pack_id)


def create_configuration_audit_event(
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    actor_name: str,
    detail: dict[str, Any] | None = None,
    project_id: str = "",
) -> None:
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO configuration_audit_events (id, entity_type, entity_id, project_id, action, actor_name, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                entity_type,
                entity_id,
                project_id,
                action,
                actor_name.strip() or "系统",
                json.dumps(detail or {}, ensure_ascii=False),
                _now(),
            ),
        )


def list_subject_codes(site_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM subject_codes WHERE site_id = ? ORDER BY code", (site_id,)).fetchall()
    return _rows(rows)


def save_subject_codes(site_id: str, subject_codes: list[dict[str, str]]) -> list[dict[str, Any]]:
    timestamp = _now()
    with transaction() as connection:
        for item in subject_codes:
            code = item.get("code", "").strip().upper()
            if not code:
                continue
            status = item.get("enrollment_status", "screening").strip() or "screening"
            existing = connection.execute(
                "SELECT id FROM subject_codes WHERE site_id = ? AND code = ?", (site_id, code)
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE subject_codes SET enrollment_status = ?, updated_at = ? WHERE id = ?",
                    (status, timestamp, existing["id"]),
                )
            else:
                connection.execute(
                    "INSERT INTO subject_codes (id, site_id, code, enrollment_status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (uuid4().hex, site_id, code, status, timestamp, timestamp),
                )
    return list_subject_codes(site_id)


def list_project_members(project_id: str, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    condition = "project_id = ?" if include_inactive else "project_id = ? AND status = 'active'"
    with get_connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM project_members WHERE {condition} ORDER BY status, role, display_name",
            (project_id,),
        ).fetchall()
    return _rows(rows)


def get_project_member(project_id: str, member_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM project_members WHERE project_id = ? AND id = ?",
            (project_id, member_id),
        ).fetchone()
    return _row(row)


def create_project_member(*, project_id: str, display_name: str, role: str) -> dict[str, Any]:
    member_id = uuid4().hex
    timestamp = _now()
    with transaction() as connection:
        connection.execute(
            "INSERT INTO project_members (id, project_id, display_name, role, status, created_at) VALUES (?, ?, ?, ?, 'active', ?)",
            (member_id, project_id, display_name.strip(), role.strip(), timestamp),
        )
    return get_project_member(project_id, member_id) or {}


def update_project_member(project_id: str, member_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"display_name", "role", "status"}
    fields = [(key, str(value).strip()) for key, value in patch.items() if key in allowed]
    if not fields:
        return get_project_member(project_id, member_id)
    assignments = ", ".join(f"{key} = ?" for key, _ in fields)
    with transaction() as connection:
        connection.execute(
            f"UPDATE project_members SET {assignments} WHERE project_id = ? AND id = ?",
            (*[value for _, value in fields], project_id, member_id),
        )
    return get_project_member(project_id, member_id)


def get_setting(key: str, default: str = "") -> str:
    with get_connection() as connection:
        row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    timestamp = _now()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, timestamp),
        )
