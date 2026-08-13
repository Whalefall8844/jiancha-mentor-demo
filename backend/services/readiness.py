from __future__ import annotations

from typing import Any

from ..database import get_connection
from ..repositories.visits import get_visit, list_tasks
from .clarifications import detect_clarification_specs
from .system_checks import SYSTEM_CHECK_TASK_TYPE


TERMINAL_STATUSES = {
    "已执行且未发现",
    "已执行且有发现",
    "未检查",
    "暂无法检查",
    "不适用",
    "已完成",
}


def _task_label(task: dict[str, Any]) -> str:
    if task.get("task_type") == SYSTEM_CHECK_TASK_TYPE:
        return f"系统／设备 · {task['title']}"
    return f"表 {task['table_index']} · {task['title']}"


def _block(blocks: list[dict[str, Any]], task: dict[str, Any], code: str, message: str) -> None:
    blocks.append(
        {
            "code": code,
            "task_id": task["id"],
            "task_index": task["table_index"],
            "message": f"{_task_label(task)}：{message}",
        }
    )


def _clarification_block(blocks: list[dict[str, Any]], spec: dict[str, Any]) -> None:
    issue_type = str(spec.get("issue_type") or "missing")
    code = "clarification_conflict" if issue_type == "conflict" else "clarification_missing"
    blocks.append(
        {
            "code": code,
            "task_id": str(spec.get("target_task_id") or ""),
            "task_index": int(spec.get("target_table") or 0),
            "message": f"{spec.get('title') or '报告信息待确认'}：{spec.get('reason') or spec.get('prompt') or ''}",
        }
    )


def evaluate_report_readiness(visit_id: str) -> dict[str, Any]:
    """Apply the same PRD task semantics before Word generation and CRA submission."""
    visit = get_visit(visit_id)
    if visit is None:
        raise ValueError("未找到当前访视")

    tasks = list_tasks(visit_id)
    blocks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    required_tasks = [task for task in tasks if bool(task.get("requires_evidence"))]
    terminal_required = 0

    for task in tasks:
        status = (task.get("status") or "").strip()
        is_terminal = status in TERMINAL_STATUSES
        if bool(task.get("requires_evidence")):
            if is_terminal:
                terminal_required += 1
            else:
                _block(blocks, task, "required_task_pending", "尚未记录明确监查结论。")

        if status == "已执行且未发现":
            missing = [
                label
                for key, label in (("execution_date", "执行日期"), ("checked_scope", "检查范围/样本量"), ("evidence", "证据或核查说明"), ("completed_by", "执行 CRA"))
                if not (task.get(key) or "").strip()
            ]
            if missing:
                _block(blocks, task, "no_finding_evidence_incomplete", f"已选择“已执行且未发现”，仍缺少{'、'.join(missing)}。")
        elif status == "已执行且有发现":
            missing = [
                label
                for key, label in (("execution_date", "执行日期"), ("checked_scope", "检查范围/样本量"), ("evidence", "发现或核查说明"), ("completed_by", "执行 CRA"))
                if not (task.get(key) or "").strip()
            ]
            if missing:
                _block(blocks, task, "finding_evidence_incomplete", f"已选择“已执行且有发现”，仍缺少{'、'.join(missing)}。")
        elif status in {"未检查", "暂无法检查", "不适用"}:
            missing = [
                label
                for key, label in (("execution_date", "执行日期"), ("rationale", "原因或适用依据"), ("completed_by", "执行 CRA"))
                if not (task.get(key) or "").strip()
            ]
            if missing:
                _block(blocks, task, "task_reason_missing", f"已选择“{status}”，仍缺少{'、'.join(missing)}。")
        elif status == "已完成":
            missing = [
                label
                for key, label in (("execution_date", "执行日期"), ("evidence", "完成说明"), ("completed_by", "执行 CRA"))
                if not (task.get(key) or "").strip()
            ]
            if missing:
                _block(blocks, task, "completed_evidence_incomplete", f"已选择“已完成”，仍缺少{'、'.join(missing)}。")

    for spec in detect_clarification_specs(visit_id):
        # Task execution gaps already have richer evidence-level blockers above.
        if spec.get("issue_type") == "missing" and spec.get("target_task_id"):
            continue
        if bool(spec.get("is_blocking")):
            _clarification_block(blocks, spec)

    with get_connection() as connection:
        escalation_rows = connection.execute(
            """
            SELECT id, title, severity, target_role, status
            FROM operation_escalations
            WHERE visit_id = ? AND status IN ('open', 'acknowledged')
            ORDER BY created_at DESC
            """,
            (visit_id,),
        ).fetchall()
    for row in escalation_rows:
        warnings.append(
            {
                "code": "open_escalation",
                "escalation_id": row["id"],
                "message": f"需升级事项仍处于{row['status']}：{row['title']}（{row['severity']} → {row['target_role']}）。",
            }
        )

    return {
        "ready": not blocks,
        "blocks": blocks,
        "warnings": warnings,
        "summary": {
            "task_count": len(tasks),
            "required_tasks": len(required_tasks),
            "terminal_required_tasks": terminal_required,
            "block_count": len(blocks),
            "warning_count": len(warnings),
        },
    }


def readiness_error(readiness: dict[str, Any]) -> str:
    blocks = readiness.get("blocks") or []
    if not blocks:
        return "报告完整性门禁未通过"
    preview = "；".join(item["message"] for item in blocks[:3])
    suffix = "" if len(blocks) <= 3 else f"；另有 {len(blocks) - 3} 项待处理"
    return f"报告尚未通过完整性门禁：{preview}{suffix}"
