from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Any, Literal
from uuid import uuid4

from ..database import get_connection, transaction
from ..repositories.visits import get_visit, list_action_items, list_tasks


TERMINAL_TASK_STATUSES = {
    "已执行且未发现",
    "已执行且有发现",
    "未检查",
    "暂无法检查",
    "不适用",
    "已完成",
}

_DOCUMENT_RULES = {
    "protocol": {"label": "研究方案", "tokens": ("方案", "protocol")},
    "icf": {"label": "知情同意书（ICF）", "tokens": ("知情同意", "icf")},
    "ethics": {"label": "伦理文件", "tokens": ("伦理", "ethics")},
    "sop": {"label": "SOP", "tokens": ("sop", "标准操作")},
}
_VERSION_PATTERN = re.compile(r"(?i)(?:版本|版|version|ver\.?|v)\s*([0-9]+(?:\.[0-9]+){0,3})")
_DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _decode_item(row: Any) -> dict[str, Any]:
    item = dict(row)
    for column, fallback in (("candidates_json", []), ("source_json", {}), ("resolution_json", {})):
        try:
            item[column.removesuffix("_json")] = json.loads(item.pop(column) or json.dumps(fallback, ensure_ascii=False))
        except json.JSONDecodeError:
            item[column.removesuffix("_json")] = fallback
    item["is_blocking"] = bool(item.get("is_blocking"))
    return item


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


def _visit_or_raise(visit_id: str) -> dict[str, Any]:
    visit = get_visit(visit_id)
    if visit is None:
        raise ValueError("未找到当前访视")
    return visit


def _extract_versions(value: str) -> list[str]:
    values: list[str] = []
    for match in _VERSION_PATTERN.finditer(value):
        version = f"V{match.group(1)}"
        if version not in values:
            values.append(version)
    return values


def _parse_iso_date(value: str) -> date | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError:
        return None


def _extract_dates(value: str) -> list[str]:
    values: list[str] = []
    for match in _DATE_PATTERN.finditer(value):
        try:
            normalized = date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError:
            continue
        if normalized not in values:
            values.append(normalized)
    return values


def _document_type_from_text(value: str) -> list[str]:
    lowered = value.casefold()
    result: list[str] = []
    for document_type, rule in _DOCUMENT_RULES.items():
        if any(token.casefold() in lowered for token in rule["tokens"]):
            result.append(document_type)
    return result


def _report_confirmed_rows(connection, visit_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT * FROM confirmed_fields
        WHERE visit_id = ? AND is_active = 1
          AND assertion_type <> 'center_explanation'
          AND source_type <> 'center_explanation'
        ORDER BY confirmed_at, rowid
        """,
        (visit_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _missing_slot_specs(visit: dict[str, Any], confirmed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    slots = list((visit.get("snapshot") or {}).get("template_field_slots") or [])
    completeness_rules = dict((visit.get("snapshot") or {}).get("template_completeness_rules") or {})
    field_mode = str(completeness_rules.get("field_mode") or "slot_required")
    for slot in slots:
        is_required = field_mode == "all_confirmed_text_slots" or (
            field_mode == "slot_required" and bool(slot.get("required"))
        )
        if not is_required or str(slot.get("value_source") or "") != "confirmed_text":
            continue
        field_key = str(slot.get("field_key") or "").strip()
        if not field_key:
            continue
        if any(str(item.get("field_key") or "") == field_key and str(item.get("value") or "").strip() for item in confirmed_rows):
            continue
        locator = str(slot.get("target_locator") or "")
        issue_key = f"missing:template_slot:{field_key}:{locator}"
        label = str(slot.get("label") or field_key)
        specs.append(
            {
                "issue_key": issue_key,
                "issue_type": "missing",
                "severity": "high",
                "is_blocking": True,
                "title": f"报告必填字段待补录：{label}",
                "prompt": f"请补录“{label}”的 CRA 已确认内容。系统将把本次输入留存在工作底稿并写入对应报告填写位。",
                "reason": "模板冻结完整性规则要求该填写位具备 CRA 已确认内容，但尚无对应字段。",
                "target_task_id": "",
                "target_table": int(slot.get("table_index") or 0),
                "field_key": field_key,
                "candidates": [],
                "source": {"kind": "template_field_slot", "slot": slot},
            }
        )
    return specs


def _missing_task_specs(visit_id: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for task in list_tasks(visit_id):
        if not bool(task.get("requires_evidence")):
            continue
        if str(task.get("status") or "").strip() in TERMINAL_TASK_STATUSES:
            continue
        table_index = int(task.get("table_index") or 0)
        task_kind = "系统／设备" if task.get("task_type") == "system_device_check" else f"表 {table_index}"
        specs.append(
            {
                "issue_key": f"missing:task:{task['id']}",
                "issue_type": "missing",
                "severity": "high",
                "is_blocking": True,
                "title": f"必填监查任务待补录：{task_kind} · {task['title']}",
                "prompt": "请在任务执行区补录明确监查结论及所需执行依据；系统不会根据现有文字猜测结论。",
                "reason": f"当前任务状态为“{task.get('status') or '待补录'}”，尚未形成报告所需终态结论。",
                "target_task_id": task["id"],
                "target_table": table_index,
                "field_key": str(task.get("field_key") or ""),
                "candidates": [],
                "source": {"kind": "visit_task", "task": task},
            }
        )
    return specs


def _controlled_document_conflict_specs(visit: dict[str, Any], confirmed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frozen_documents = dict(((visit.get("snapshot") or {}).get("master_data") or {}).get("documents") or {})
    collected: dict[str, dict[str, Any]] = {}
    for field in confirmed_rows:
        value = str(field.get("value") or "").strip()
        if not value:
            continue
        versions = _extract_versions(value)
        dates = _extract_dates(value)
        if not versions and not dates:
            continue
        for document_type in _document_type_from_text(value):
            bucket = collected.setdefault(document_type, {"fields": [], "versions": set(), "dates": set()})
            bucket["fields"].append({"field": field, "versions": versions, "dates": dates})
            bucket["versions"].update(versions)
            bucket["dates"].update(dates)

    specs: list[dict[str, Any]] = []
    for document_type, bucket in collected.items():
        rule = _DOCUMENT_RULES[document_type]
        frozen = dict(frozen_documents.get(document_type) or {})
        frozen_display = str(frozen.get("version") or frozen.get("display") or "").strip()
        frozen_versions = _extract_versions(frozen_display)
        frozen_date_value = str(frozen.get("version_date") or "").strip()
        frozen_dates = _extract_dates(frozen_date_value)
        known_versions = set(bucket["versions"])
        known_dates = set(bucket["dates"])
        version_mismatch = bool(frozen_versions and any(version not in frozen_versions for version in known_versions))
        date_mismatch = bool(frozen_dates and any(value not in frozen_dates for value in known_dates))
        multiple_versions = len(known_versions) > 1
        multiple_dates = len(known_dates) > 1
        if not version_mismatch and not date_mismatch and not multiple_versions and not multiple_dates:
            continue
        candidates: list[dict[str, Any]] = []
        if frozen_display or frozen_dates:
            candidates.append(
                {
                    "id": f"frozen:{document_type}",
                    "kind": "frozen_document",
                    "value": frozen_display or frozen_date_value,
                    "versions": frozen_versions,
                    "dates": frozen_dates,
                    "source": {
                        "document_id": frozen.get("id", ""),
                        "title": frozen.get("title", rule["label"]),
                        "document_type": document_type,
                        "source": frozen.get("source", "frozen_visit_snapshot"),
                    },
                }
            )
        for item in bucket["fields"]:
            field = item["field"]
            candidates.append(
                {
                    "id": field["id"],
                    "kind": "confirmed_field",
                    "value": field.get("value", ""),
                    "versions": item["versions"],
                    "dates": item["dates"],
                    "target_table": field.get("target_table", 0),
                    "field_key": field.get("field_key", ""),
                    "category": field.get("category", ""),
                    "subject_code": field.get("subject_code", ""),
                    "subject_display_code": field.get("subject_display_code", ""),
                    "source": {
                        "confirmed_field_id": field["id"],
                        "source_record_id": field.get("source_record_id", ""),
                        "suggestion_id": field.get("suggestion_id", ""),
                        "confirmed_at": field.get("confirmed_at", ""),
                    },
                }
            )
        ordered_versions = "|".join(sorted(known_versions | set(frozen_versions))) or "no_version"
        ordered_dates = "|".join(sorted(known_dates | set(frozen_dates))) or "no_date"
        field_candidate = next((item for item in candidates if item["kind"] == "confirmed_field"), {})
        mismatch_reasons: list[str] = []
        if version_mismatch:
            mismatch_reasons.append("与访视冻结受控文件版本不一致")
        elif multiple_versions:
            mismatch_reasons.append("同类受控文件出现多个版本")
        if date_mismatch:
            mismatch_reasons.append("与访视冻结文件日期不一致")
        elif multiple_dates:
            mismatch_reasons.append("同类受控文件出现多个日期")
        mismatch_text = "；".join(mismatch_reasons)
        specs.append(
            {
                "issue_key": f"conflict:controlled_document:{document_type}:{ordered_versions}:{ordered_dates}",
                "issue_type": "conflict",
                "severity": "high",
                "is_blocking": True,
                "title": f"受控文件版本冲突：{rule['label']}",
                "prompt": f"已确认记录中{mismatch_text}。请核对来源后选择可采用的记录候选，或录入经核对后的 CRA 决议文本；系统不会静默覆盖。",
                "reason": (
                    f"检测到版本：{', '.join(sorted(known_versions)) or '未识别'}；冻结版本：{', '.join(frozen_versions) or frozen_display or '未登记'}；"
                    f"检测到日期：{', '.join(sorted(known_dates)) or '未识别'}；冻结日期：{', '.join(frozen_dates) or frozen_date_value or '未登记'}。"
                ),
                "target_task_id": "",
                "target_table": int(field_candidate.get("target_table") or 0),
                "field_key": str(field_candidate.get("field_key") or ""),
                "candidates": candidates,
                "source": {
                    "kind": "controlled_document_version_check",
                    "document_type": document_type,
                    "frozen_document": frozen,
                    "detected_versions": sorted(known_versions),
                    "detected_dates": sorted(known_dates),
                },
            }
        )
    return specs


def _rule_period_conflict_specs(visit: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = dict(visit.get("snapshot") or {})
    frozen_rule = dict(snapshot.get("rule_pack") or {})
    visit_context = dict(snapshot.get("visit_context") or {})
    activity_start = str(
        visit.get("activity_start_date") or visit_context.get("activity_start_date") or visit.get("visit_date") or ""
    ).strip()
    activity_end = str(
        visit.get("visit_date") or visit_context.get("activity_end_date") or ""
    ).strip()
    effective_from = str(frozen_rule.get("effective_from") or "").strip()
    effective_to = str(frozen_rule.get("effective_to") or "").strip()
    start_date = _parse_iso_date(activity_start)
    end_date = _parse_iso_date(activity_end)
    rule_from = _parse_iso_date(effective_from)
    rule_to = _parse_iso_date(effective_to) if effective_to else None

    reasons: list[str] = []
    if not frozen_rule:
        reasons.append("当前访视未保留冻结规则包快照")
    if start_date is None or end_date is None:
        reasons.append("监查活动日期无法按 YYYY-MM-DD 解释")
    elif end_date < start_date:
        reasons.append("监查活动结束日期早于开始日期")
    if frozen_rule and rule_from is None:
        reasons.append("冻结规则包未登记有效生效日期")
    if effective_to and rule_to is None:
        reasons.append("冻结规则包失效日期无法按 YYYY-MM-DD 解释")
    if rule_from and rule_to and rule_to < rule_from:
        reasons.append("冻结规则包失效日期早于生效日期")
    if start_date and end_date and rule_from and not reasons:
        if start_date < rule_from or (rule_to is not None and end_date > rule_to):
            reasons.append("监查活动日期跨出冻结规则包的有效期")

    if not reasons:
        return []
    rule_label = " · ".join(part for part in (str(frozen_rule.get("name") or "").strip(), str(frozen_rule.get("version") or "").strip()) if part)
    return [
        {
            "issue_key": f"conflict:rule_period:{frozen_rule.get('id') or visit.get('rule_pack_id') or 'missing'}:{activity_start}:{activity_end}:{effective_from}:{effective_to}",
            "issue_type": "conflict",
            "severity": "high",
            "is_blocking": True,
            "title": "规则包适用期需人工确认",
            "prompt": "请按项目既有 SOP 发起 QA/临床运营人工确认；系统不会依据自由文本替换或豁免冻结规则包。",
            "reason": "；".join(reasons) + f"。活动日期：{activity_start or '未登记'} 至 {activity_end or '未登记'}；规则包：{rule_label or '未登记'}（{effective_from or '未登记'} 至 {effective_to or '未设失效日期'}）。",
            "target_task_id": "",
            "target_table": 0,
            "field_key": "rule_period",
            "candidates": [],
            "source": {
                "kind": "rule_period_check",
                "conflict_kind": "rule_period",
                "rule_pack": frozen_rule,
                "activity_start_date": activity_start,
                "activity_end_date": activity_end,
                "effective_from": effective_from,
                "effective_to": effective_to,
            },
        }
    ]


def _template_rule_contract_conflict_specs(visit: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = dict(visit.get("snapshot") or {})
    frozen_rule = dict(snapshot.get("rule_pack") or {})
    rule_content = dict(frozen_rule.get("content") or {})
    expected_profile = str(rule_content.get("template_profile") or rule_content.get("task_template") or "").strip()
    expected_sop_version = str(rule_content.get("sop_version") or rule_content.get("required_sop_version") or "").strip()
    template_contract = dict(snapshot.get("template_contract") or {})
    actual_table_count = int(template_contract.get("table_count") or visit.get("table_count") or 0)
    actual_profile = str(template_contract.get("profile") or "").strip()
    if not actual_profile and actual_table_count > 0:
        actual_profile = f"imv_{actual_table_count}_table"
    actual_sop_version = str(
        snapshot.get("project_sop_version") or (visit.get("project_metadata") or {}).get("sop_version") or ""
    ).strip()

    reasons: list[str] = []
    if expected_profile and not actual_profile:
        reasons.append("规则包要求的模板工作流标识无法从当前冻结模板解析")
    elif expected_profile and actual_profile != expected_profile:
        reasons.append(f"规则包要求模板工作流“{expected_profile}”，当前模板为“{actual_profile}”")
    if expected_sop_version and not actual_sop_version:
        reasons.append(f"规则包要求 SOP 版本“{expected_sop_version}”，但访视未冻结项目 SOP 版本")
    elif expected_sop_version and actual_sop_version != expected_sop_version:
        reasons.append(f"规则包要求 SOP 版本“{expected_sop_version}”，当前冻结项目 SOP 为“{actual_sop_version}”")
    if not reasons:
        return []

    template_label = " · ".join(
        part for part in (str(template_contract.get("name") or visit.get("template_name") or "").strip(), str(template_contract.get("version") or visit.get("template_version") or "").strip()) if part
    ) or "当前冻结模板"
    return [
        {
            "issue_key": f"conflict:template_rule_contract:{frozen_rule.get('id') or visit.get('rule_pack_id') or 'missing'}:{expected_profile}:{actual_profile}:{expected_sop_version}:{actual_sop_version}",
            "issue_type": "conflict",
            "severity": "high",
            "is_blocking": True,
            "title": "模板／规则包契约需人工确认",
            "prompt": "请按项目既有 SOP 由 PM/LM 协调 QA/临床运营确认，或在草稿期改选符合规则包要求的模板/规则包；系统不会用报告文本覆盖冻结配置。",
            "reason": "；".join(reasons) + f"。当前模板：{template_label}。",
            "target_task_id": "",
            "target_table": 0,
            "field_key": "template_rule_contract",
            "candidates": [],
            "source": {
                "kind": "template_rule_contract_check",
                "conflict_kind": "template_rule_contract",
                "rule_pack": frozen_rule,
                "template_contract": template_contract,
                "expected_template_profile": expected_profile,
                "actual_template_profile": actual_profile,
                "expected_sop_version": expected_sop_version,
                "actual_sop_version": actual_sop_version,
            },
        }
    ]


def _action_closure_conflict_specs(visit_id: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for action_item in list_action_items(visit_id):
        status = str(action_item.get("status") or "").strip()
        closure_note = str(action_item.get("closure_note") or "").strip()
        closed_at = str(action_item.get("closed_at") or "").strip()
        attachment_count = int(action_item.get("attachment_count") or 0)
        conflict_code = ""
        reason = ""
        if status == "closed" and not closure_note and attachment_count <= 0:
            conflict_code = "closed_without_basis"
            reason = "行动项已标为关闭，但未保存关闭说明，也未关联关闭证据附件。"
        elif status in {"open", "in_progress"} and closed_at:
            conflict_code = "reopened_with_closed_at"
            reason = f"行动项当前状态为“{status}”，但仍保留关闭时间 {closed_at}。"
        if not conflict_code:
            continue
        title = str(action_item.get("title") or "未命名行动项").strip()
        specs.append(
            {
                "issue_key": f"conflict:action_closure:{action_item['id']}:{conflict_code}",
                "issue_type": "conflict",
                "severity": "high",
                "is_blocking": True,
                "title": f"行动项闭环状态矛盾：{title}",
                "prompt": "请在行动项区域修正状态，或补充关闭说明/关联证据后重新扫描；系统不会以澄清文本替代行动项闭环证据。",
                "reason": reason,
                "target_task_id": "",
                "target_table": 0,
                "field_key": f"action_item:{action_item['id']}",
                "candidates": [],
                "source": {
                    "kind": "action_closure_check",
                    "conflict_kind": "action_closure",
                    "action_item_id": action_item["id"],
                    "action_title": title,
                    "action_status": status,
                    "closure_note": closure_note,
                    "closed_at": closed_at,
                    "attachment_count": attachment_count,
                    "conflict_code": conflict_code,
                },
            }
        )
    return specs


def detect_clarification_specs(visit_id: str) -> list[dict[str, Any]]:
    """Produce deterministic FR-06 issues without changing visit data."""
    visit = _visit_or_raise(visit_id)
    with get_connection() as connection:
        confirmed_rows = _report_confirmed_rows(connection, visit_id)
    specs = [
        *_missing_slot_specs(visit, confirmed_rows),
        *_missing_task_specs(visit_id),
        *_controlled_document_conflict_specs(visit, confirmed_rows),
        *_rule_period_conflict_specs(visit),
        *_template_rule_contract_conflict_specs(visit),
        *_action_closure_conflict_specs(visit_id),
    ]
    return sorted(
        specs,
        key=lambda item: (
            0 if item["issue_type"] == "conflict" else 1,
            0 if item["is_blocking"] else 1,
            item["target_table"],
            item["title"],
        ),
    )


def _item_by_id(connection, item_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM clarification_items WHERE id = ?", (item_id,)).fetchone()
    return _decode_item(row) if row is not None else None


def list_clarification_items(visit_id: str, *, include_resolved: bool = True) -> list[dict[str, Any]]:
    where = "visit_id = ?" if include_resolved else "visit_id = ? AND status IN ('open', 'manual_required')"
    with get_connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM clarification_items WHERE {where} ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'manual_required' THEN 1 ELSE 2 END, updated_at DESC, rowid DESC",
            (visit_id,),
        ).fetchall()
        items = [_decode_item(row) for row in rows]
        if not items:
            return []
        response_rows = connection.execute(
            "SELECT * FROM clarification_responses WHERE clarification_item_id IN ("
            + ", ".join("?" for _ in items)
            + ") ORDER BY created_at DESC, rowid DESC",
            tuple(item["id"] for item in items),
        ).fetchall()
    responses_by_item: dict[str, list[dict[str, Any]]] = {item["id"]: [] for item in items}
    for row in response_rows:
        response = dict(row)
        responses_by_item.setdefault(response["clarification_item_id"], []).append(response)
    for item in items:
        item["responses"] = responses_by_item.get(item["id"], [])
    return items


def refresh_clarification_items(*, visit_id: str, actor_name: str = "系统") -> list[dict[str, Any]]:
    specs = detect_clarification_specs(visit_id)
    timestamp = _now()
    with transaction() as connection:
        visit = connection.execute("SELECT project_id FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if visit is None:
            raise ValueError("未找到当前访视")
        existing_rows = connection.execute("SELECT * FROM clarification_items WHERE visit_id = ?", (visit_id,)).fetchall()
        existing_by_key = {row["issue_key"]: _decode_item(row) for row in existing_rows}
        active_keys = {spec["issue_key"] for spec in specs}
        for spec in specs:
            existing = existing_by_key.get(spec["issue_key"])
            payload = (
                spec["issue_type"],
                spec["severity"],
                1 if spec["is_blocking"] else 0,
                spec["title"],
                spec["prompt"],
                spec["reason"],
                spec["target_task_id"] or None,
                spec["target_table"],
                spec["field_key"],
                json.dumps(spec["candidates"], ensure_ascii=False),
                json.dumps(spec["source"], ensure_ascii=False),
            )
            if existing is None:
                item_id = uuid4().hex
                connection.execute(
                    """
                    INSERT INTO clarification_items (
                        id, visit_id, issue_key, issue_type, severity, is_blocking, status, title, prompt, reason,
                        target_task_id, target_table, field_key, candidates_json, source_json, resolution_json,
                        invalid_attempts, created_at, updated_at, resolved_at, resolved_by
                    ) VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, '{}', 0, ?, ?, '', '')
                    """,
                    (item_id, visit_id, spec["issue_key"], *payload, timestamp, timestamp),
                )
                _audit(
                    connection,
                    project_id=visit["project_id"],
                    visit_id=visit_id,
                    entity_type="clarification_item",
                    entity_id=item_id,
                    action="created",
                    actor_name=actor_name,
                    detail={"issue_key": spec["issue_key"], "issue_type": spec["issue_type"], "reason": spec["reason"]},
                )
            else:
                status = "open" if existing["status"] == "resolved" else existing["status"]
                connection.execute(
                    """
                    UPDATE clarification_items
                    SET issue_type = ?, severity = ?, is_blocking = ?, status = ?, title = ?, prompt = ?, reason = ?,
                        target_task_id = ?, target_table = ?, field_key = ?, candidates_json = ?, source_json = ?,
                        updated_at = ?, resolved_at = CASE WHEN ? = 'open' THEN '' ELSE resolved_at END,
                        resolved_by = CASE WHEN ? = 'open' THEN '' ELSE resolved_by END
                    WHERE id = ?
                    """,
                    (*payload[:3], status, *payload[3:], timestamp, status, status, existing["id"]),
                )
        for existing in existing_by_key.values():
            if existing["issue_key"] in active_keys or existing["status"] == "resolved":
                continue
            connection.execute(
                "UPDATE clarification_items SET status = 'resolved', resolution_json = ?, updated_at = ?, resolved_at = ?, resolved_by = ? WHERE id = ?",
                (json.dumps({"mode": "condition_cleared"}, ensure_ascii=False), timestamp, timestamp, "系统", existing["id"]),
            )
            _audit(
                connection,
                project_id=visit["project_id"],
                visit_id=visit_id,
                entity_type="clarification_item",
                entity_id=existing["id"],
                action="condition_cleared",
                actor_name=actor_name,
                detail={"issue_key": existing["issue_key"]},
            )
    return list_clarification_items(visit_id)


def _store_response(
    connection,
    *,
    item_id: str,
    answer_text: str,
    selected_candidate_id: str,
    response_status: str,
    invalid_reason: str,
    actor_name: str,
    timestamp: str,
) -> str:
    response_id = uuid4().hex
    connection.execute(
        """
        INSERT INTO clarification_responses (
            id, clarification_item_id, answer_text, selected_candidate_id, response_status, invalid_reason, actor_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (response_id, item_id, answer_text, selected_candidate_id, response_status, invalid_reason, actor_name, timestamp),
    )
    return response_id


def _create_resolution_record(
    connection,
    *,
    visit_id: str,
    text: str,
    actor_name: str,
    timestamp: str,
) -> str:
    record_id = uuid4().hex
    normalized_text = text.strip()
    connection.execute(
        """
        INSERT INTO work_records (
            id, visit_id, text, record_kind, created_by, linked_task_id, recorded_at, tags_json,
            client_idempotency_key, client_created_at, client_timezone, server_received_at, text_hash,
            processing_status, processing_error, processed_at, created_at
        ) VALUES (?, ?, ?, 'clarification_response', ?, '', ?, '[]', '', ?, 'server', ?, ?, 'completed', '', ?, ?)
        """,
        (
            record_id,
            visit_id,
            normalized_text,
            actor_name,
            timestamp,
            timestamp,
            timestamp,
            hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
            timestamp,
            timestamp,
        ),
    )
    return record_id


def _create_resolution_field(
    connection,
    *,
    visit_id: str,
    source_record_id: str,
    target_table: int,
    field_key: str,
    category: str,
    subject_code: str,
    subject_validation_status: str,
    subject_display_code: str,
    value: str,
    decision_reason: str,
    actor_name: str,
    timestamp: str,
) -> str:
    field_id = uuid4().hex
    connection.execute(
        """
        INSERT INTO confirmed_fields (
            id, visit_id, suggestion_id, source_record_id, target_table, field_key, category,
            subject_code, assertion_type, source_type, subject_validation_status, subject_display_code,
            value, decision, decision_reason, confirmed_by, confirmed_at, is_active
        ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, 'cra_resolution', 'clarification_resolution', ?, ?, ?, 'clarification_resolution', ?, ?, ?, 1)
        """,
        (
            field_id,
            visit_id,
            source_record_id,
            target_table,
            field_key,
            category,
            subject_code,
            subject_validation_status,
            subject_display_code,
            value.strip(),
            decision_reason.strip(),
            actor_name,
            timestamp,
        ),
    )
    return field_id


def _create_or_reuse_context_escalation(
    connection,
    *,
    visit: Any,
    item: dict[str, Any],
    actor_name: str,
    note: str,
    timestamp: str,
) -> str:
    marker = f"[clarification:{item['id']}]"
    source = dict(item.get("source") or {})
    conflict_kind = str(source.get("conflict_kind") or "")
    existing = connection.execute(
        """
        SELECT id FROM operation_escalations
        WHERE visit_id = ? AND status IN ('open', 'acknowledged') AND description LIKE ?
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        (item["visit_id"], f"%{marker}%"),
    ).fetchone()
    if existing is not None:
        return str(existing["id"])
    escalation_id = uuid4().hex
    rule_pack = dict(source.get("rule_pack") or {})
    rule_label = " · ".join(
        part for part in (str(rule_pack.get("name") or "").strip(), str(rule_pack.get("version") or "").strip()) if part
    ) or "冻结规则包"
    if conflict_kind == "template_rule_contract":
        title = "模板／规则包契约需人工确认"
        description = (
            f"{marker} 规则包：{rule_label}；模板契约：期望 {source.get('expected_template_profile') or '未登记'} / "
            f"当前 {source.get('actual_template_profile') or '未解析'}；SOP：期望 {source.get('expected_sop_version') or '未登记'} / "
            f"当前 {source.get('actual_sop_version') or '未登记'}；CRA 提请说明：{note}。"
        )
    else:
        title = "规则包适用期需人工确认"
        description = (
            f"{marker} 规则包：{rule_label}；活动日期：{source.get('activity_start_date') or '未登记'} 至 "
            f"{source.get('activity_end_date') or '未登记'}；CRA 提请说明：{note}。"
        )
    connection.execute(
        """
        INSERT INTO operation_escalations (
            id, project_id, visit_id, action_item_id, title, description, severity, target_role, status, created_by, created_at
        ) VALUES (?, ?, ?, NULL, ?, ?, 'high', 'PM_LM', 'open', ?, ?)
        """,
        (escalation_id, visit["project_id"], item["visit_id"], title, description, actor_name, timestamp),
    )
    _audit(
        connection,
        project_id=visit["project_id"],
        visit_id=item["visit_id"],
        entity_type="operation_escalation",
        entity_id=escalation_id,
        action="created",
        actor_name=actor_name,
        detail={"clarification_item_id": item["id"], "conflict_kind": conflict_kind, "target_role": "PM_LM", "severity": "high"},
    )
    return escalation_id


def _invalid_response(
    connection,
    *,
    visit: Any,
    item: dict[str, Any],
    answer_text: str,
    selected_candidate_id: str,
    invalid_reason: str,
    actor_name: str,
    timestamp: str,
) -> dict[str, Any]:
    _store_response(
        connection,
        item_id=item["id"],
        answer_text=answer_text,
        selected_candidate_id=selected_candidate_id,
        response_status="invalid",
        invalid_reason=invalid_reason,
        actor_name=actor_name,
        timestamp=timestamp,
    )
    invalid_attempts = int(item.get("invalid_attempts") or 0) + 1
    status = "manual_required" if invalid_attempts >= 2 else "open"
    connection.execute(
        "UPDATE clarification_items SET invalid_attempts = ?, status = ?, updated_at = ? WHERE id = ?",
        (invalid_attempts, status, timestamp, item["id"]),
    )
    _audit(
        connection,
        project_id=visit["project_id"],
        visit_id=item["visit_id"],
        entity_type="clarification_item",
        entity_id=item["id"],
        action="response_invalid" if status == "open" else "manual_required",
        actor_name=actor_name,
        detail={"reason": invalid_reason, "invalid_attempts": invalid_attempts},
    )
    updated = _item_by_id(connection, item["id"])
    return updated or item


def resolve_clarification_item(
    *,
    visit_id: str,
    item_id: str,
    action: Literal["answer", "select_candidate", "supplement", "manual_escalation"],
    answer_text: str,
    selected_candidate_id: str,
    actor_name: str,
) -> dict[str, Any]:
    normalized_answer = answer_text.strip()
    normalized_candidate_id = selected_candidate_id.strip()
    timestamp = _now()
    with transaction() as connection:
        visit = connection.execute("SELECT id, project_id, status FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if visit is None:
            raise ValueError("未找到当前访视")
        if visit["status"] not in {"draft", "returned"}:
            raise ValueError("当前报告已提交审核或已批准，不能处理 CRA 确认台账")
        item = _item_by_id(connection, item_id)
        if item is None or item["visit_id"] != visit_id:
            raise ValueError("未找到该访视的缺失或冲突问题")
        if item["status"] not in {"open", "manual_required"}:
            raise ValueError("该问题已处理")

        source = dict(item.get("source") or {})
        conflict_kind = str(source.get("conflict_kind") or "")
        if conflict_kind == "action_closure":
            raise ValueError("行动项闭环问题必须在行动项区域修正状态、关闭说明或附件证据后重新扫描")
        if conflict_kind in {"rule_period", "template_rule_contract"}:
            if action != "manual_escalation" or not normalized_answer:
                return _invalid_response(
                    connection,
                    visit=visit,
                    item=item,
                    answer_text=normalized_answer,
                    selected_candidate_id=normalized_candidate_id,
                    invalid_reason="该冻结配置冲突只能填写人工升级说明并发起 PM/LM 待办，不能以候选文本替代配置适用性确认。",
                    actor_name=actor_name,
                    timestamp=timestamp,
                )
            response_id = _store_response(
                connection,
                item_id=item["id"],
                answer_text=normalized_answer,
                selected_candidate_id="",
                response_status="escalated",
                invalid_reason="",
                actor_name=actor_name,
                timestamp=timestamp,
            )
            escalation_id = _create_or_reuse_context_escalation(
                connection,
                visit=visit,
                item=item,
                actor_name=actor_name,
                note=normalized_answer,
                timestamp=timestamp,
            )
            resolution = {
                "mode": "manual_escalation",
                "response_id": response_id,
                "escalation_id": escalation_id,
                "note": normalized_answer,
            }
            connection.execute(
                """
                UPDATE clarification_items
                SET status = 'manual_required', resolution_json = ?, invalid_attempts = 0,
                    updated_at = ?, resolved_at = '', resolved_by = ''
                WHERE id = ?
                """,
                (json.dumps(resolution, ensure_ascii=False), timestamp, item["id"]),
            )
            _audit(
                connection,
                project_id=visit["project_id"],
                visit_id=visit_id,
                entity_type="clarification_item",
                entity_id=item["id"],
                action="manual_escalation",
                actor_name=actor_name,
                detail={"issue_key": item["issue_key"], "resolution": resolution},
            )
            updated = _item_by_id(connection, item["id"])
            return updated or item

        if item["issue_type"] == "missing":
            if item.get("target_task_id"):
                return _invalid_response(
                    connection,
                    visit=visit,
                    item=item,
                    answer_text=normalized_answer,
                    selected_candidate_id=normalized_candidate_id,
                    invalid_reason="该问题需要在任务执行区补录监查结论和证据。",
                    actor_name=actor_name,
                    timestamp=timestamp,
                )
            if action != "answer" or not normalized_answer:
                return _invalid_response(
                    connection,
                    visit=visit,
                    item=item,
                    answer_text=normalized_answer,
                    selected_candidate_id=normalized_candidate_id,
                    invalid_reason="请提供该必填字段的 CRA 已确认内容。",
                    actor_name=actor_name,
                    timestamp=timestamp,
                )
            response_id = _store_response(
                connection,
                item_id=item["id"],
                answer_text=normalized_answer,
                selected_candidate_id="",
                response_status="valid",
                invalid_reason="",
                actor_name=actor_name,
                timestamp=timestamp,
            )
            record_id = _create_resolution_record(
                connection,
                visit_id=visit_id,
                text=normalized_answer,
                actor_name=actor_name,
                timestamp=timestamp,
            )
            field_id = _create_resolution_field(
                connection,
                visit_id=visit_id,
                source_record_id=record_id,
                target_table=int(item.get("target_table") or 0),
                field_key=str(item.get("field_key") or ""),
                category="clarification",
                subject_code="",
                subject_validation_status="not_provided",
                subject_display_code="",
                value=normalized_answer,
                decision_reason="CRA 在缺失信息确认台账中补录",
                actor_name=actor_name,
                timestamp=timestamp,
            )
            resolution = {
                "mode": "field_answer",
                "response_id": response_id,
                "source_record_id": record_id,
                "confirmed_field_id": field_id,
                "final_text": normalized_answer,
            }
        elif item["issue_type"] == "conflict":
            candidates = list(item.get("candidates") or [])
            candidate = next(
                (
                    value
                    for value in candidates
                    if value.get("id") == normalized_candidate_id
                    and value.get("kind") in {"confirmed_field", "frozen_document"}
                ),
                None,
            )
            if action == "select_candidate" and candidate is None:
                return _invalid_response(
                    connection,
                    visit=visit,
                    item=item,
                    answer_text=normalized_answer,
                    selected_candidate_id=normalized_candidate_id,
                    invalid_reason="请选择一条可采用的已确认或冻结文件候选，或改用经核对后的补充文本。",
                    actor_name=actor_name,
                    timestamp=timestamp,
                )
            if action == "supplement" and not normalized_answer:
                return _invalid_response(
                    connection,
                    visit=visit,
                    item=item,
                    answer_text=normalized_answer,
                    selected_candidate_id=normalized_candidate_id,
                    invalid_reason="补充决议必须填写经 CRA 核对后的文本。",
                    actor_name=actor_name,
                    timestamp=timestamp,
                )
            if action not in {"select_candidate", "supplement"}:
                return _invalid_response(
                    connection,
                    visit=visit,
                    item=item,
                    answer_text=normalized_answer,
                    selected_candidate_id=normalized_candidate_id,
                    invalid_reason="请明确选择候选记录，或填写补充决议。",
                    actor_name=actor_name,
                    timestamp=timestamp,
                )
            if candidate is None and action == "supplement":
                candidate = next((value for value in candidates if value.get("kind") == "confirmed_field"), None)
            if candidate is None:
                return _invalid_response(
                    connection,
                    visit=visit,
                    item=item,
                    answer_text=normalized_answer,
                    selected_candidate_id=normalized_candidate_id,
                    invalid_reason="当前冲突缺少可用于生成 CRA 决议的记录候选，请转人工处理。",
                    actor_name=actor_name,
                    timestamp=timestamp,
                )
            final_text = normalized_answer or str(candidate.get("value") or "").strip()
            if not final_text:
                return _invalid_response(
                    connection,
                    visit=visit,
                    item=item,
                    answer_text=normalized_answer,
                    selected_candidate_id=normalized_candidate_id,
                    invalid_reason="决议文本不能为空。",
                    actor_name=actor_name,
                    timestamp=timestamp,
                )
            response_id = _store_response(
                connection,
                item_id=item["id"],
                answer_text=final_text,
                selected_candidate_id=str(candidate.get("id") or ""),
                response_status="valid",
                invalid_reason="",
                actor_name=actor_name,
                timestamp=timestamp,
            )
            record_id = _create_resolution_record(
                connection,
                visit_id=visit_id,
                text=f"CRA 冲突决议：{final_text}",
                actor_name=actor_name,
                timestamp=timestamp,
            )
            candidate_ids = [
                str(value.get("id") or "")
                for value in candidates
                if value.get("kind") == "confirmed_field" and str(value.get("id") or "")
            ]
            if candidate_ids:
                connection.execute(
                    "UPDATE confirmed_fields SET is_active = 0 WHERE visit_id = ? AND id IN ("
                    + ", ".join("?" for _ in candidate_ids)
                    + ")",
                    (visit_id, *candidate_ids),
                )
            source = dict(candidate.get("source") or {})
            field_id = _create_resolution_field(
                connection,
                visit_id=visit_id,
                source_record_id=record_id,
                target_table=int(candidate.get("target_table") or item.get("target_table") or 0),
                field_key=str(candidate.get("field_key") or item.get("field_key") or ""),
                category=str(candidate.get("category") or "clarification"),
                subject_code=str(candidate.get("subject_code") or ""),
                subject_validation_status="not_provided" if not candidate.get("subject_code") else "historical_unverified",
                subject_display_code=str(candidate.get("subject_display_code") or ""),
                value=final_text,
                decision_reason=f"CRA 处理受控文件版本冲突：{item.get('reason') or ''}",
                actor_name=actor_name,
                timestamp=timestamp,
            )
            resolution = {
                "mode": "selected_candidate" if action == "select_candidate" else "supplement",
                "response_id": response_id,
                "selected_candidate_id": candidate.get("id", ""),
                "source_record_id": record_id,
                "confirmed_field_id": field_id,
                "superseded_confirmed_field_ids": candidate_ids,
                "final_text": final_text,
                "selected_source_record_id": source.get("source_record_id", ""),
            }
        else:
            raise ValueError("当前问题类型不受支持")

        connection.execute(
            """
            UPDATE clarification_items
            SET status = 'resolved', resolution_json = ?, invalid_attempts = 0,
                updated_at = ?, resolved_at = ?, resolved_by = ?
            WHERE id = ?
            """,
            (json.dumps(resolution, ensure_ascii=False), timestamp, timestamp, actor_name, item["id"]),
        )
        connection.execute("UPDATE visits SET updated_at = ? WHERE id = ?", (timestamp, visit_id))
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="clarification_item",
            entity_id=item["id"],
            action="resolved",
            actor_name=actor_name,
            detail={"issue_key": item["issue_key"], "issue_type": item["issue_type"], "resolution": resolution},
        )
        updated = _item_by_id(connection, item["id"])
    # Re-evaluate after a valid CRA decision. A decision that still conflicts with
    # the frozen visit context remains visible as an open issue instead of being
    # silently treated as cleared.
    refreshed_items = refresh_clarification_items(visit_id=visit_id, actor_name="系统")
    return next((value for value in refreshed_items if value["id"] == item_id), updated or {})
