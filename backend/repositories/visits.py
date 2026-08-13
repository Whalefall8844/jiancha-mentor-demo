from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..database import get_connection, transaction
from ..seed_data import TABLE_TITLES
from ..services.rule_eligibility import assess_rule_pack_for_visit
from ..services.project_eligibility import get_current_approved_assessment
from ..services.system_checks import SYSTEM_CHECK_TASK_TYPE, normalize_system_checks
from .controlled_data import resolve_frozen_master_data


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _row(row) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("snapshot_json", "detail_json", "preview_json", "tags_json"):
        if key in data:
            fallback = "[]" if key == "tags_json" else "{}"
            data[key.removesuffix("_json")] = json.loads(data.pop(key) or fallback)
    return data


def _rows(rows) -> list[dict[str, Any]]:
    return [_row(row) for row in rows]


def list_visits(project_id: str, site_id: str | None = None) -> list[dict[str, Any]]:
    conditions = ["v.project_id = ?"]
    values: list[str] = [project_id]
    if site_id:
        conditions.append("v.site_id = ?")
        values.append(site_id)
    where = " AND ".join(conditions)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT v.*, s.name AS site_name, t.name AS template_name, t.version AS template_version,
                (SELECT COUNT(*) FROM report_revisions rr WHERE rr.visit_id = v.id) AS revision_count,
                (SELECT COUNT(*) FROM report_revisions rr WHERE rr.visit_id = v.id AND rr.revision_type = 'formal') AS formal_revision_count,
                CASE
                    WHEN v.status = 'draft'
                     AND NOT EXISTS (
                        SELECT 1 FROM report_revisions rr
                        WHERE rr.visit_id = v.id AND rr.revision_type = 'formal'
                     )
                    THEN 1
                    ELSE 0
                END AS cancellation_eligible,
                v.status AS latest_revision_status
            FROM visits v
            JOIN sites s ON s.id = v.site_id
            JOIN templates t ON t.id = v.template_id
            WHERE {where}
            ORDER BY v.visit_date DESC, v.code DESC
            """,
            values,
        ).fetchall()
    return _rows(rows)


def _normalize_history_finding_text(value: str) -> str:
    """Provide a transparent, exact-match key without clinical inference."""
    return " ".join(str(value or "").casefold().split())


def get_project_history_insights(
    project_id: str,
    *,
    site_id: str | None = None,
    as_of: str = "",
) -> dict[str, Any]:
    """Summarize retained project history without changing any source record."""
    cutoff = as_of.strip() or datetime.now().strftime("%Y-%m-%d")
    conditions = ["visit.project_id = ?", "visit.visit_date <= ?"]
    values: list[str] = [project_id, cutoff]
    if site_id:
        conditions.append("visit.site_id = ?")
        values.append(site_id)
    where = " AND ".join(conditions)

    with get_connection() as connection:
        site_row = None
        if site_id:
            site_row = connection.execute(
                "SELECT id, code, name FROM sites WHERE id = ? AND project_id = ?",
                (site_id, project_id),
            ).fetchone()

        visit_count = connection.execute(
            f"SELECT COUNT(*) AS count FROM visits visit WHERE {where}",
            values,
        ).fetchone()["count"]

        report_rows = connection.execute(
            f"""
            SELECT revision.id,
                revision.visit_id,
                revision.version_number,
                revision.revision_type,
                revision.status AS revision_status,
                revision.file_name,
                revision.generated_at,
                revision.submitted_at,
                revision.created_at,
                visit.code AS visit_code,
                visit.visit_type,
                visit.visit_date,
                visit.status AS visit_status,
                site.id AS site_id,
                site.code AS site_code,
                site.name AS site_name
            FROM report_revisions revision
            JOIN visits visit ON visit.id = revision.visit_id
            JOIN sites site ON site.id = visit.site_id
            WHERE {where}
            ORDER BY visit.visit_date DESC, revision.created_at DESC, revision.rowid DESC
            """,
            values,
        ).fetchall()

        finding_rows = connection.execute(
            f"""
            SELECT finding.id,
                finding.category,
                finding.description,
                finding.severity,
                finding.status,
                finding.created_at,
                visit.id AS visit_id,
                visit.code AS visit_code,
                visit.visit_date,
                site.id AS site_id,
                site.code AS site_code,
                site.name AS site_name
            FROM findings finding
            JOIN visits visit ON visit.id = finding.visit_id
            JOIN sites site ON site.id = visit.site_id
            WHERE {where}
            ORDER BY visit.visit_date DESC, finding.created_at DESC, finding.rowid DESC
            """,
            values,
        ).fetchall()

        action_rows = connection.execute(
            f"""
            SELECT action_item.id,
                action_item.visit_id,
                action_item.source_action_item_id,
                action_item.title,
                action_item.description,
                action_item.owner,
                action_item.due_date,
                action_item.status,
                action_item.created_at,
                action_item.updated_at,
                action_item.closed_at,
                visit.code AS visit_code,
                visit.visit_date,
                site.id AS site_id,
                site.code AS site_code,
                site.name AS site_name,
                CASE WHEN action_item.due_date <> '' AND action_item.due_date < ? THEN 1 ELSE 0 END AS is_overdue
            FROM action_items action_item
            JOIN visits visit ON visit.id = action_item.visit_id
            JOIN sites site ON site.id = visit.site_id
            WHERE {where}
              AND action_item.status IN ('open', 'in_progress')
            ORDER BY is_overdue DESC,
                CASE WHEN action_item.due_date = '' THEN 1 ELSE 0 END,
                action_item.due_date,
                visit.visit_date DESC,
                action_item.created_at DESC
            """,
            [cutoff, *values],
        ).fetchall()

    reports = _rows(report_rows)
    repeated_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _rows(finding_rows):
        category = str(row.get("category") or "监查发现").strip() or "监查发现"
        normalized_description = _normalize_history_finding_text(str(row.get("description") or ""))
        if not normalized_description:
            continue
        key = (category.casefold(), normalized_description)
        source = {
            "finding_id": row["id"],
            "visit_id": row["visit_id"],
            "visit_code": row["visit_code"],
            "visit_date": row["visit_date"],
            "site_id": row["site_id"],
            "site_code": row["site_code"],
            "site_name": row["site_name"],
            "description": row["description"],
            "severity": row["severity"],
            "status": row["status"],
            "created_at": row["created_at"],
        }
        group = repeated_by_key.get(key)
        if group is None:
            group = {
                "key": f"{key[0]}::{key[1]}",
                "category": category,
                "description": row["description"],
                "count": 0,
                "site_ids": set(),
                "latest_found_at": row["created_at"],
                "source_visits": [],
            }
            repeated_by_key[key] = group
        group["count"] += 1
        group["site_ids"].add(row["site_id"])
        group["source_visits"].append(source)
        if str(row["created_at"]) >= str(group["latest_found_at"]):
            group["latest_found_at"] = row["created_at"]
            group["description"] = row["description"]

    repeated_findings: list[dict[str, Any]] = []
    for group in repeated_by_key.values():
        if group["count"] < 2:
            continue
        sources = sorted(
            group["source_visits"],
            key=lambda item: (str(item["visit_date"]), str(item["created_at"])),
            reverse=True,
        )
        repeated_findings.append(
            {
                "key": group["key"],
                "category": group["category"],
                "description": group["description"],
                "count": group["count"],
                "site_count": len(group["site_ids"]),
                "latest_found_at": group["latest_found_at"],
                "source_visits": sources,
            }
        )
    repeated_findings.sort(key=lambda item: (item["count"], str(item["latest_found_at"])), reverse=True)

    open_actions = _rows(action_rows)
    for action in open_actions:
        action["is_overdue"] = bool(action.get("is_overdue"))

    return {
        "scope": {
            "project_id": project_id,
            "site_id": site_id or "",
            "site_name": site_row["name"] if site_row is not None else "",
            "as_of": cutoff,
            "visit_count": visit_count,
            "formal_report_count": sum(1 for report in reports if report.get("revision_type") == "formal"),
            "repeated_finding_count": len(repeated_findings),
            "open_action_count": len(open_actions),
            "overdue_action_count": sum(1 for action in open_actions if action["is_overdue"]),
        },
        "reports": reports,
        "repeated_findings": repeated_findings,
        "open_actions": open_actions,
    }


def get_visit(visit_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT v.*, p.code AS project_code, p.name AS project_name, p.sponsor AS sponsor, p.metadata_json,
                   s.code AS site_code, s.name AS site_name, s.pi_name, s.ethics_date, s.protocol_version, s.icf_version,
                   t.name AS template_name, t.version AS template_version, t.docx_path, t.table_count,
                   rp.name AS rule_pack_name, rp.version AS rule_pack_version, rp.content_json
            FROM visits v
            JOIN projects p ON p.id = v.project_id
            JOIN sites s ON s.id = v.site_id
            JOIN templates t ON t.id = v.template_id
            JOIN rule_packs rp ON rp.id = v.rule_pack_id
            WHERE v.id = ?
            """,
            (visit_id,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["project_metadata"] = json.loads(data.pop("metadata_json") or "{}")
    data["rule_pack_content"] = json.loads(data.pop("content_json") or "{}")
    data["snapshot"] = json.loads(data.pop("snapshot_json") or "{}")
    return data


def _active_template_id(connection) -> str:
    row = connection.execute("SELECT id FROM templates WHERE status = 'active' ORDER BY created_at LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("没有可用的 Word 模板")
    return row["id"]


def _active_rule_pack_id(connection, project_id: str, visit_date: str) -> str:
    rows = connection.execute(
        """
        SELECT id, name, version, effective_from, effective_to, status
        FROM rule_packs
        WHERE project_id = ? AND status = 'active'
        ORDER BY effective_from DESC, version DESC
        """,
        (project_id,),
    ).fetchall()
    for row in rows:
        if assess_rule_pack_for_visit(dict(row), visit_date).get("selectable"):
            return row["id"]
    raise ValueError(f"项目没有适用于 {visit_date} 的已启用规则包")


def create_default_tasks(
    connection,
    visit_id: str,
    created_at: str,
    template_id: str,
    rule_content: dict[str, Any] | None = None,
    template_task_completeness_mode: str = "mapping_required",
) -> None:
    initial_status = {
        1: ("已映射", "项目固定信息已载入"),
        2: ("已映射", "访视快照已创建"),
        4: ("已映射", "招募数据待 CRA 更新"),
    }
    mappings = connection.execute(
        """
        SELECT table_index, field_key, target_description, required
        FROM template_mappings
        WHERE template_id = ?
        ORDER BY table_index
        """,
        (template_id,),
    ).fetchall()
    task_specs = (
        [
            (
                int(mapping["table_index"]),
                (mapping["field_key"] or f"table_{mapping['table_index']}").strip(),
                (mapping["target_description"] or f"表 {mapping['table_index']}").strip(),
                bool(mapping["required"]),
            )
            for mapping in mappings
        ]
        if mappings
        else [(index, f"table_{index}", title, index in {7, 8, 11, 13, 14}) for index, title in enumerate(TABLE_TITLES, start=1)]
    )
    for index, field_key, title, mapping_required in task_specs:
        requires_evidence = template_task_completeness_mode == "all_mappings" or (
            template_task_completeness_mode == "mapping_required" and mapping_required
        )
        status, evidence = initial_status.get(index, ("待补录", "待 CRA 记录或确认"))
        connection.execute(
            """
            INSERT INTO visit_tasks (id, visit_id, table_index, task_type, field_key, title, status, evidence, requires_evidence, created_at, updated_at)
            VALUES (?, ?, ?, 'template_table', ?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid4().hex, visit_id, index, field_key, title, status, evidence, 1 if requires_evidence else 0, created_at, created_at),
        )

    for spec in normalize_system_checks(rule_content or {}):
        connection.execute(
            """
            INSERT INTO visit_tasks (id, visit_id, table_index, task_type, field_key, title, status, evidence, requires_evidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, '待补录', '', ?, ?, ?)
            """,
            (
                uuid4().hex,
                visit_id,
                spec["table_index"],
                SYSTEM_CHECK_TASK_TYPE,
                spec["field_key"],
                spec["title"],
                1 if spec["requires_evidence"] else 0,
                created_at,
                created_at,
            ),
        )


def create_visit(
    *,
    project_id: str,
    site_id: str,
    code: str,
    visit_type: str,
    visit_date: str,
    activity_start_date: str = "",
    visit_method: str = "现场",
    visit_location: str = "",
    contact_persons: str = "",
    report_date: str | None = None,
    site_team: str = "",
    monitoring_team: str = "",
    next_visit: str = "",
    cra_name: str = "演示 CRA",
    template_id: str | None = None,
    rule_pack_id: str | None = None,
) -> dict[str, Any]:
    visit_id = uuid4().hex
    timestamp = _now()
    with transaction() as connection:
        actual_template_id = template_id or _active_template_id(connection)
        actual_rule_pack_id = rule_pack_id or _active_rule_pack_id(connection, project_id, visit_date.strip())
        template = connection.execute(
            "SELECT id, name, version, table_count, status, metadata_json FROM templates WHERE id = ?",
            (actual_template_id,),
        ).fetchone()
        if template is None:
            raise ValueError("未找到 Word 模板")
        if template["status"] != "active":
            raise ValueError("只能选用已启用的 Word 模板创建访视")
        template_field_slots = [
            dict(row)
            for row in connection.execute(
                """
                SELECT table_index, target_kind, label, field_key, target_locator, value_source, required
                FROM template_field_slots
                WHERE template_id = ?
                ORDER BY target_kind, table_index, created_at, id
                """,
                (actual_template_id,),
            ).fetchall()
        ]
        template_metadata = json.loads(template["metadata_json"] or "{}")
        template_completeness_rules = dict(template_metadata.get("template_completeness_rules") or {})
        task_completeness_mode = str(template_completeness_rules.get("task_mode") or "mapping_required")
        field_completeness_mode = str(template_completeness_rules.get("field_mode") or "slot_required")
        if task_completeness_mode not in {"mapping_required", "all_mappings", "none"}:
            task_completeness_mode = "mapping_required"
        if field_completeness_mode not in {"slot_required", "all_confirmed_text_slots", "none"}:
            field_completeness_mode = "slot_required"
        template_completeness_rules = {
            "task_mode": task_completeness_mode,
            "field_mode": field_completeness_mode,
        }
        rule_pack = connection.execute(
            "SELECT id, name, version, effective_from, effective_to, content_json, status FROM rule_packs WHERE id = ? AND project_id = ?",
            (actual_rule_pack_id, project_id),
        ).fetchone()
        if rule_pack is None:
            raise ValueError("项目没有可用规则包")
        if rule_pack["status"] != "active":
            raise ValueError("只能选用经审批启用的规则包创建访视")
        rule_eligibility = assess_rule_pack_for_visit(dict(rule_pack), visit_date.strip())
        if not rule_eligibility["selectable"]:
            raise ValueError(f"所选规则包不适用于该访视日期：{rule_eligibility['message']}")
        project = connection.execute("SELECT metadata_json FROM projects WHERE id = ?", (project_id,)).fetchone()
        project_metadata = json.loads(project["metadata_json"] or "{}") if project else {}
        blinding_mode = str(project_metadata.get("blinding_mode") or "open_label")
        if blinding_mode not in {"open_label", "blinded_with_separation"}:
            blinding_mode = "open_label"
        resolved_visit_date = visit_date.strip()
        resolved_activity_start_date = activity_start_date.strip() or resolved_visit_date
        resolved_visit_method = visit_method.strip() or "现场"
        resolved_visit_location = visit_location.strip()
        resolved_contact_persons = contact_persons.strip()
        eligibility_snapshot = get_current_approved_assessment(
            project_id,
            resolved_visit_date,
            connection=connection,
        )
        master_data = resolve_frozen_master_data(
            project_id=project_id,
            site_id=site_id,
            visit_date=resolved_visit_date,
            connection=connection,
        )
        resolved_site_team = site_team.strip() or str((master_data.get("site_profile") or {}).get("site_team") or "")
        rule_content = json.loads(rule_pack["content_json"] or "{}")
        snapshot = {
            "template_id": actual_template_id,
            "template_contract": {
                "template_id": template["id"],
                "name": template["name"],
                "version": template["version"],
                "table_count": int(template["table_count"] or 0),
                "profile": f"imv_{int(template['table_count'] or 0)}_table",
            },
            "template_field_slots": template_field_slots,
            "template_completeness_rules": template_completeness_rules,
            "rule_pack_id": actual_rule_pack_id,
            "rule_pack": {
                "id": rule_pack["id"],
                "name": rule_pack["name"],
                "version": rule_pack["version"],
                "effective_from": rule_pack["effective_from"],
                "effective_to": rule_pack["effective_to"],
                "content": rule_content,
                "eligibility": rule_eligibility,
            },
            "master_data": master_data,
            "visit_context": {
                "activity_start_date": resolved_activity_start_date,
                "activity_end_date": resolved_visit_date,
                "visit_method": resolved_visit_method,
                "visit_location": resolved_visit_location,
                "contact_persons": resolved_contact_persons,
            },
            "trial_control": {
                "blinding_mode": blinding_mode,
                "system_unblinds": False,
                "note": "系统不执行揭盲；盲态项目仅用于职责隔离和非盲态监查工作底稿。" if blinding_mode == "blinded_with_separation" else "开放标签项目；系统仍不记录或推断治疗分组。",
            },
            "project_sop_version": str(project_metadata.get("sop_version") or "").strip(),
            "frozen_at": timestamp,
            "recruitment": {
                "screened": 0,
                "screen_failed": 0,
                "treated": 0,
                "ae_dropout": 0,
                "other_dropout": 0,
                "completed_treatment": 0,
                "follow_up": 0,
                "follow_up_dropout": 0,
                "completed_follow_up": 0,
            },
        }
        if eligibility_snapshot:
            snapshot["project_eligibility"] = {
                **eligibility_snapshot,
                "assessment_as_of": resolved_visit_date,
                "frozen_at": timestamp,
            }
        connection.execute(
            """
            INSERT INTO visits (id, project_id, site_id, template_id, rule_pack_id, code, visit_type, visit_date, activity_start_date, visit_method, visit_location, contact_persons, report_date, site_team, monitoring_team, next_visit, cra_name, status, snapshot_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
            """,
            (
                visit_id,
                project_id,
                site_id,
                actual_template_id,
                actual_rule_pack_id,
                code.strip(),
                visit_type.strip(),
                resolved_visit_date,
                resolved_activity_start_date,
                resolved_visit_method,
                resolved_visit_location,
                resolved_contact_persons,
                (report_date or visit_date).strip(),
                resolved_site_team,
                monitoring_team.strip(),
                next_visit.strip(),
                cra_name.strip(),
                json.dumps(snapshot, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        create_default_tasks(
            connection,
            visit_id,
            timestamp,
            actual_template_id,
            rule_content,
            template_completeness_rules["task_mode"],
        )
    return get_visit(visit_id) or {}


def update_visit(visit_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {
        "code",
        "visit_type",
        "visit_date",
        "activity_start_date",
        "visit_method",
        "visit_location",
        "contact_persons",
        "report_date",
        "site_team",
        "monitoring_team",
        "next_visit",
        "cra_name",
        "status",
    }
    direct_patch = {key: str(value).strip() for key, value in patch.items() if key in allowed}
    current = get_visit(visit_id) if {"recruitment", "visit_date", "activity_start_date", "visit_method", "visit_location", "contact_persons"} & set(patch) else None
    if current:
        effective_visit_date = direct_patch.get("visit_date", str(current.get("visit_date") or "")).strip()
        current_context = dict(current.get("snapshot", {}).get("visit_context") or {})
        effective_start_date = direct_patch.get(
            "activity_start_date",
            str(current.get("activity_start_date") or current_context.get("activity_start_date") or effective_visit_date),
        ).strip() or effective_visit_date
        effective_method = direct_patch.get(
            "visit_method",
            str(current.get("visit_method") or current_context.get("visit_method") or "现场"),
        ).strip() or "现场"
        effective_location = direct_patch.get(
            "visit_location",
            str(current.get("visit_location") or current_context.get("visit_location") or ""),
        ).strip()
        effective_contacts = direct_patch.get(
            "contact_persons",
            str(current.get("contact_persons") or current_context.get("contact_persons") or ""),
        ).strip()
        if "activity_start_date" in direct_patch:
            direct_patch["activity_start_date"] = effective_start_date
        if "visit_method" in direct_patch:
            direct_patch["visit_method"] = effective_method
        snapshot = current["snapshot"]
        if "recruitment" in patch:
            snapshot["recruitment"] = patch["recruitment"]
        snapshot["visit_context"] = {
            "activity_start_date": effective_start_date,
            "activity_end_date": effective_visit_date,
            "visit_method": effective_method,
            "visit_location": effective_location,
            "contact_persons": effective_contacts,
        }
        direct_patch["snapshot_json"] = json.dumps(snapshot, ensure_ascii=False)
    fields = list(direct_patch.items())
    if not fields:
        return get_visit(visit_id)
    fields.append(("updated_at", _now()))
    assignments = ", ".join(f"{key} = ?" for key, _ in fields)
    with transaction() as connection:
        connection.execute(f"UPDATE visits SET {assignments} WHERE id = ?", (*[value for _, value in fields], visit_id))
    return get_visit(visit_id)


def list_tasks(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM visit_tasks WHERE visit_id = ? AND is_active = 1 ORDER BY table_index",
            (visit_id,),
        ).fetchall()
    return _rows(rows)


def get_task_for_table(visit_id: str, table_index: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM visit_tasks WHERE visit_id = ? AND table_index = ? AND is_active = 1", (visit_id, table_index)
        ).fetchone()
    return _row(row)


def update_task(
    task_id: str,
    *,
    status: str,
    evidence: str,
    execution_date: str = "",
    checked_scope: str = "",
    rationale: str = "",
    completed_by: str = "",
) -> dict[str, Any] | None:
    with transaction() as connection:
        visit = connection.execute(
            """
            SELECT v.status
            FROM visits v
            JOIN visit_tasks t ON t.visit_id = v.id
            WHERE t.id = ? AND t.is_active = 1
            """,
            (task_id,),
        ).fetchone()
        if visit is None:
            raise ValueError("未找到访视任务")
        if visit["status"] not in {"draft", "returned"}:
            raise ValueError("当前报告已提交审核或已批准，不能修改任务结论")
        connection.execute(
            """
            UPDATE visit_tasks
            SET status = ?, evidence = ?, execution_date = ?, checked_scope = ?, rationale = ?, completed_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, evidence, execution_date, checked_scope, rationale, completed_by, _now(), task_id),
        )
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM visit_tasks WHERE id = ? AND is_active = 1", (task_id,)).fetchone()
    return _row(row)


def bulk_update_tasks(visit_id: str, *, task_ids: list[str], status: str, evidence: str) -> list[dict[str, Any]]:
    unique_ids = list(dict.fromkeys(task_ids))
    if not unique_ids:
        return []
    placeholders = ", ".join("?" for _ in unique_ids)
    with transaction() as connection:
        visit = connection.execute("SELECT status FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if visit is None:
            raise ValueError("未找到当前访视")
        if visit["status"] not in {"draft", "returned"}:
            raise ValueError("当前报告已提交审核或已批准，不能批量修改任务")
        rows = connection.execute(
            f"SELECT id FROM visit_tasks WHERE visit_id = ? AND is_active = 1 AND id IN ({placeholders})",
            (visit_id, *unique_ids),
        ).fetchall()
        found_ids = {row["id"] for row in rows}
        if found_ids != set(unique_ids):
            raise ValueError("所选任务不属于当前访视")
        timestamp = _now()
        connection.execute(
            f"UPDATE visit_tasks SET status = ?, evidence = ?, updated_at = ? WHERE visit_id = ? AND is_active = 1 AND id IN ({placeholders})",
            (status, evidence, timestamp, visit_id, *unique_ids),
        )
        updated_rows = connection.execute(
            f"SELECT * FROM visit_tasks WHERE visit_id = ? AND is_active = 1 AND id IN ({placeholders}) ORDER BY table_index",
            (visit_id, *unique_ids),
        ).fetchall()
    return _rows(updated_rows)


def list_work_records(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM work_records WHERE visit_id = ? ORDER BY created_at DESC, rowid DESC", (visit_id,)).fetchall()
    return _rows(rows)


def list_suggestions(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM suggestions WHERE visit_id = ? AND is_active = 1 ORDER BY created_at DESC, rowid DESC",
            (visit_id,),
        ).fetchall()
    return _rows(rows)


def list_ai_executions(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM ai_executions WHERE visit_id = ? ORDER BY executed_at DESC, rowid DESC",
            (visit_id,),
        ).fetchall()
    return _rows(rows)


def list_confirmed_fields(visit_id: str, *, include_center_explanations: bool = False) -> list[dict[str, Any]]:
    """Return CRA-confirmed report facts, optionally with separately retained centre explanations.

    A centre explanation stays in the decision ledger for traceability, but it must not
    be treated as a CRA-verified report fact unless the caller explicitly asks for it.
    """
    center_explanation_clause = "" if include_center_explanations else (
        " AND assertion_type <> 'center_explanation' AND source_type <> 'center_explanation'"
    )
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM confirmed_fields WHERE visit_id = ? AND is_active = 1"
            + center_explanation_clause
            + " ORDER BY confirmed_at DESC",
            (visit_id,),
        ).fetchall()
    return _rows(rows)


def list_template_switches(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT template_switch.*,
                   source_template.name AS from_template_name,
                   source_template.version AS from_template_version,
                   target_template.name AS to_template_name,
                   target_template.version AS to_template_version
            FROM template_switches template_switch
            JOIN templates source_template ON source_template.id = template_switch.from_template_id
            JOIN templates target_template ON target_template.id = template_switch.to_template_id
            WHERE template_switch.visit_id = ?
            ORDER BY template_switch.created_at DESC, template_switch.rowid DESC
            """,
            (visit_id,),
        ).fetchall()
    return _rows(rows)


def list_visit_date_reassessments(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT reassessment.*,
                   from_rule.name AS from_rule_pack_name,
                   from_rule.version AS from_rule_pack_version,
                   to_rule.name AS to_rule_pack_name,
                   to_rule.version AS to_rule_pack_version
            FROM visit_date_reassessments reassessment
            JOIN rule_packs from_rule ON from_rule.id = reassessment.from_rule_pack_id
            JOIN rule_packs to_rule ON to_rule.id = reassessment.to_rule_pack_id
            WHERE reassessment.visit_id = ?
            ORDER BY reassessment.created_at DESC, reassessment.rowid DESC
            """,
            (visit_id,),
        ).fetchall()
    return _rows(rows)


def list_findings(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT finding.*,
                (
                    SELECT COUNT(*)
                    FROM action_items action_item
                    WHERE action_item.visit_id = finding.visit_id
                      AND (
                        action_item.finding_id = finding.id
                        OR EXISTS (
                            SELECT 1
                            FROM action_item_findings link
                            WHERE link.action_item_id = action_item.id
                              AND link.finding_id = finding.id
                        )
                      )
                ) AS action_item_count
            FROM findings finding
            WHERE finding.visit_id = ?
            ORDER BY finding.created_at DESC
            """,
            (visit_id,),
        ).fetchall()
    return _rows(rows)


def list_action_items(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT action_item.*,
                source_visit.code AS source_visit_code,
                source_visit.visit_date AS source_visit_date,
                (SELECT COUNT(*) FROM attachments attachment WHERE attachment.action_item_id = action_item.id) AS attachment_count
            FROM action_items action_item
            LEFT JOIN action_items source_action ON source_action.id = action_item.source_action_item_id
            LEFT JOIN visits source_visit ON source_visit.id = source_action.visit_id
            WHERE action_item.visit_id = ?
            ORDER BY action_item.status, action_item.due_date, action_item.created_at DESC
            """,
            (visit_id,),
        ).fetchall()
        actions = _rows(rows)
        if not actions:
            return actions
        action_ids = [action["id"] for action in actions]
        placeholders = ", ".join("?" for _ in action_ids)
        linked_rows = connection.execute(
            f"""
            SELECT link.action_item_id,
                finding.id, finding.subject_code, finding.category, finding.description,
                finding.severity, finding.status, finding.created_at
            FROM action_item_findings link
            JOIN findings finding ON finding.id = link.finding_id
            WHERE link.action_item_id IN ({placeholders})
            ORDER BY finding.created_at DESC
            """,
            action_ids,
        ).fetchall()
        legacy_rows = connection.execute(
            f"""
            SELECT action_item.id AS action_item_id,
                finding.id, finding.subject_code, finding.category, finding.description,
                finding.severity, finding.status, finding.created_at
            FROM action_items action_item
            JOIN findings finding ON finding.id = action_item.finding_id
            WHERE action_item.id IN ({placeholders})
            """,
            action_ids,
        ).fetchall()
    linked_by_action: dict[str, list[dict[str, Any]]] = {action_id: [] for action_id in action_ids}
    linked_ids_by_action: dict[str, set[str]] = {action_id: set() for action_id in action_ids}
    for row in [*linked_rows, *legacy_rows]:
        item = dict(row)
        action_id = item.pop("action_item_id")
        finding_id = item["id"]
        if finding_id in linked_ids_by_action[action_id]:
            continue
        linked_ids_by_action[action_id].add(finding_id)
        linked_by_action[action_id].append(item)
    for action in actions:
        linked_findings = linked_by_action[action["id"]]
        action["linked_findings"] = linked_findings
        action["finding_ids"] = [finding["id"] for finding in linked_findings]
    return actions


def list_historical_open_action_items(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        current_visit = connection.execute(
            "SELECT id, project_id, site_id, visit_date FROM visits WHERE id = ?",
            (visit_id,),
        ).fetchone()
        if current_visit is None:
            return []
        rows = connection.execute(
            """
            SELECT historical_action.*,
                source_visit.code AS source_visit_code,
                source_visit.visit_date AS source_visit_date,
                source_visit.id AS source_visit_id,
                (SELECT COUNT(*) FROM attachments attachment WHERE attachment.action_item_id = historical_action.id) AS attachment_count
            FROM action_items historical_action
            JOIN visits source_visit ON source_visit.id = historical_action.visit_id
            WHERE source_visit.project_id = ?
              AND source_visit.site_id = ?
              AND source_visit.id <> ?
              AND source_visit.visit_date <= ?
              AND historical_action.status IN ('open', 'in_progress')
              AND NOT EXISTS (
                SELECT 1
                FROM action_items follow_up
                WHERE follow_up.source_action_item_id = historical_action.id
              )
            ORDER BY source_visit.visit_date DESC, historical_action.created_at DESC
            """,
            (
                current_visit["project_id"],
                current_visit["site_id"],
                visit_id,
                current_visit["visit_date"],
            ),
        ).fetchall()
    return _rows(rows)


def list_attachments(visit_id: str, action_item_id: str | None = None) -> list[dict[str, Any]]:
    conditions = ["visit_id = ?"]
    values: list[str] = [visit_id]
    if action_item_id:
        conditions.append("action_item_id = ?")
        values.append(action_item_id)
    with get_connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM attachments WHERE {' AND '.join(conditions)} ORDER BY created_at DESC",
            values,
        ).fetchall()
    return _rows(rows)


def get_attachment(attachment_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    return _row(row)


def list_revisions(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM report_revisions WHERE visit_id = ? ORDER BY created_at DESC, rowid DESC", (visit_id,)
        ).fetchall()
    return _rows(rows)


def get_revision(revision_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM report_revisions WHERE id = ?", (revision_id,)).fetchone()
    return _row(row)


def next_revision_number(visit_id: str) -> str:
    revisions = list_revisions(visit_id)
    return f"V0.{len(revisions) + 1}"


def create_report_revision(
    visit_id: str,
    *,
    version_number: str | None = None,
    file_name: str = "",
    file_path: str = "",
    status: str = "draft",
    parent_revision_id: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    revision_id = uuid4().hex
    timestamp = _now()
    actual_version = version_number or next_revision_number(visit_id)
    generated_timestamp = timestamp if generated_at is None else generated_at
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO report_revisions (
                id, visit_id, parent_revision_id, version_number, revision_type, status,
                file_name, file_path, generated_at, created_at
            ) VALUES (?, ?, ?, ?, 'working', ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                visit_id,
                parent_revision_id,
                actual_version,
                status,
                file_name,
                file_path,
                generated_timestamp,
                timestamp,
            ),
        )
    return get_revision(revision_id) or {}


def update_working_revision_file(*, revision_id: str, file_name: str, file_path: str) -> dict[str, Any]:
    timestamp = _now()
    with transaction() as connection:
        updated = connection.execute(
            """
            UPDATE report_revisions
            SET file_name = ?, file_path = ?, generated_at = ?
            WHERE id = ? AND revision_type = 'working' AND status = 'draft'
            """,
            (file_name, file_path, timestamp, revision_id),
        ).rowcount
        if updated != 1:
            raise ValueError("当前工作修订不可写入报告文件")
    return get_revision(revision_id) or {}


def list_review_comments(revision_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT rc.*, rcr.resolution, rcr.note AS resolution_note, rcr.resolved_by
            FROM review_comments rc
            LEFT JOIN review_comment_resolutions rcr ON rcr.review_comment_id = rc.id
            WHERE rc.revision_id = ?
            ORDER BY rc.created_at DESC
            """,
            (revision_id,),
        ).fetchall()
    return _rows(rows)


def list_visit_review_comments(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT rc.*, rr.version_number, rcr.resolution, rcr.note AS resolution_note, rcr.resolved_by
            FROM review_comments rc
            JOIN report_revisions rr ON rr.id = rc.revision_id
            LEFT JOIN review_comment_resolutions rcr ON rcr.review_comment_id = rc.id
            WHERE rr.visit_id = ?
            ORDER BY rc.created_at DESC
            """,
            (visit_id,),
        ).fetchall()
    return _rows(rows)


def list_audit_events(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM audit_events WHERE visit_id = ? ORDER BY created_at DESC, rowid DESC", (visit_id,)
        ).fetchall()
    return _rows(rows)


def create_audit_event(*, project_id: str, visit_id: str | None, entity_type: str, entity_id: str, action: str, actor_name: str, detail: dict[str, Any] | None = None) -> None:
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO audit_events (id, project_id, visit_id, entity_type, entity_id, action, actor_name, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid4().hex, project_id, visit_id, entity_type, entity_id, action, actor_name, json.dumps(detail or {}, ensure_ascii=False), _now()),
        )
