from __future__ import annotations

from datetime import date, datetime
from typing import Any


ELIGIBLE_STATUS = "eligible"


def _parse_date(value: str) -> date | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError:
        return None


def assess_rule_pack_for_visit(rule_pack: dict[str, Any], visit_date: str) -> dict[str, Any]:
    """Return a CRA-facing applicability decision without changing the rule pack."""
    raw_visit_date = visit_date.strip()
    if str(rule_pack.get("status") or "") != "active":
        return {
            "status": "not_active",
            "selectable": False,
            "message": "该规则包尚未启用或已停用，不能用于新访视。",
            "assessment_date": raw_visit_date,
            "days_until_expiry": None,
            "expires_soon": False,
        }
    if not raw_visit_date:
        return {
            "status": "visit_date_required",
            "selectable": False,
            "message": "请先填写访视日期，系统才能匹配适用规则包。",
            "assessment_date": "",
            "days_until_expiry": None,
            "expires_soon": False,
        }

    assessed_date = _parse_date(raw_visit_date)
    if assessed_date is None:
        return {
            "status": "invalid_visit_date",
            "selectable": False,
            "message": "访视日期应使用 YYYY-MM-DD 格式。",
            "assessment_date": raw_visit_date,
            "days_until_expiry": None,
            "expires_soon": False,
        }

    effective_from_raw = str(rule_pack.get("effective_from") or "").strip()
    effective_to_raw = str(rule_pack.get("effective_to") or "").strip()
    effective_from = _parse_date(effective_from_raw)
    effective_to = _parse_date(effective_to_raw)
    if effective_from is None:
        return {
            "status": "invalid_rule_dates",
            "selectable": False,
            "message": "该规则包未设置有效生效日期，不能用于新访视。",
            "assessment_date": raw_visit_date,
            "days_until_expiry": None,
            "expires_soon": False,
        }
    if effective_to_raw and effective_to is None:
        return {
            "status": "invalid_rule_dates",
            "selectable": False,
            "message": "该规则包的失效日期格式无效，不能用于新访视。",
            "assessment_date": raw_visit_date,
            "days_until_expiry": None,
            "expires_soon": False,
        }
    if effective_to and effective_to < effective_from:
        return {
            "status": "invalid_rule_dates",
            "selectable": False,
            "message": "该规则包的失效日期早于生效日期，不能用于新访视。",
            "assessment_date": raw_visit_date,
            "days_until_expiry": None,
            "expires_soon": False,
        }
    if assessed_date < effective_from:
        return {
            "status": "not_yet_effective",
            "selectable": False,
            "message": f"该规则包自 {effective_from.isoformat()} 起生效，不适用于 {raw_visit_date} 的访视。",
            "assessment_date": raw_visit_date,
            "days_until_expiry": None,
            "expires_soon": False,
        }
    if effective_to and assessed_date > effective_to:
        return {
            "status": "expired",
            "selectable": False,
            "message": f"该规则包已于 {effective_to.isoformat()} 失效，不适用于 {raw_visit_date} 的访视。",
            "assessment_date": raw_visit_date,
            "days_until_expiry": (effective_to - assessed_date).days,
            "expires_soon": False,
        }

    days_until_expiry = (effective_to - assessed_date).days if effective_to else None
    expires_soon = days_until_expiry is not None and 0 <= days_until_expiry <= 30
    message = "规则包适用于该访视日期。"
    if expires_soon:
        message = f"规则包适用于该访视日期；距失效日还有 {days_until_expiry} 天，请确认后续过渡安排。"
    return {
        "status": ELIGIBLE_STATUS,
        "selectable": True,
        "message": message,
        "assessment_date": raw_visit_date,
        "days_until_expiry": days_until_expiry,
        "expires_soon": expires_soon,
    }


def attach_rule_eligibility(rule_packs: list[dict[str, Any]], visit_date: str) -> list[dict[str, Any]]:
    return [{**rule_pack, "eligibility": assess_rule_pack_for_visit(rule_pack, visit_date)} for rule_pack in rule_packs]
