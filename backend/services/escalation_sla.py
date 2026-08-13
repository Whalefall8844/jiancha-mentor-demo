from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"
ESCALATION_SEVERITIES = {"high", "urgent"}
ESCALATION_TARGET_ROLES = {"PM_LM", "PROJECT_ADMIN"}


def _empty_resolution() -> dict[str, Any]:
    return {
        "configured": False,
        "acknowledge_within_hours": None,
        "initial_target_role": "",
        "overdue_target_role": "",
        "source": "not_configured",
    }


def _parse_entry(raw_entry: Any) -> dict[str, Any] | None:
    if not isinstance(raw_entry, dict):
        return None
    hours = raw_entry.get("acknowledge_within_hours")
    initial_target_role = str(raw_entry.get("target_role") or "").strip()
    overdue_target_role = str(raw_entry.get("overdue_target_role") or "").strip()
    if isinstance(hours, bool) or not isinstance(hours, int) or hours <= 0:
        return None
    if initial_target_role not in ESCALATION_TARGET_ROLES:
        return None
    if overdue_target_role not in ESCALATION_TARGET_ROLES:
        return None
    return {
        "configured": True,
        "acknowledge_within_hours": hours,
        "initial_target_role": initial_target_role,
        "overdue_target_role": overdue_target_role,
        "source": "frozen_rule_pack",
    }


def resolve_escalation_sla(rule_content: Any, severity: str) -> dict[str, Any]:
    """Return one safely usable, project-specific SLA without inventing a default."""
    if severity not in ESCALATION_SEVERITIES or not isinstance(rule_content, dict):
        return _empty_resolution()
    raw_sla = rule_content.get("escalation_sla")
    if not isinstance(raw_sla, dict):
        return _empty_resolution()
    return _parse_entry(raw_sla.get(severity)) or _empty_resolution()


def validate_escalation_sla_configuration(rule_content: Any) -> list[str]:
    """Validate only the optional SLA block when a rule-pack author provides it."""
    if not isinstance(rule_content, dict) or "escalation_sla" not in rule_content:
        return []
    raw_sla = rule_content.get("escalation_sla")
    if not isinstance(raw_sla, dict):
        return ["规则包 escalation_sla 必须是对象"]

    errors: list[str] = []
    for severity, raw_entry in raw_sla.items():
        if severity not in ESCALATION_SEVERITIES:
            errors.append(f"escalation_sla 仅支持 high 或 urgent，当前为：{severity}")
            continue
        if not isinstance(raw_entry, dict):
            errors.append(f"escalation_sla.{severity} 必须是对象")
            continue
        hours = raw_entry.get("acknowledge_within_hours")
        if isinstance(hours, bool) or not isinstance(hours, int) or hours <= 0:
            errors.append(f"escalation_sla.{severity}.acknowledge_within_hours 必须为正整数")
        target_role = str(raw_entry.get("target_role") or "").strip()
        if target_role not in ESCALATION_TARGET_ROLES:
            errors.append(f"escalation_sla.{severity}.target_role 必须为 PM_LM 或 PROJECT_ADMIN")
        overdue_target_role = str(raw_entry.get("overdue_target_role") or "").strip()
        if overdue_target_role not in ESCALATION_TARGET_ROLES:
            errors.append(f"escalation_sla.{severity}.overdue_target_role 必须为 PM_LM 或 PROJECT_ADMIN")
    return errors


def build_sla_snapshot(
    *,
    rule_content: Any,
    severity: str,
    fallback_target_role: str,
    rule_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = resolve_escalation_sla(rule_content, severity)
    pack = rule_pack or {}
    return {
        **resolved,
        "severity": severity,
        "initial_target_role": resolved["initial_target_role"] or fallback_target_role,
        "rule_pack_id": str(pack.get("id") or ""),
        "rule_pack_name": str(pack.get("name") or ""),
        "rule_pack_version": str(pack.get("version") or ""),
    }


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, TIMESTAMP_FORMAT)
    except (TypeError, ValueError):
        return None


def calculate_sla_due_at(created_at: str, snapshot: dict[str, Any]) -> str:
    if not snapshot.get("configured"):
        return ""
    created = _parse_timestamp(created_at)
    hours = snapshot.get("acknowledge_within_hours")
    if created is None or isinstance(hours, bool) or not isinstance(hours, int) or hours <= 0:
        return ""
    return (created + timedelta(hours=hours)).strftime(TIMESTAMP_FORMAT)


def describe_sla_state(escalation: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    snapshot = escalation.get("sla_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}
    configured = bool(snapshot.get("configured"))
    due_at = str(escalation.get("sla_due_at") or "")
    due = _parse_timestamp(due_at)
    observed_at = now or datetime.now()
    acknowledged_at = str(escalation.get("acknowledged_at") or "")
    acknowledged = _parse_timestamp(acknowledged_at)
    lifecycle_status = str(escalation.get("status") or "open")
    overdue_escalated_at = str(escalation.get("overdue_escalated_at") or "")
    overdue_target_role = str(
        escalation.get("overdue_escalated_to")
        or snapshot.get("overdue_target_role")
        or ""
    )

    if not configured or due is None:
        return {
            "configured": False,
            "state": "not_configured",
            "receipt_state": "not_configured",
            "due_at": "",
            "remaining_minutes": None,
            "overdue_target_role": "",
            "acknowledged_within_sla": None,
        }

    acknowledged_within_sla = acknowledged <= due if acknowledged else None
    if lifecycle_status == "closed":
        state = "closed"
    elif acknowledged is not None:
        state = "acknowledged_within_sla" if acknowledged_within_sla else "acknowledged_late"
    elif overdue_escalated_at:
        state = "overdue_escalated"
    elif observed_at > due:
        state = "overdue_escalated"
    else:
        state = "pending"

    if acknowledged is not None:
        receipt_state = "acknowledged_within_sla" if acknowledged_within_sla else "acknowledged_late"
    elif overdue_escalated_at or observed_at > due:
        receipt_state = "overdue_escalated"
    else:
        receipt_state = "pending"

    remaining_minutes = max(0, int((due - observed_at).total_seconds() // 60))
    return {
        "configured": True,
        "state": state,
        "receipt_state": receipt_state,
        "due_at": due_at,
        "remaining_minutes": remaining_minutes,
        "overdue_target_role": overdue_target_role,
        "acknowledged_within_sla": acknowledged_within_sla,
    }
