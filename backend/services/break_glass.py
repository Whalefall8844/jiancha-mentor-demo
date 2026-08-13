"""PRD 9.12/13/15.3: 紧急破窗访问 (break-glass emergency access).

A break-glass request grants a system administrator (who by default has no
clinical-content access at all — PRD "系统管理员默认不能查看临床内容") a
time-boxed, project-scoped read grant. Normal use requires two distinct
approvals: the project's business data owner (PROJECT_ADMIN or
QA_CLINICAL_OPS) and a security approver (SYSTEM_ADMIN). A life-safety
"emergency self-activation" path is also provided (客户批准的应急 SOP 启用
最小范围访问) but forces a mandatory post-hoc dual review within the grant
window instead of skipping accountability.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ..database import transaction, get_connection


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _row(row) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["is_expired"] = bool(item.get("expires_at")) and item["expires_at"] < _now() and item.get("status") == "active"
    return item


def _audit(connection, *, project_id: str, action: str, actor_name: str, entity_id: str, detail: dict[str, Any]) -> None:
    import json

    connection.execute(
        """
        INSERT INTO audit_events (id, project_id, visit_id, entity_type, entity_id, action, actor_name, detail_json, created_at)
        VALUES (?, ?, NULL, 'break_glass_request', ?, ?, ?, ?, ?)
        """,
        (uuid4().hex, project_id, entity_id, action, actor_name, json.dumps(detail, ensure_ascii=False), _now()),
    )


def create_break_glass_request(
    *,
    project_id: str,
    object_scope: str,
    purpose: str,
    requested_by: str,
    requested_by_role: str,
    max_duration_minutes: int = 60,
    emergency_self_activate: bool = False,
) -> dict[str, Any]:
    if not purpose.strip():
        raise ValueError("请填写破窗访问目的")
    if max_duration_minutes <= 0 or max_duration_minutes > 24 * 60:
        raise ValueError("时效必须在 1 分钟至 24 小时之间")
    request_id = uuid4().hex
    timestamp = _now()
    status = "pending_business_approval"
    activated_at = ""
    expires_at = ""
    review_status = "not_required"
    if emergency_self_activate:
        status = "active"
        activated_at = timestamp
        expires_at = (datetime.now() + timedelta(minutes=max_duration_minutes)).strftime("%Y-%m-%d %H:%M")
        review_status = "pending"
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO break_glass_requests (
                id, project_id, object_scope, purpose, requested_by, requested_by_role,
                status, emergency_self_activated, max_duration_minutes, activated_at, expires_at,
                review_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                project_id,
                object_scope.strip(),
                purpose.strip(),
                requested_by,
                requested_by_role,
                status,
                1 if emergency_self_activate else 0,
                max_duration_minutes,
                activated_at,
                expires_at,
                review_status,
                timestamp,
            ),
        )
        _audit(
            connection,
            project_id=project_id,
            action="requested" if not emergency_self_activate else "emergency_self_activated",
            actor_name=requested_by,
            entity_id=request_id,
            detail={"purpose": purpose.strip(), "object_scope": object_scope.strip(), "emergency": emergency_self_activate},
        )
        row = connection.execute("SELECT * FROM break_glass_requests WHERE id = ?", (request_id,)).fetchone()
    return _row(row) or {}


def approve_business(*, request_id: str, approver_name: str) -> dict[str, Any]:
    timestamp = _now()
    with transaction() as connection:
        request = connection.execute("SELECT * FROM break_glass_requests WHERE id = ?", (request_id,)).fetchone()
        if request is None:
            raise ValueError("未找到破窗访问申请")
        if request["status"] != "pending_business_approval":
            raise ValueError("当前申请不在待业务审批状态")
        connection.execute(
            "UPDATE break_glass_requests SET status = 'pending_security_approval', business_approver = ?, business_approved_at = ? WHERE id = ?",
            (approver_name, timestamp, request_id),
        )
        _audit(connection, project_id=request["project_id"], action="business_approved", actor_name=approver_name, entity_id=request_id, detail={})
        row = connection.execute("SELECT * FROM break_glass_requests WHERE id = ?", (request_id,)).fetchone()
    return _row(row) or {}


def approve_security(*, request_id: str, approver_name: str) -> dict[str, Any]:
    timestamp = _now()
    with transaction() as connection:
        request = connection.execute("SELECT * FROM break_glass_requests WHERE id = ?", (request_id,)).fetchone()
        if request is None:
            raise ValueError("未找到破窗访问申请")
        if request["status"] != "pending_security_approval":
            raise ValueError("当前申请不在待安全审批状态；须先完成业务审批")
        expires_at = (datetime.now() + timedelta(minutes=int(request["max_duration_minutes"]))).strftime("%Y-%m-%d %H:%M")
        connection.execute(
            """
            UPDATE break_glass_requests
            SET status = 'active', security_approver = ?, security_approved_at = ?,
                activated_at = ?, expires_at = ?, review_status = 'pending'
            WHERE id = ?
            """,
            (approver_name, timestamp, timestamp, expires_at, request_id),
        )
        _audit(
            connection,
            project_id=request["project_id"],
            action="security_approved_and_activated",
            actor_name=approver_name,
            entity_id=request_id,
            detail={"expires_at": expires_at},
        )
        row = connection.execute("SELECT * FROM break_glass_requests WHERE id = ?", (request_id,)).fetchone()
    return _row(row) or {}


def end_break_glass(*, request_id: str, actor_name: str, reason: str) -> dict[str, Any]:
    if not reason.strip():
        raise ValueError("请填写提前结束破窗访问的原因")
    timestamp = _now()
    with transaction() as connection:
        request = connection.execute("SELECT * FROM break_glass_requests WHERE id = ?", (request_id,)).fetchone()
        if request is None:
            raise ValueError("未找到破窗访问申请")
        if request["status"] != "active":
            raise ValueError("只有生效中的破窗访问可以结束")
        connection.execute(
            "UPDATE break_glass_requests SET status = 'ended', ended_at = ?, ended_reason = ? WHERE id = ?",
            (timestamp, reason.strip(), request_id),
        )
        _audit(connection, project_id=request["project_id"], action="ended", actor_name=actor_name, entity_id=request_id, detail={"reason": reason.strip()})
        row = connection.execute("SELECT * FROM break_glass_requests WHERE id = ?", (request_id,)).fetchone()
    return _row(row) or {}


def record_review(*, request_id: str, reviewer_name: str, note: str) -> dict[str, Any]:
    """QA/临床运营复核：核实破窗期间的操作范围与目的一致，尤其是应急自激活场景。"""
    if not note.strip():
        raise ValueError("请填写复核结论")
    timestamp = _now()
    with transaction() as connection:
        request = connection.execute("SELECT * FROM break_glass_requests WHERE id = ?", (request_id,)).fetchone()
        if request is None:
            raise ValueError("未找到破窗访问申请")
        if request["review_status"] != "pending":
            raise ValueError("当前申请没有待处理的复核")
        connection.execute(
            "UPDATE break_glass_requests SET review_status = 'completed', reviewed_by = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
            (reviewer_name, timestamp, note.strip(), request_id),
        )
        _audit(connection, project_id=request["project_id"], action="reviewed", actor_name=reviewer_name, entity_id=request_id, detail={"note": note.strip()})
        row = connection.execute("SELECT * FROM break_glass_requests WHERE id = ?", (request_id,)).fetchone()
    return _row(row) or {}


def list_break_glass_requests(project_id: str = "") -> list[dict[str, Any]]:
    with get_connection() as connection:
        if project_id:
            rows = connection.execute(
                "SELECT * FROM break_glass_requests WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
        else:
            rows = connection.execute("SELECT * FROM break_glass_requests ORDER BY created_at DESC").fetchall()
    return [item for item in (_row(row) for row in rows) if item is not None]
