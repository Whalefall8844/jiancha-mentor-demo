from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..database import get_connection, transaction


DOCUMENT_TYPES = {"protocol", "icf", "ethics", "other"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _row(row) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    if "key_roles_json" in data:
        data["key_roles"] = json.loads(data.pop("key_roles_json") or "{}")
    return data


def _rows(rows) -> list[dict[str, Any]]:
    return [_row(row) for row in rows]


def _active_for_date(record: dict[str, Any], visit_date: str) -> bool:
    if record.get("status") != "active":
        return False
    start = str(record.get("effective_from") or "")
    end = str(record.get("effective_to") or "")
    return (not start or start <= visit_date) and (not end or end >= visit_date)


def _document_display(record: dict[str, Any]) -> str:
    parts = [str(record.get("version") or "").strip(), str(record.get("version_date") or "").strip()]
    return " / ".join(part for part in parts if part) or str(record.get("title") or "")


def _document_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id", ""),
        "document_type": record.get("document_type", ""),
        "title": record.get("title", ""),
        "version": record.get("version", ""),
        "version_date": record.get("version_date", ""),
        "effective_from": record.get("effective_from", ""),
        "effective_to": record.get("effective_to", ""),
        "source_file_name": record.get("source_file_name", ""),
        "content_hash": record.get("content_hash", ""),
        "source_reference": record.get("source_reference", ""),
        "display": _document_display(record),
    }


def list_site_master_versions(site_id: str, *, include_inactive: bool = True) -> list[dict[str, Any]]:
    condition = "" if include_inactive else "AND status = 'active'"
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM site_master_versions
            WHERE site_id = ? {condition}
            ORDER BY effective_from DESC, created_at DESC
            """,
            (site_id,),
        ).fetchall()
    return _rows(rows)


def get_site_master_version(version_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM site_master_versions WHERE id = ?", (version_id,)).fetchone()
    return _row(row)


def create_site_master_version(
    *,
    site_id: str,
    version_label: str,
    pi_name: str = "",
    site_address: str = "",
    site_team: str = "",
    key_roles: dict[str, str] | None = None,
    effective_from: str = "",
    effective_to: str = "",
    created_by: str = "项目管理员",
) -> dict[str, Any]:
    version_id = uuid4().hex
    timestamp = _now()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO site_master_versions (
                id, site_id, version_label, pi_name, site_address, site_team, key_roles_json,
                effective_from, effective_to, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                version_id,
                site_id,
                version_label.strip(),
                pi_name.strip(),
                site_address.strip(),
                site_team.strip(),
                json.dumps(key_roles or {}, ensure_ascii=False),
                effective_from.strip(),
                effective_to.strip(),
                created_by.strip(),
                timestamp,
                timestamp,
            ),
        )
    return get_site_master_version(version_id) or {}


def patch_site_master_version(version_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"version_label", "pi_name", "site_address", "site_team", "effective_from", "effective_to", "status"}
    fields = [(key, str(value).strip()) for key, value in patch.items() if key in allowed]
    if "key_roles" in patch:
        fields.append(("key_roles_json", json.dumps(patch["key_roles"] or {}, ensure_ascii=False)))
    if not fields:
        return get_site_master_version(version_id)
    fields.append(("updated_at", _now()))
    assignments = ", ".join(f"{key} = ?" for key, _ in fields)
    with transaction() as connection:
        connection.execute(f"UPDATE site_master_versions SET {assignments} WHERE id = ?", (*[value for _, value in fields], version_id))
    return get_site_master_version(version_id)


def list_controlled_documents(
    project_id: str,
    *,
    site_id: str | None = None,
    include_inactive: bool = True,
) -> list[dict[str, Any]]:
    conditions = ["project_id = ?"]
    values: list[str] = [project_id]
    if site_id:
        conditions.append("(site_id IS NULL OR site_id = ?)")
        values.append(site_id)
    if not include_inactive:
        conditions.append("status = 'active'")
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM controlled_documents
            WHERE {' AND '.join(conditions)}
            ORDER BY document_type, CASE WHEN site_id IS NULL THEN 0 ELSE 1 END DESC, effective_from DESC, created_at DESC
            """,
            values,
        ).fetchall()
    return _rows(rows)


def get_controlled_document(document_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM controlled_documents WHERE id = ?", (document_id,)).fetchone()
    return _row(row)


def create_controlled_document(
    *,
    project_id: str,
    site_id: str | None,
    document_type: str,
    title: str,
    version: str = "",
    version_date: str = "",
    effective_from: str = "",
    effective_to: str = "",
    source_file_name: str = "",
    stored_path: str = "",
    content_hash: str = "",
    source_reference: str = "",
    notes: str = "",
    created_by: str = "项目管理员",
) -> dict[str, Any]:
    normalized_type = document_type.strip().lower()
    if normalized_type not in DOCUMENT_TYPES:
        raise ValueError("受控文件类型仅支持 protocol、icf、ethics 或 other")
    document_id = uuid4().hex
    timestamp = _now()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO controlled_documents (
                id, project_id, site_id, document_type, title, version, version_date,
                effective_from, effective_to, status, source_file_name, stored_path,
                content_hash, source_reference, notes, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                project_id,
                site_id or None,
                normalized_type,
                title.strip(),
                version.strip(),
                version_date.strip(),
                effective_from.strip(),
                effective_to.strip(),
                source_file_name.strip(),
                stored_path.strip(),
                content_hash.strip(),
                source_reference.strip(),
                notes.strip(),
                created_by.strip(),
                timestamp,
                timestamp,
            ),
        )
    return get_controlled_document(document_id) or {}


def patch_controlled_document(document_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {
        "title",
        "version",
        "version_date",
        "effective_from",
        "effective_to",
        "status",
        "source_reference",
        "notes",
    }
    fields = [(key, str(value).strip()) for key, value in patch.items() if key in allowed]
    if not fields:
        return get_controlled_document(document_id)
    fields.append(("updated_at", _now()))
    assignments = ", ".join(f"{key} = ?" for key, _ in fields)
    with transaction() as connection:
        connection.execute(f"UPDATE controlled_documents SET {assignments} WHERE id = ?", (*[value for _, value in fields], document_id))
    return get_controlled_document(document_id)


def resolve_frozen_master_data(
    *,
    project_id: str,
    site_id: str,
    visit_date: str,
    connection=None,
) -> dict[str, Any]:
    own_connection = connection is None
    active_connection = connection or get_connection()
    try:
        site_row = active_connection.execute(
            "SELECT id, name, pi_name, protocol_version, icf_version, ethics_date FROM sites WHERE id = ? AND project_id = ?",
            (site_id, project_id),
        ).fetchone()
        if site_row is None:
            raise ValueError("未找到访视所属中心")
        site = dict(site_row)
        profile_rows = _rows(
            active_connection.execute(
                """
                SELECT * FROM site_master_versions
                WHERE site_id = ? AND status = 'active'
                ORDER BY effective_from DESC, created_at DESC
                """,
                (site_id,),
            ).fetchall()
        )
        profile = next((record for record in profile_rows if _active_for_date(record, visit_date)), None)
        if profile is None:
            profile = {
                "id": "",
                "version_label": "历史中心资料",
                "pi_name": site.get("pi_name", ""),
                "site_address": "",
                "site_team": "",
                "key_roles": {},
                "effective_from": "",
                "effective_to": "",
                "source": "legacy_site_fields",
            }
        else:
            profile = {
                "id": profile.get("id", ""),
                "version_label": profile.get("version_label", ""),
                "pi_name": profile.get("pi_name", ""),
                "site_address": profile.get("site_address", ""),
                "site_team": profile.get("site_team", ""),
                "key_roles": profile.get("key_roles", {}),
                "effective_from": profile.get("effective_from", ""),
                "effective_to": profile.get("effective_to", ""),
                "source": "site_master_version",
            }

        document_rows = _rows(
            active_connection.execute(
                """
                SELECT * FROM controlled_documents
                WHERE project_id = ? AND (site_id IS NULL OR site_id = ?) AND status = 'active'
                ORDER BY CASE WHEN site_id IS NULL THEN 0 ELSE 1 END DESC, effective_from DESC, created_at DESC
                """,
                (project_id, site_id),
            ).fetchall()
        )
        effective_documents = [record for record in document_rows if _active_for_date(record, visit_date)]
        documents: dict[str, dict[str, Any]] = {}
        for record in effective_documents:
            document_type = str(record.get("document_type") or "")
            if document_type not in documents:
                documents[document_type] = _document_snapshot(record)
        legacy_documents = {
            "protocol": {"document_type": "protocol", "title": "研究方案", "display": site.get("protocol_version", ""), "source": "legacy_site_fields"},
            "icf": {"document_type": "icf", "title": "知情同意书", "display": site.get("icf_version", ""), "source": "legacy_site_fields"},
            "ethics": {"document_type": "ethics", "title": "伦理批准", "display": site.get("ethics_date", ""), "source": "legacy_site_fields"},
        }
        for document_type, fallback in legacy_documents.items():
            documents.setdefault(document_type, fallback)
        return {
            "visit_date": visit_date,
            "site_profile": profile,
            "documents": documents,
            "document_list": list(documents.values()),
        }
    finally:
        if own_connection:
            active_connection.close()
