from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from ..database import get_connection, transaction
from ..repositories.catalog import create_configuration_audit_event, get_project


AssessmentAction = Literal["submit", "approve", "reject", "withdraw"]

EDITABLE_STATUSES = {"draft"}
APPROVABLE_STATUSES = {"pending_approval"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    return datetime.now().date().isoformat()


def _row(row) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    for key in (
        "processes_nonblind_data",
        "contains_direct_identifiers",
        "requires_full_blind_separation",
        "uses_editable_docx_only",
        "requires_ctms_etmf_integration",
    ):
        item[key] = bool(item.get(key))
    return item


def _assessment_boundary(item: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    if item.get("processes_nonblind_data"):
        reasons.append("评估声明会处理非盲数据")
    if item.get("contains_direct_identifiers"):
        reasons.append("评估声明会处理直接身份信息或源文件")
    if item.get("requires_full_blind_separation"):
        reasons.append("评估声明需要完整盲／非盲权限隔离")
    if not item.get("uses_editable_docx_only"):
        reasons.append("评估声明不局限于可编辑 DOCX 模板")
    if item.get("requires_ctms_etmf_integration"):
        reasons.append("评估声明要求真实 CTMS/eTMF 集成")
    return {
        "matches_local_mvp_boundary": not reasons,
        "boundary_notes": reasons,
    }


def _with_boundary(row) -> dict[str, Any] | None:
    item = _row(row)
    if item is None:
        return None
    return {**item, "boundary": _assessment_boundary(item)}


def list_project_eligibility_assessments(project_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM project_eligibility_assessments
            WHERE project_id = ?
            ORDER BY assessment_version DESC, rowid DESC
            """,
            (project_id,),
        ).fetchall()
    return [_with_boundary(row) or {} for row in rows]


def _is_effective(item: dict[str, Any], as_of_date: str) -> bool:
    effective_from = str(item.get("effective_from") or "").strip()
    effective_to = str(item.get("effective_to") or "").strip()
    return (not effective_from or effective_from <= as_of_date) and (not effective_to or effective_to >= as_of_date)


def get_current_approved_assessment(
    project_id: str,
    as_of_date: str = "",
    *,
    connection=None,
) -> dict[str, Any] | None:
    effective_date = as_of_date.strip() or _today()
    query = """
        SELECT *
        FROM project_eligibility_assessments
        WHERE project_id = ? AND status = 'approved'
        ORDER BY assessment_version DESC, rowid DESC
    """
    if connection is not None:
        rows = connection.execute(query, (project_id,)).fetchall()
    else:
        with get_connection() as local_connection:
            rows = local_connection.execute(query, (project_id,)).fetchall()
    for row in rows:
        item = _with_boundary(row)
        if item is not None and _is_effective(item, effective_date):
            return item
    return None


def create_project_eligibility_assessment(
    *,
    project_id: str,
    actor_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if get_project(project_id) is None:
        raise ValueError("未找到项目")
    timestamp = _now()
    assessment_id = uuid4().hex
    with transaction() as connection:
        next_version = int(
            connection.execute(
                "SELECT COALESCE(MAX(assessment_version), 0) + 1 AS next_version FROM project_eligibility_assessments WHERE project_id = ?",
                (project_id,),
            ).fetchone()["next_version"]
        )
        connection.execute(
            """
            INSERT INTO project_eligibility_assessments (
                id, project_id, assessment_version, assessment_scope, blinding_mode,
                processes_nonblind_data, contains_direct_identifiers, requires_full_blind_separation,
                uses_editable_docx_only, requires_ctms_etmf_integration, assessment_note,
                effective_from, effective_to, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (
                assessment_id,
                project_id,
                next_version,
                str(payload.get("assessment_scope") or "IMV_DOCX").strip() or "IMV_DOCX",
                str(payload.get("blinding_mode") or "open_label").strip() or "open_label",
                int(bool(payload.get("processes_nonblind_data", False))),
                int(bool(payload.get("contains_direct_identifiers", False))),
                int(bool(payload.get("requires_full_blind_separation", False))),
                int(bool(payload.get("uses_editable_docx_only", True))),
                int(bool(payload.get("requires_ctms_etmf_integration", False))),
                str(payload.get("assessment_note") or "").strip(),
                str(payload.get("effective_from") or "").strip(),
                str(payload.get("effective_to") or "").strip(),
                timestamp,
                timestamp,
            ),
        )
        saved = connection.execute("SELECT * FROM project_eligibility_assessments WHERE id = ?", (assessment_id,)).fetchone()
    item = _with_boundary(saved) or {}
    create_configuration_audit_event(
        entity_type="project_eligibility_assessment",
        entity_id=assessment_id,
        project_id=project_id,
        action="created",
        actor_name=actor_name.strip() or "项目管理员",
        detail={"assessment_version": next_version, "boundary": item.get("boundary", {})},
    )
    return item


def update_project_eligibility_assessment(
    *,
    project_id: str,
    assessment_id: str,
    actor_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    allowed = {
        "assessment_scope",
        "blinding_mode",
        "processes_nonblind_data",
        "contains_direct_identifiers",
        "requires_full_blind_separation",
        "uses_editable_docx_only",
        "requires_ctms_etmf_integration",
        "assessment_note",
        "effective_from",
        "effective_to",
    }
    with transaction() as connection:
        before_row = connection.execute(
            "SELECT * FROM project_eligibility_assessments WHERE id = ? AND project_id = ?",
            (assessment_id, project_id),
        ).fetchone()
        before = _with_boundary(before_row)
        if before is None:
            raise ValueError("未找到项目适用性评估")
        if before["status"] not in EDITABLE_STATUSES:
            raise ValueError("只有草稿评估可以修改；需要重新评估时请新建版本")
        fields: list[tuple[str, Any]] = []
        changes: dict[str, Any] = {}
        for key, value in payload.items():
            if key not in allowed:
                continue
            normalized = int(bool(value)) if key in {
                "processes_nonblind_data",
                "contains_direct_identifiers",
                "requires_full_blind_separation",
                "uses_editable_docx_only",
                "requires_ctms_etmf_integration",
            } else str(value or "").strip()
            fields.append((key, normalized))
            if before.get(key) != normalized and not (isinstance(before.get(key), bool) and bool(before.get(key)) == bool(normalized)):
                changes[key] = {"before": before.get(key), "after": normalized}
        if fields:
            assignments = ", ".join(f"{field} = ?" for field, _ in fields)
            connection.execute(
                f"UPDATE project_eligibility_assessments SET {assignments}, updated_at = ? WHERE id = ?",
                (*[value for _, value in fields], _now(), assessment_id),
            )
        saved = connection.execute("SELECT * FROM project_eligibility_assessments WHERE id = ?", (assessment_id,)).fetchone()
    item = _with_boundary(saved) or {}
    if changes:
        create_configuration_audit_event(
            entity_type="project_eligibility_assessment",
            entity_id=assessment_id,
            project_id=project_id,
            action="updated",
            actor_name=actor_name.strip() or "项目管理员",
            detail={"assessment_version": item.get("assessment_version"), "changes": changes},
        )
    return item


def transition_project_eligibility_assessment(
    *,
    project_id: str,
    assessment_id: str,
    action: AssessmentAction,
    actor_name: str,
    note: str = "",
) -> dict[str, Any]:
    normalized_note = note.strip()
    timestamp = _now()
    with transaction() as connection:
        before_row = connection.execute(
            "SELECT * FROM project_eligibility_assessments WHERE id = ? AND project_id = ?",
            (assessment_id, project_id),
        ).fetchone()
        before = _with_boundary(before_row)
        if before is None:
            raise ValueError("未找到项目适用性评估")
        status = before["status"]
        if action == "submit":
            if status != "draft":
                raise ValueError("只有草稿评估可以提交审批")
            assignments = {
                "status": "pending_approval",
                "submitted_at": timestamp,
                "submitted_by": actor_name.strip(),
            }
        elif action == "approve":
            if status not in APPROVABLE_STATUSES:
                raise ValueError("只有待审批评估可以批准")
            assignments = {
                "status": "approved",
                "reviewed_at": timestamp,
                "reviewed_by": actor_name.strip(),
                "review_note": normalized_note,
            }
        elif action == "reject":
            if status not in APPROVABLE_STATUSES:
                raise ValueError("只有待审批评估可以退回")
            if not normalized_note:
                raise ValueError("退回评估时必须填写审批意见")
            assignments = {
                "status": "rejected",
                "reviewed_at": timestamp,
                "reviewed_by": actor_name.strip(),
                "review_note": normalized_note,
            }
        elif action == "withdraw":
            if status != "pending_approval":
                raise ValueError("只有待审批评估可以撤回")
            assignments = {
                "status": "withdrawn",
                "withdrawn_at": timestamp,
                "withdrawn_by": actor_name.strip(),
                "withdrawal_note": normalized_note,
            }
        else:
            raise ValueError("不支持的适用性评估操作")
        assignment_clause = ", ".join(f"{key} = ?" for key in assignments)
        connection.execute(
            f"UPDATE project_eligibility_assessments SET {assignment_clause}, updated_at = ? WHERE id = ?",
            (*assignments.values(), timestamp, assessment_id),
        )
        saved = connection.execute("SELECT * FROM project_eligibility_assessments WHERE id = ?", (assessment_id,)).fetchone()
    item = _with_boundary(saved) or {}
    create_configuration_audit_event(
        entity_type="project_eligibility_assessment",
        entity_id=assessment_id,
        project_id=project_id,
        action=f"approval_{action}",
        actor_name=actor_name.strip() or "审批人",
        detail={
            "assessment_version": item.get("assessment_version"),
            "from_status": before.get("status"),
            "to_status": item.get("status"),
            "note": normalized_note,
            "boundary": item.get("boundary", {}),
        },
    )
    return item
