from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..database import BACKEND_DIR, transaction
from ..repositories.visits import get_attachment, list_attachments


ATTACHMENT_UPLOAD_DIR = BACKEND_DIR / "uploads" / "attachments"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def save_attachment(
    *,
    visit_id: str,
    file_name: str,
    content: bytes,
    description: str,
    created_by: str,
    action_item_id: str | None = None,
) -> dict[str, Any]:
    attachment_id = uuid4().hex
    timestamp = _now()
    suffix = Path(file_name).suffix.lower()
    stored_directory = ATTACHMENT_UPLOAD_DIR / visit_id
    stored_directory.mkdir(parents=True, exist_ok=True)
    stored_path = stored_directory / f"{attachment_id}{suffix}"

    with transaction() as connection:
        visit = connection.execute("SELECT project_id FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if visit is None:
            raise ValueError("未找到访视")
        if action_item_id:
            action_item = connection.execute(
                "SELECT id FROM action_items WHERE id = ? AND visit_id = ?",
                (action_item_id, visit_id),
            ).fetchone()
            if action_item is None:
                raise ValueError("未找到该访视的行动项")
        stored_path.write_bytes(content)
        connection.execute(
            """
            INSERT INTO attachments (id, visit_id, action_item_id, file_name, stored_path, description, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attachment_id,
                visit_id,
                action_item_id or None,
                file_name,
                str(stored_path.resolve()),
                description.strip(),
                created_by.strip() or "演示 CRA",
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO audit_events (id, project_id, visit_id, entity_type, entity_id, action, actor_name, detail_json, created_at)
            VALUES (?, ?, ?, 'attachment', ?, 'uploaded', ?, ?, ?)
            """,
            (
                uuid4().hex,
                visit["project_id"],
                visit_id,
                attachment_id,
                created_by.strip() or "演示 CRA",
                json.dumps(
                    {"file_name": file_name, "action_item_id": action_item_id or "", "description": description.strip()},
                    ensure_ascii=False,
                ),
                timestamp,
            ),
        )
    return get_attachment(attachment_id) or {}


def list_visit_attachments(visit_id: str, action_item_id: str | None = None) -> list[dict[str, Any]]:
    return list_attachments(visit_id, action_item_id)


def get_stored_attachment(attachment_id: str) -> dict[str, Any] | None:
    return get_attachment(attachment_id)
