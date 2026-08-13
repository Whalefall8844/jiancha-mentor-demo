from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from ..database import get_connection, transaction
from ..repositories.visits import bulk_update_tasks
from .escalation_sla import build_sla_snapshot, calculate_sla_due_at, describe_sla_state
from .monitoring import add_work_record


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _row(row) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    if "payload_json" in result:
        result["payload"] = json.loads(result.pop("payload_json") or "{}")
    if "sla_snapshot_json" in result:
        result["sla_snapshot"] = json.loads(result.pop("sla_snapshot_json") or "{}")
    return result


def _rows(rows) -> list[dict[str, Any]]:
    return [_row(row) for row in rows]


def _require_visit(connection, visit_id: str):
    visit = connection.execute(
        "SELECT id, project_id, cra_name, status, updated_at, snapshot_json FROM visits WHERE id = ?",
        (visit_id,),
    ).fetchone()
    if visit is None:
        raise ValueError("未找到当前访视")
    return visit


def _frozen_rule_pack(visit) -> dict[str, Any]:
    snapshot = json.loads(visit["snapshot_json"] or "{}")
    return dict(snapshot.get("rule_pack") or {})


def _with_sla_status(escalation: dict[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any] | None:
    if escalation is None:
        return None
    escalation["sla"] = describe_sla_state(escalation, now=now)
    return escalation


def _synchronize_overdue_escalations(connection, visit_id: str) -> None:
    """Route each unreceived, expired SLA item once inside the existing in-app queue."""
    visit = _require_visit(connection, visit_id)
    timestamp = _now()
    observed_at = datetime.strptime(timestamp, "%Y-%m-%d %H:%M")
    rows = connection.execute(
        """
        SELECT *
        FROM operation_escalations
        WHERE visit_id = ?
          AND status = 'open'
          AND sla_due_at <> ''
          AND overdue_escalated_at = ''
        """,
        (visit_id,),
    ).fetchall()
    for row in rows:
        escalation = _row(row) or {}
        sla = describe_sla_state(escalation, now=observed_at)
        if sla["state"] != "overdue_escalated":
            continue
        target_role = str(sla.get("overdue_target_role") or "").strip()
        if not target_role:
            continue
        previous_target_role = str(escalation.get("target_role") or "")
        connection.execute(
            """
            UPDATE operation_escalations
            SET target_role = ?, overdue_escalated_at = ?, overdue_escalated_to = ?
            WHERE id = ?
            """,
            (target_role, timestamp, target_role, escalation["id"]),
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="operation_escalation",
            entity_id=escalation["id"],
            action="sla_overdue_escalated",
            actor_name="系统 SLA 路由",
            detail={
                "previous_target_role": previous_target_role,
                "target_role": target_role,
                "sla_due_at": escalation.get("sla_due_at", ""),
                "sla_snapshot": escalation.get("sla_snapshot", {}),
            },
        )


def _sync_token(connection, visit_id: str) -> str:
    visit = _require_visit(connection, visit_id)
    counts = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM audit_events WHERE visit_id = ?) AS audit_count,
            (SELECT COUNT(*) FROM work_records WHERE visit_id = ?) AS record_count,
            (SELECT COUNT(*) FROM confirmed_fields WHERE visit_id = ?) AS confirmed_count,
            (SELECT COUNT(*) FROM action_items WHERE visit_id = ?) AS action_count
        """,
        (visit_id, visit_id, visit_id, visit_id),
    ).fetchone()
    return f"{visit['updated_at']}|{counts['audit_count']}|{counts['record_count']}|{counts['confirmed_count']}|{counts['action_count']}"


def get_visit_sync_token(visit_id: str) -> str:
    with get_connection() as connection:
        return _sync_token(connection, visit_id)


def _audit(
    connection,
    *,
    project_id: str,
    visit_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    actor_name: str,
    detail: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO audit_events (id, project_id, visit_id, entity_type, entity_id, action, actor_name, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid4().hex,
            project_id,
            visit_id,
            entity_type,
            entity_id,
            action,
            actor_name,
            json.dumps(detail, ensure_ascii=False),
            _now(),
        ),
    )


def _get_draft(connection, draft_id: str) -> dict[str, Any] | None:
    return _row(connection.execute("SELECT * FROM offline_drafts WHERE id = ?", (draft_id,)).fetchone())


def _get_conflict(connection, conflict_id: str) -> dict[str, Any] | None:
    return _row(connection.execute("SELECT * FROM sync_conflicts WHERE id = ?", (conflict_id,)).fetchone())


def list_offline_drafts(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM offline_drafts WHERE visit_id = ? ORDER BY updated_at DESC, created_at DESC",
            (visit_id,),
        ).fetchall()
    return _rows(rows)


def list_sync_conflicts(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM sync_conflicts WHERE visit_id = ? ORDER BY created_at DESC",
            (visit_id,),
        ).fetchall()
    return _rows(rows)


def sync_offline_draft(
    *,
    visit_id: str,
    client_id: str,
    payload: dict[str, str],
    base_updated_at: str,
    actor_name: str,
) -> dict[str, Any]:
    text = str(payload.get("text", "")).strip()
    if not text:
        raise ValueError("离线草稿不能为空")

    draft_id = uuid4().hex
    timestamp = _now()
    with transaction() as connection:
        visit = _require_visit(connection, visit_id)
        current_token = _sync_token(connection, visit_id)
        connection.execute(
            """
            INSERT INTO offline_drafts (id, visit_id, client_id, payload_json, base_updated_at, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (draft_id, visit_id, client_id.strip(), json.dumps({"text": text}, ensure_ascii=False), base_updated_at, timestamp, timestamp),
        )
        if base_updated_at != current_token:
            conflict_id = uuid4().hex
            server_value = f"服务器工作区已更新：{visit['updated_at']}；同步版本 {current_token}"
            connection.execute(
                """
                INSERT INTO sync_conflicts (id, visit_id, draft_id, field_key, local_value, server_value, status, created_at)
                VALUES (?, ?, ?, 'work_record', ?, ?, 'open', ?)
                """,
                (conflict_id, visit_id, draft_id, text, server_value, timestamp),
            )
            connection.execute(
                "UPDATE offline_drafts SET status = 'conflict', updated_at = ? WHERE id = ?",
                (timestamp, draft_id),
            )
            _audit(
                connection,
                project_id=visit["project_id"],
                visit_id=visit_id,
                entity_type="offline_draft",
                entity_id=draft_id,
                action="conflict_created",
                actor_name=actor_name,
                detail={"conflict_id": conflict_id, "base_updated_at": base_updated_at, "current_token": current_token},
            )
            return {
                "status": "conflict",
                "draft": _get_draft(connection, draft_id),
                "conflict": _get_conflict(connection, conflict_id),
            }

    record_result = add_work_record(visit_id=visit_id, text=text, created_by=actor_name, record_kind="offline_sync")
    with transaction() as connection:
        visit = _require_visit(connection, visit_id)
        connection.execute(
            "UPDATE offline_drafts SET status = 'synced', updated_at = ? WHERE id = ?",
            (_now(), draft_id),
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="offline_draft",
            entity_id=draft_id,
            action="synced",
            actor_name=actor_name,
            detail={"record_id": record_result["record"]["id"]},
        )
        draft = _get_draft(connection, draft_id)
    return {"status": "synced", "draft": draft, "record": record_result["record"], "suggestions": record_result["suggestions"]}


def resolve_sync_conflict(
    *,
    visit_id: str,
    conflict_id: str,
    resolution: Literal["local", "server"],
    actor_name: str,
) -> dict[str, Any]:
    with get_connection() as connection:
        conflict = _get_conflict(connection, conflict_id)
        if conflict is None or conflict["visit_id"] != visit_id:
            raise ValueError("未找到该访视的同步冲突")
        if conflict["status"] != "open":
            raise ValueError("该同步冲突已处理")
        draft = _get_draft(connection, conflict["draft_id"])
        if draft is None:
            raise ValueError("未找到关联的离线草稿")

    record_result: dict[str, Any] | None = None
    if resolution == "local":
        record_result = add_work_record(
            visit_id=visit_id,
            text=str(draft["payload"].get("text", "")),
            created_by=actor_name,
            record_kind="offline_conflict_resolved",
        )

    timestamp = _now()
    with transaction() as connection:
        visit = _require_visit(connection, visit_id)
        connection.execute(
            "UPDATE sync_conflicts SET status = 'resolved', resolved_at = ? WHERE id = ?",
            (timestamp, conflict_id),
        )
        connection.execute(
            "UPDATE offline_drafts SET status = ?, updated_at = ? WHERE id = ?",
            ("synced" if resolution == "local" else "discarded", timestamp, draft["id"]),
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="sync_conflict",
            entity_id=conflict_id,
            action=f"resolved_{resolution}",
            actor_name=actor_name,
            detail={"draft_id": draft["id"], "record_id": record_result["record"]["id"] if record_result else None},
        )
        resolved = _get_conflict(connection, conflict_id)
    return {"status": "resolved", "resolution": resolution, "conflict": resolved, "record": record_result["record"] if record_result else None}


def _parse_due_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def get_visit_operations(visit_id: str) -> dict[str, Any]:
    today = date.today()
    observed_at = datetime.now()
    with transaction() as connection:
        visit = _require_visit(connection, visit_id)
        _synchronize_overdue_escalations(connection, visit_id)
        action_rows = connection.execute(
            "SELECT * FROM action_items WHERE visit_id = ? AND status != 'closed' ORDER BY due_date, created_at",
            (visit_id,),
        ).fetchall()
        missing_rows = connection.execute(
            "SELECT * FROM visit_tasks WHERE visit_id = ? AND status = '待补录' ORDER BY table_index",
            (visit_id,),
        ).fetchall()
        escalation_rows = connection.execute(
            """
            SELECT escalation.*, action.title AS action_title
            FROM operation_escalations escalation
            LEFT JOIN action_items action ON action.id = escalation.action_item_id
            WHERE escalation.visit_id = ?
            ORDER BY
                CASE escalation.status WHEN 'open' THEN 0 WHEN 'acknowledged' THEN 1 ELSE 2 END,
                escalation.created_at DESC
            """,
            (visit_id,),
        ).fetchall()
        handover_rows = connection.execute(
            """
            SELECT handover.*, origin.display_name AS from_member_name, target.display_name AS to_member_name
            FROM visit_handovers handover
            LEFT JOIN project_members origin ON origin.id = handover.from_member_id
            JOIN project_members target ON target.id = handover.to_member_id
            WHERE handover.visit_id = ?
            ORDER BY handover.created_at DESC
            """,
            (visit_id,),
        ).fetchall()

    overdue: list[dict[str, Any]] = []
    due_soon: list[dict[str, Any]] = []
    for action in _rows(action_rows):
        due = _parse_due_date(action.get("due_date", ""))
        if due is None:
            continue
        if due < today:
            overdue.append(action)
        elif due <= today + timedelta(days=3):
            due_soon.append(action)

    return {
        "visit_id": visit_id,
        "project_id": visit["project_id"],
        "as_of": today.isoformat(),
        "overdue_actions": overdue,
        "due_soon_actions": due_soon,
        "missing_tasks": _rows(missing_rows),
        "escalations": [_with_sla_status(item, now=observed_at) for item in _rows(escalation_rows)],
        "handovers": _rows(handover_rows),
    }


def create_escalation(
    *,
    visit_id: str,
    action_item_id: str | None,
    title: str,
    description: str,
    severity: str,
    target_role: str,
    actor_name: str,
) -> dict[str, Any]:
    escalation_id = uuid4().hex
    timestamp = _now()
    with transaction() as connection:
        visit = _require_visit(connection, visit_id)
        frozen_rule_pack = _frozen_rule_pack(visit)
        sla_snapshot = build_sla_snapshot(
            rule_content=frozen_rule_pack.get("content") or {},
            severity=severity,
            fallback_target_role=target_role,
            rule_pack=frozen_rule_pack,
        )
        actual_target_role = str(sla_snapshot["initial_target_role"] or target_role)
        sla_due_at = calculate_sla_due_at(timestamp, sla_snapshot)
        action = None
        if action_item_id:
            action = connection.execute(
                "SELECT * FROM action_items WHERE id = ? AND visit_id = ?",
                (action_item_id, visit_id),
            ).fetchone()
            if action is None:
                raise ValueError("未找到需升级的行动项")
        actual_title = title.strip() or (f"紧急升级：{action['title']}" if action else "需要人工升级的监查事项")
        actual_description = description.strip() or (action["description"] if action else "请 PM/LM 依据项目 SOP 介入处理。")
        connection.execute(
            """
            INSERT INTO operation_escalations (
                id, project_id, visit_id, action_item_id, title, description, severity, target_role,
                sla_snapshot_json, sla_due_at, status, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                escalation_id,
                visit["project_id"],
                visit_id,
                action_item_id,
                actual_title,
                actual_description,
                severity,
                actual_target_role,
                json.dumps(sla_snapshot, ensure_ascii=False),
                sla_due_at,
                actor_name,
                timestamp,
            ),
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="operation_escalation",
            entity_id=escalation_id,
            action="created",
            actor_name=actor_name,
            detail={
                "action_item_id": action_item_id,
                "severity": severity,
                "requested_target_role": target_role,
                "target_role": actual_target_role,
                "sla_snapshot": sla_snapshot,
                "sla_due_at": sla_due_at,
            },
        )
        row = connection.execute("SELECT * FROM operation_escalations WHERE id = ?", (escalation_id,)).fetchone()
    return _with_sla_status(_row(row)) or {}


def dispose_escalation(
    *,
    visit_id: str,
    escalation_id: str,
    action: Literal["acknowledge", "close"],
    note: str,
    actor_name: str,
) -> dict[str, Any]:
    timestamp = _now()
    normalized_note = note.strip()
    with transaction() as connection:
        visit = _require_visit(connection, visit_id)
        _synchronize_overdue_escalations(connection, visit_id)
        escalation = connection.execute(
            "SELECT * FROM operation_escalations WHERE id = ? AND visit_id = ?",
            (escalation_id, visit_id),
        ).fetchone()
        if escalation is None:
            raise ValueError("未找到该访视的升级待办")
        if action == "acknowledge":
            connection.execute(
                """
                UPDATE operation_escalations
                SET status = 'acknowledged', acknowledged_at = ?, acknowledged_by = ?, acknowledgement_note = ?
                WHERE id = ?
                """,
                (timestamp, actor_name.strip(), normalized_note, escalation_id),
            )
            audit_action = "acknowledged"
            audit_detail = {"previous_status": escalation["status"], "acknowledgement_note": normalized_note}
        else:
            fields = [
                ("status", "closed"),
                ("closed_at", timestamp),
                ("closed_by", actor_name.strip()),
                ("resolution_note", normalized_note),
            ]
            if not str(escalation["acknowledged_at"] or "").strip():
                fields.extend(
                    [
                        ("acknowledged_at", timestamp),
                        ("acknowledged_by", actor_name.strip()),
                    ]
                )
            assignments = ", ".join(f"{name} = ?" for name, _ in fields)
            connection.execute(
                f"UPDATE operation_escalations SET {assignments} WHERE id = ?",
                (*[value for _, value in fields], escalation_id),
            )
            audit_action = "closed"
            audit_detail = {"previous_status": escalation["status"], "resolution_note": normalized_note}
        row = connection.execute("SELECT * FROM operation_escalations WHERE id = ?", (escalation_id,)).fetchone()
        updated = _with_sla_status(_row(row)) or {}
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="operation_escalation",
            entity_id=escalation_id,
            action=audit_action,
            actor_name=actor_name,
            detail={
                **audit_detail,
                "sla": updated.get("sla", {}),
                "sla_due_at": updated.get("sla_due_at", ""),
                "acknowledged_at": updated.get("acknowledged_at", ""),
            },
        )
    return updated


def create_administrator_visit_handover(
    *,
    visit_id: str,
    from_member_id: str,
    to_member_id: str,
    reason: str,
    authorization_basis: str,
    note: str,
    actor_name: str,
) -> dict[str, Any]:
    """Move an unsubmitted visit to an active CRA while retaining the manager's authority basis."""
    handover_id = uuid4().hex
    timestamp = _now()
    with transaction() as connection:
        visit = _require_visit(connection, visit_id)
        if visit["status"] not in {"draft", "returned"}:
            raise ValueError("管理员授权交接仅适用于尚未提交的草稿或退回访视")
        source = connection.execute(
            "SELECT * FROM project_members WHERE id = ? AND project_id = ?",
            (from_member_id, visit["project_id"]),
        ).fetchone()
        if source is None or source["role"] != "CRA":
            raise ValueError("原负责人员必须是当前项目中的 CRA")
        target = connection.execute(
            "SELECT * FROM project_members WHERE id = ? AND project_id = ? AND status = 'active'",
            (to_member_id, visit["project_id"]),
        ).fetchone()
        if target is None or target["role"] != "CRA":
            raise ValueError("接收人必须是当前项目的有效 CRA")
        if source["id"] == target["id"]:
            raise ValueError("接收 CRA 不能与原负责 CRA 相同")
        if str(visit["cra_name"] or "").strip() and source["display_name"] != visit["cra_name"]:
            raise ValueError("原负责 CRA 与当前访视负责人不一致，请先核对访视归属")
        connection.execute(
            """
            INSERT INTO visit_handovers (
                id, project_id, visit_id, from_member_id, to_member_id, note,
                handover_mode, authorization_basis, reason, status, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'administrator_authorized', ?, ?, 'pending_recipient_confirmation', ?, ?)
            """,
            (
                handover_id,
                visit["project_id"],
                visit_id,
                source["id"],
                target["id"],
                note.strip(),
                authorization_basis.strip(),
                reason.strip(),
                actor_name,
                timestamp,
            ),
        )
        connection.execute(
            "UPDATE visits SET cra_name = ?, updated_at = ? WHERE id = ?",
            (target["display_name"], timestamp, visit_id),
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="visit_handover",
            entity_id=handover_id,
            action="administrator_authorized",
            actor_name=actor_name,
            detail={
                "from_member_id": source["id"],
                "to_member_id": target["id"],
                "to_member_name": target["display_name"],
                "reason": reason.strip(),
                "authorization_basis": authorization_basis.strip(),
            },
        )
        row = connection.execute(
            """
            SELECT handover.*, origin.display_name AS from_member_name, target.display_name AS to_member_name
            FROM visit_handovers handover
            LEFT JOIN project_members origin ON origin.id = handover.from_member_id
            JOIN project_members target ON target.id = handover.to_member_id
            WHERE handover.id = ?
            """,
            (handover_id,),
        ).fetchone()
    return _row(row) or {}


def acknowledge_administrator_visit_handover(
    *,
    visit_id: str,
    handover_id: str,
    acknowledgement_note: str,
    actor_name: str,
) -> dict[str, Any]:
    """Record the receiving CRA's re-check confirmation without rewriting prior work."""
    timestamp = _now()
    with transaction() as connection:
        visit = _require_visit(connection, visit_id)
        row = connection.execute(
            "SELECT * FROM visit_handovers WHERE id = ? AND visit_id = ?",
            (handover_id, visit_id),
        ).fetchone()
        if row is None:
            raise ValueError("未找到当前访视的管理员交接记录")
        handover = _row(row) or {}
        if handover.get("handover_mode") != "administrator_authorized":
            raise ValueError("只有管理员授权交接需要接收 CRA 确认")
        if handover.get("status") != "pending_recipient_confirmation":
            raise ValueError("该管理员交接已完成接收确认")
        target = connection.execute(
            "SELECT * FROM project_members WHERE id = ? AND project_id = ? AND status = 'active'",
            (handover["to_member_id"], visit["project_id"]),
        ).fetchone()
        if target is None or target["role"] != "CRA":
            raise ValueError("接收 CRA 已不再是当前项目的有效成员")
        connection.execute(
            """
            UPDATE visit_handovers
            SET status = 'completed', acknowledged_at = ?, acknowledged_by = ?, acknowledgement_note = ?
            WHERE id = ?
            """,
            (timestamp, actor_name, acknowledgement_note.strip(), handover_id),
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="visit_handover",
            entity_id=handover_id,
            action="recipient_confirmed",
            actor_name=actor_name,
            detail={"acknowledgement_note": acknowledgement_note.strip(), "to_member_id": handover["to_member_id"]},
        )
        updated = connection.execute(
            """
            SELECT handover.*, origin.display_name AS from_member_name, target.display_name AS to_member_name
            FROM visit_handovers handover
            LEFT JOIN project_members origin ON origin.id = handover.from_member_id
            JOIN project_members target ON target.id = handover.to_member_id
            WHERE handover.id = ?
            """,
            (handover_id,),
        ).fetchone()
    return _row(updated) or {}


def bulk_complete_visit_tasks(
    *,
    visit_id: str,
    task_ids: list[str],
    status: str,
    evidence: str,
    actor_name: str,
) -> list[dict[str, Any]]:
    updated_tasks = bulk_update_tasks(visit_id, task_ids=task_ids, status=status.strip(), evidence=evidence.strip())
    with transaction() as connection:
        visit = _require_visit(connection, visit_id)
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="visit_task",
            entity_id="batch",
            action="bulk_updated",
            actor_name=actor_name,
            detail={"task_ids": [item["id"] for item in updated_tasks], "status": status.strip(), "evidence": evidence.strip()},
        )
    return updated_tasks
