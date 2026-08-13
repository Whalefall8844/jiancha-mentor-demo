from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..database import BACKEND_DIR, transaction
from ..repositories.visits import get_attachment, list_attachments


ATTACHMENT_UPLOAD_DIR = BACKEND_DIR / "uploads" / "attachments"

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # PRD 9.1 uses the same 20 MB MVP guidance for uploads.

# Only de-identified, non-executable evidence types are in scope for MVP (PRD 5.1/9.7):
# scanned/photographed evidence, plain correspondence exports and non-macro office documents.
# Deliberately excludes .docm/.xlsm/.zip and any script/binary extension.
ALLOWED_EXTENSIONS: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".txt": (),
    ".csv": (),
    ".eml": (),
    ".docx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
}

# Signatures that indicate an executable/script disguised behind an allowed extension.
DANGEROUS_SIGNATURES: tuple[bytes, ...] = (
    b"MZ",  # Windows PE (.exe/.dll)
    b"\x7fELF",  # Linux ELF binary
    b"#!",  # shell/script shebang
    b"<script",  # embedded script in a supposedly plain-text/HTML file
)

_ID_CARD_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _detect_direct_identifiers(*texts: str) -> list[str]:
    hits: list[str] = []
    combined = "\n".join(texts)
    if _ID_CARD_PATTERN.search(combined):
        hits.append("疑似身份证号")
    if _PHONE_PATTERN.search(combined):
        hits.append("疑似手机号")
    if _EMAIL_PATTERN.search(combined):
        hits.append("疑似邮箱地址")
    return hits


def _scan_attachment(*, file_name: str, content: bytes) -> tuple[str, str, str]:
    """Return (content_type_label, scan_status, scan_notes). Raises ValueError to reject."""
    suffix = Path(file_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"不支持的附件类型「{suffix or '无扩展名'}」；MVP 仅接受脱敏证据类文件（PDF/图片/纯文本/邮件导出/不含宏的 Word・Excel）"
        )
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"附件大小超过 {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB 上限")
    if len(content) == 0:
        raise ValueError("附件内容为空")

    for signature in DANGEROUS_SIGNATURES:
        if content[:4096].startswith(signature) or signature in content[:4096]:
            raise ValueError("附件内容命中可执行文件/脚本特征，已拒绝并记录安全事件")

    expected_signatures = ALLOWED_EXTENSIONS[suffix]
    if expected_signatures and not any(content.startswith(sig) for sig in expected_signatures):
        raise ValueError("附件文件头与扩展名不一致，疑似伪装文件类型，已拒绝并记录安全事件")

    return suffix.lstrip("."), "passed", "扩展名/文件头校验通过；MVP 未接入第三方恶意软件扫描引擎，属演示级校验"


def _record_rejected_upload(*, visit_id: str, file_name: str, created_by: str, reason: str) -> None:
    """PRD §14: 拒绝上传或立即隔离...通知授权责任人并记录事件."""
    try:
        with transaction() as connection:
            visit = connection.execute("SELECT project_id FROM visits WHERE id = ?", (visit_id,)).fetchone()
            connection.execute(
                """
                INSERT INTO audit_events (id, project_id, visit_id, entity_type, entity_id, action, actor_name, detail_json, created_at)
                VALUES (?, ?, ?, 'attachment', ?, 'upload_rejected', ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    visit["project_id"] if visit else "",
                    visit_id,
                    file_name,
                    created_by.strip() or "演示 CRA",
                    json.dumps({"file_name": file_name, "reason": reason}, ensure_ascii=False),
                    _now(),
                ),
            )
    except Exception:
        pass


def save_attachment(
    *,
    visit_id: str,
    file_name: str,
    content: bytes,
    description: str,
    created_by: str,
    action_item_id: str | None = None,
    created_by_member_id: str = "",
    deidentification_ack: bool = False,
) -> dict[str, Any]:
    try:
        if not deidentification_ack:
            raise ValueError("请先勾选「本附件已脱敏，不含直接身份信息、源文件或非盲数据」声明后再上传")

        identifier_hits = _detect_direct_identifiers(description, file_name)
        if identifier_hits:
            raise ValueError(f"附件描述/文件名中检测到{'、'.join(identifier_hits)}，请先脱敏后再上传")

        content_type, scan_status, scan_notes = _scan_attachment(file_name=file_name, content=content)
    except ValueError as exc:
        _record_rejected_upload(visit_id=visit_id, file_name=file_name, created_by=created_by, reason=str(exc))
        raise
    file_hash = hashlib.sha256(content).hexdigest()

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
            INSERT INTO attachments (
                id, visit_id, action_item_id, file_name, stored_path, description, created_by, created_at,
                file_hash, content_type, size_bytes, scan_status, scan_notes, created_by_member_id, deidentification_ack
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
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
                file_hash,
                content_type,
                len(content),
                scan_status,
                scan_notes,
                created_by_member_id,
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
                    {
                        "file_name": file_name,
                        "action_item_id": action_item_id or "",
                        "description": description.strip(),
                        "file_hash": file_hash,
                        "size_bytes": len(content),
                        "scan_status": scan_status,
                    },
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
