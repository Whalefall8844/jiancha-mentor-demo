from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..database import get_connection, transaction
from ..repositories.controlled_data import resolve_frozen_master_data
from .rule_eligibility import assess_rule_pack_for_visit
from .system_checks import SYSTEM_CHECK_TASK_TYPE, normalize_system_checks


EDITABLE_VISIT_STATUSES = {"draft", "returned"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _parse_content(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content")
    if isinstance(content, dict):
        return content
    raw = row.get("content_json")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _rule_record(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["content"] = _parse_content(item)
    return item


def _rule_view(rule: dict[str, Any] | None, eligibility: dict[str, Any] | None = None) -> dict[str, Any]:
    if rule is None:
        return {"id": "", "name": "", "version": "", "status": "missing", "eligibility": eligibility or {}}
    return {
        "id": rule.get("id", ""),
        "name": rule.get("name", ""),
        "version": rule.get("version", ""),
        "effective_from": rule.get("effective_from", ""),
        "effective_to": rule.get("effective_to", ""),
        "status": rule.get("status", ""),
        "eligibility": eligibility or {},
    }


def _valid_visit_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _system_task_key(task: dict[str, Any]) -> str:
    key = str(task.get("field_key") or "").strip()
    if key and not key.startswith("table_"):
        return key
    return f"system_check:{str(task.get('title') or '').casefold().strip()}"


def _profile_view(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": profile.get("id", ""),
        "version_label": profile.get("version_label", ""),
        "pi_name": profile.get("pi_name", ""),
        "site_team": profile.get("site_team", ""),
        "display": profile.get("version_label", "") or profile.get("pi_name", "") or "未登记版本",
    }


def _document_view(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": document.get("id", ""),
        "title": document.get("title", ""),
        "version": document.get("version", ""),
        "version_date": document.get("version_date", ""),
        "display": document.get("display", ""),
    }


def _master_data_changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_profile = _profile_view(dict(before.get("site_profile") or {}))
    after_profile = _profile_view(dict(after.get("site_profile") or {}))
    profile_changed = before_profile != after_profile
    before_documents = dict(before.get("documents") or {})
    after_documents = dict(after.get("documents") or {})
    document_changes: list[dict[str, Any]] = []
    ordered_types = ["protocol", "icf", "ethics"]
    extra_types = sorted((set(before_documents) | set(after_documents)) - set(ordered_types))
    for document_type in [*ordered_types, *extra_types]:
        before_view = _document_view(dict(before_documents.get(document_type) or {}))
        after_view = _document_view(dict(after_documents.get(document_type) or {}))
        document_changes.append(
            {
                "document_type": document_type,
                "changed": before_view != after_view,
                "from": before_view,
                "to": after_view,
            }
        )
    return {
        "site_profile": {"changed": profile_changed, "from": before_profile, "to": after_profile},
        "documents": document_changes,
        "changed_count": int(profile_changed) + sum(item["changed"] for item in document_changes),
    }


def _site_team_change(visit: dict[str, Any], before_master_data: dict[str, Any], after_master_data: dict[str, Any]) -> dict[str, Any]:
    current = str(visit.get("site_team") or "").strip()
    previous_profile_team = str((before_master_data.get("site_profile") or {}).get("site_team") or "").strip()
    next_profile_team = str((after_master_data.get("site_profile") or {}).get("site_team") or "").strip()
    should_refresh = not current or current == previous_profile_team
    return {
        "action": "refresh" if should_refresh else "preserve_manual",
        "from": current,
        "to": next_profile_team if should_refresh else current,
        "message": "中心团队将随新日期的中心资料版本刷新。" if should_refresh else "保留当前已由 CRA 手工维护的中心团队。",
    }


def _visit_context(visit: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, str]:
    frozen = dict(snapshot.get("visit_context") or {})
    activity_end_date = str(visit.get("visit_date") or "").strip()
    return {
        "activity_start_date": str(
            visit.get("activity_start_date") or frozen.get("activity_start_date") or activity_end_date
        ).strip()
        or activity_end_date,
        "activity_end_date": activity_end_date,
        "visit_method": str(visit.get("visit_method") or frozen.get("visit_method") or "现场").strip() or "现场",
        "visit_location": str(visit.get("visit_location") or frozen.get("visit_location") or "").strip(),
        "contact_persons": str(visit.get("contact_persons") or frozen.get("contact_persons") or "").strip(),
    }


def _visit_context_change(visit: dict[str, Any], snapshot: dict[str, Any], proposed_date: str) -> dict[str, Any]:
    current = _visit_context(visit, snapshot)
    is_single_day = current["activity_start_date"] == current["activity_end_date"]
    next_context = {
        **current,
        "activity_start_date": proposed_date if is_single_day else current["activity_start_date"],
        "activity_end_date": proposed_date,
    }
    return {
        "from": current,
        "to": next_context,
        "activity_start_date_action": "synchronize_single_day" if is_single_day else "preserve_multi_day",
        "message": "原活动为单日监查，开始日期将随结束日期同步调整。"
        if is_single_day
        else "原活动为多日监查，保留既有开始日期，仅调整活动结束日期。",
    }


def _system_task_changes(connection, visit_id: str, target_rule_content: dict[str, Any]) -> dict[str, Any]:
    current_rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT * FROM visit_tasks
            WHERE visit_id = ? AND task_type = ? AND is_active = 1
            ORDER BY table_index
            """,
            (visit_id, SYSTEM_CHECK_TASK_TYPE),
        ).fetchall()
    ]
    target_specs = normalize_system_checks(target_rule_content)
    target_by_key = {str(item["field_key"]): item for item in target_specs}
    used_keys: set[str] = set()
    changes: list[dict[str, Any]] = []
    for task in current_rows:
        key = _system_task_key(task)
        target = target_by_key.get(key)
        if target is not None:
            used_keys.add(key)
            changes.append(
                {
                    "action": "preserve",
                    "task_id": task["id"],
                    "field_key": key,
                    "from_title": task["title"],
                    "to_title": target["title"],
                    "status": task["status"],
                }
            )
        else:
            changes.append(
                {
                    "action": "archive",
                    "task_id": task["id"],
                    "field_key": key,
                    "from_title": task["title"],
                    "to_title": "",
                    "status": task["status"],
                }
            )
    for spec in target_specs:
        if str(spec["field_key"]) not in used_keys:
            changes.append(
                {
                    "action": "new",
                    "task_id": "",
                    "field_key": spec["field_key"],
                    "from_title": "",
                    "to_title": spec["title"],
                    "status": "待补录",
                }
            )
    return {
        "changes": changes,
        "summary": {
            "preserved": sum(item["action"] == "preserve" for item in changes),
            "new": sum(item["action"] == "new" for item in changes),
            "archived": sum(item["action"] == "archive" for item in changes),
        },
    }


def _rule_choices(connection, visit: dict[str, Any], visit_date: str, target_rule_pack_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    rows = [
        _rule_record(row)
        for row in connection.execute(
            """
            SELECT * FROM rule_packs
            WHERE project_id = ? AND status = 'active'
            ORDER BY effective_from DESC, version DESC
            """,
            (visit["project_id"],),
        ).fetchall()
    ]
    choices = [{**_rule_view(row, assess_rule_pack_for_visit(row, visit_date)), "content": row["content"]} for row in rows]
    selectable = [item for item in choices if bool((item.get("eligibility") or {}).get("selectable"))]
    errors: list[str] = []
    selected: dict[str, Any] | None = None
    if target_rule_pack_id.strip():
        selected = next((item for item in choices if item["id"] == target_rule_pack_id.strip()), None)
        if selected is None:
            errors.append("未找到目标规则包，或该规则包不属于当前项目。")
        elif not bool((selected.get("eligibility") or {}).get("selectable")):
            errors.append(str((selected.get("eligibility") or {}).get("message") or "目标规则包不适用于新的访视日期。"))
    else:
        selected = next((item for item in selectable if item["id"] == visit["rule_pack_id"]), None)
        selected = selected or (selectable[0] if selectable else None)
    if selected is None and not errors:
        errors.append("该日期没有可重新冻结的已启用规则包。")
    return selected, choices, errors


def _preview_with_connection(connection, visit_id: str, visit_date: str, target_rule_pack_id: str = "") -> dict[str, Any]:
    row = connection.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
    if row is None:
        raise ValueError("未找到当前访视")
    visit = dict(row)
    proposed_date = visit_date.strip()
    snapshot = json.loads(visit.get("snapshot_json") or "{}")
    visit_context = _visit_context_change(visit, snapshot, proposed_date)
    errors: list[str] = []
    if visit["status"] not in EDITABLE_VISIT_STATUSES:
        errors.append("当前报告已提交审核或已批准，不能调整访视日期。")
    if not _valid_visit_date(proposed_date):
        errors.append("访视日期应使用 YYYY-MM-DD 格式。")

    current_rule_row = connection.execute("SELECT * FROM rule_packs WHERE id = ?", (visit["rule_pack_id"],)).fetchone()
    current_rule = _rule_record(current_rule_row) if current_rule_row is not None else None
    frozen_rule = dict(snapshot.get("rule_pack") or {})
    if current_rule is not None and not frozen_rule:
        frozen_rule = current_rule
    from_rule_view = _rule_view(frozen_rule or current_rule)
    eligible_rule_packs: list[dict[str, Any]] = []
    target_rule: dict[str, Any] | None = None
    if not errors:
        target_rule, eligible_rule_packs, selection_errors = _rule_choices(connection, visit, proposed_date, target_rule_pack_id)
        errors.extend(selection_errors)

    before_master_data = dict(snapshot.get("master_data") or {})
    after_master_data: dict[str, Any] = {}
    master_changes: dict[str, Any] = {"site_profile": {"changed": False, "from": {}, "to": {}}, "documents": [], "changed_count": 0}
    site_team = {"action": "preserve_manual", "from": visit.get("site_team", ""), "to": visit.get("site_team", ""), "message": "等待有效日期。"}
    system_changes: dict[str, Any] = {"changes": [], "summary": {"preserved": 0, "new": 0, "archived": 0}}
    if target_rule is not None and not errors:
        after_master_data = resolve_frozen_master_data(
            project_id=visit["project_id"],
            site_id=visit["site_id"],
            visit_date=proposed_date,
            connection=connection,
        )
        master_changes = _master_data_changes(before_master_data, after_master_data)
        site_team = _site_team_change(visit, before_master_data, after_master_data)
        try:
            system_changes = _system_task_changes(connection, visit_id, target_rule["content"])
        except ValueError as exc:
            errors.append(str(exc))

    summary = {
        "changed_master_items": master_changes["changed_count"],
        "preserved_system_tasks": system_changes["summary"]["preserved"],
        "new_system_tasks": system_changes["summary"]["new"],
        "archived_system_tasks": system_changes["summary"]["archived"],
        "site_team_action": site_team["action"],
    }
    return {
        "can_apply": not errors,
        "reason": "；".join(errors),
        "visit": {
            "id": visit["id"],
            "code": visit["code"],
            "status": visit["status"],
            "from_visit_date": visit["visit_date"],
            "to_visit_date": proposed_date,
        },
        "visit_context": visit_context,
        "from_rule_pack": from_rule_view,
        "to_rule_pack": _rule_view(target_rule, target_rule.get("eligibility") if target_rule else None),
        "eligible_rule_packs": eligible_rule_packs,
        "master_data_changes": master_changes,
        "site_team": site_team,
        "system_task_changes": system_changes,
        "summary": summary,
        "_after_master_data": after_master_data,
        "_target_rule_content": target_rule.get("content", {}) if target_rule else {},
    }


def preview_visit_date_reassessment(*, visit_id: str, visit_date: str, target_rule_pack_id: str = "") -> dict[str, Any]:
    with get_connection() as connection:
        preview = _preview_with_connection(connection, visit_id, visit_date, target_rule_pack_id)
    preview.pop("_after_master_data", None)
    preview.pop("_target_rule_content", None)
    return preview


def _rebase_system_tasks(connection, *, visit_id: str, target_rule_content: dict[str, Any], timestamp: str) -> None:
    rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT rowid AS row_id, * FROM visit_tasks
            WHERE visit_id = ? AND task_type = ?
            ORDER BY is_active DESC, table_index, rowid
            """,
            (visit_id, SYSTEM_CHECK_TASK_TYPE),
        ).fetchall()
    ]
    active_rows = [item for item in rows if bool(item.get("is_active"))]
    inactive_rows = [item for item in rows if not bool(item.get("is_active"))]
    active_by_key: dict[str, list[dict[str, Any]]] = {}
    inactive_by_key: dict[str, list[dict[str, Any]]] = {}
    active_by_title: dict[str, list[dict[str, Any]]] = {}
    inactive_by_title: dict[str, list[dict[str, Any]]] = {}
    for collection, by_key, by_title in (
        (active_rows, active_by_key, active_by_title),
        (inactive_rows, inactive_by_key, inactive_by_title),
    ):
        for item in collection:
            by_key.setdefault(_system_task_key(item), []).append(item)
            by_title.setdefault(str(item.get("title") or "").casefold().strip(), []).append(item)

    for offset, item in enumerate(rows, start=1):
        connection.execute(
            "UPDATE visit_tasks SET table_index = ?, is_active = 0, updated_at = ? WHERE id = ?",
            (-800000 - offset, timestamp, item["id"]),
        )

    used_ids: set[str] = set()

    def next_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        return next((item for item in candidates if item["id"] not in used_ids), None)

    for spec in normalize_system_checks(target_rule_content):
        key = str(spec["field_key"])
        title_key = str(spec["title"]).casefold().strip()
        selected = next_candidate(active_by_key.get(key, []))
        selected = selected or next_candidate(active_by_title.get(title_key, []))
        selected = selected or next_candidate(inactive_by_key.get(key, []))
        selected = selected or next_candidate(inactive_by_title.get(title_key, []))
        if selected is None:
            connection.execute(
                """
                INSERT INTO visit_tasks (
                    id, visit_id, table_index, task_type, field_key, title, status, evidence,
                    requires_evidence, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, '待补录', '', ?, 1, ?, ?)
                """,
                (
                    uuid4().hex,
                    visit_id,
                    int(spec["table_index"]),
                    SYSTEM_CHECK_TASK_TYPE,
                    key,
                    spec["title"],
                    1 if bool(spec["requires_evidence"]) else 0,
                    timestamp,
                    timestamp,
                ),
            )
        else:
            used_ids.add(selected["id"])
            connection.execute(
                """
                UPDATE visit_tasks
                SET table_index = ?, field_key = ?, title = ?, requires_evidence = ?, is_active = 1, updated_at = ?
                WHERE id = ?
                """,
                (
                    int(spec["table_index"]),
                    key,
                    spec["title"],
                    1 if bool(spec["requires_evidence"]) else 0,
                    timestamp,
                    selected["id"],
                ),
            )


def _audit(connection, *, visit: dict[str, Any], reassessment_id: str, actor_name: str, detail: dict[str, Any], timestamp: str) -> None:
    connection.execute(
        """
        INSERT INTO audit_events (id, project_id, visit_id, entity_type, entity_id, action, actor_name, detail_json, created_at)
        VALUES (?, ?, ?, 'visit_date_reassessment', ?, 'reassessed', ?, ?, ?)
        """,
        (
            uuid4().hex,
            visit["project_id"],
            visit["id"],
            reassessment_id,
            actor_name,
            json.dumps(detail, ensure_ascii=False),
            timestamp,
        ),
    )


def apply_visit_date_reassessment(*, visit_id: str, visit_date: str, target_rule_pack_id: str, actor_name: str) -> dict[str, Any]:
    timestamp = _now()
    with transaction() as connection:
        row = connection.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if row is None:
            raise ValueError("未找到当前访视")
        visit = dict(row)
        preview = _preview_with_connection(connection, visit_id, visit_date, target_rule_pack_id)
        if not preview["can_apply"]:
            raise ValueError(preview["reason"] or "当前访视不能重新冻结日期配置")
        target_rule_id = str(preview["to_rule_pack"]["id"])
        target_rule_row = connection.execute("SELECT * FROM rule_packs WHERE id = ?", (target_rule_id,)).fetchone()
        if target_rule_row is None:
            raise ValueError("未找到目标规则包")
        target_rule = _rule_record(target_rule_row)
        target_eligibility = assess_rule_pack_for_visit(target_rule, visit_date.strip())
        if not target_eligibility.get("selectable"):
            raise ValueError(str(target_eligibility.get("message") or "目标规则包不适用于新的访视日期。"))

        snapshot = json.loads(visit.get("snapshot_json") or "{}")
        snapshot["rule_pack_id"] = target_rule_id
        snapshot["rule_pack"] = {
            "id": target_rule["id"],
            "name": target_rule["name"],
            "version": target_rule["version"],
            "effective_from": target_rule.get("effective_from", ""),
            "effective_to": target_rule.get("effective_to", ""),
            "content": target_rule["content"],
            "eligibility": target_eligibility,
        }
        snapshot["master_data"] = preview["_after_master_data"]
        next_visit_context = dict(preview["visit_context"]["to"])
        snapshot["visit_context"] = next_visit_context
        snapshot["visit_date_reassessed_at"] = timestamp
        snapshot["visit_date_reassessment_count"] = int(snapshot.get("visit_date_reassessment_count") or 0) + 1
        next_site_team = str(preview["site_team"]["to"])
        _rebase_system_tasks(connection, visit_id=visit_id, target_rule_content=target_rule["content"], timestamp=timestamp)
        connection.execute(
            """
            UPDATE visits
            SET visit_date = ?, activity_start_date = ?, rule_pack_id = ?, site_team = ?, snapshot_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                visit_date.strip(),
                str(next_visit_context.get("activity_start_date") or visit_date.strip()),
                target_rule_id,
                next_site_team,
                json.dumps(snapshot, ensure_ascii=False),
                timestamp,
                visit_id,
            ),
        )
        reassessment_id = uuid4().hex
        public_preview = {key: value for key, value in preview.items() if not key.startswith("_")}
        actor = actor_name.strip() or "演示 CRA"
        connection.execute(
            """
            INSERT INTO visit_date_reassessments (
                id, visit_id, from_visit_date, to_visit_date, from_rule_pack_id, to_rule_pack_id,
                preview_json, actor_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reassessment_id,
                visit_id,
                visit["visit_date"],
                visit_date.strip(),
                visit["rule_pack_id"],
                target_rule_id,
                json.dumps(public_preview, ensure_ascii=False),
                actor,
                timestamp,
            ),
        )
        _audit(
            connection,
            visit=visit,
            reassessment_id=reassessment_id,
            actor_name=actor,
            detail={
                "from_visit_date": visit["visit_date"],
                "to_visit_date": visit_date.strip(),
                "from_rule_pack_id": visit["rule_pack_id"],
                "to_rule_pack_id": target_rule_id,
                "visit_context": preview["visit_context"],
                "summary": preview["summary"],
            },
            timestamp=timestamp,
        )
    return {"reassessment_id": reassessment_id, "preview": public_preview}
