from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..database import get_connection, transaction
from .system_checks import SYSTEM_CHECK_TASK_TYPE


EDITABLE_VISIT_STATUSES = {"draft", "returned"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _template(connection, template_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
    return dict(row) if row is not None else None


def _mappings(connection, template_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT table_index, field_key, target_description, required
        FROM template_mappings
        WHERE template_id = ?
        ORDER BY table_index
        """,
        (template_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _mapping_indexes(mappings: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]]]:
    by_key: dict[str, dict[str, Any]] = {}
    by_index: dict[int, dict[str, Any]] = {}
    for mapping in mappings:
        key = str(mapping.get("field_key") or "").strip()
        index = int(mapping["table_index"])
        if key and key not in by_key:
            by_key[key] = mapping
        by_index[index] = mapping
    return by_key, by_index


def _match_mapping(
    *,
    field_key: str,
    table_index: int,
    target_by_key: dict[str, dict[str, Any]],
    target_by_index: dict[int, dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    key = field_key.strip()
    if key and key in target_by_key:
        return target_by_key[key], "field_key"
    fallback = target_by_index.get(table_index)
    legacy_key = f"table_{table_index}"
    if (
        fallback is not None
        and key in {"", legacy_key}
        and str(fallback.get("field_key") or "").strip() == legacy_key
    ):
        return fallback, "table_index"
    return None, "unmapped"


def _template_view(template: dict[str, Any] | None) -> dict[str, Any]:
    if template is None:
        return {"id": "", "name": "", "version": "", "table_count": 0, "status": "missing"}
    return {
        "id": template["id"],
        "name": template["name"],
        "version": template["version"],
        "table_count": int(template.get("table_count") or 0),
        "status": template.get("status", ""),
    }


def _preview_with_connection(
    connection,
    visit_id: str,
    target_template_id: str,
    *,
    allow_inactive_target: bool = False,
) -> dict[str, Any]:
    visit_row = connection.execute(
        "SELECT id, project_id, template_id, status, code FROM visits WHERE id = ?", (visit_id,)
    ).fetchone()
    if visit_row is None:
        raise ValueError("未找到当前访视")
    visit = dict(visit_row)
    source_template = _template(connection, visit["template_id"])
    target_template = _template(connection, target_template_id)
    errors: list[str] = []
    if visit["status"] not in EDITABLE_VISIT_STATUSES:
        errors.append("当前报告已提交审核或已批准，不能更换模板")
    if target_template is None:
        errors.append("未找到目标 Word 模板")
    elif target_template.get("status") != "active" and not allow_inactive_target:
        errors.append("仅可切换到已启用的 Word 模板")
    if source_template is None:
        errors.append("当前访视的原模板不存在")
    if target_template_id == visit["template_id"]:
        errors.append("目标模板与当前模板相同")

    source_mappings = _mappings(connection, visit["template_id"]) if source_template else []
    target_mappings = _mappings(connection, target_template_id) if target_template else []
    target_by_key, target_by_index = _mapping_indexes(target_mappings)
    active_tasks = [
        dict(row)
        for row in connection.execute(
            """
            SELECT * FROM visit_tasks
            WHERE visit_id = ? AND task_type != ? AND is_active = 1
            ORDER BY table_index
            """,
            (visit_id, SYSTEM_CHECK_TASK_TYPE),
        ).fetchall()
    ]
    active_fields = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM confirmed_fields WHERE visit_id = ? AND is_active = 1 "
            "AND assertion_type <> 'center_explanation' AND source_type <> 'center_explanation' "
            "ORDER BY confirmed_at, rowid",
            (visit_id,),
        ).fetchall()
    ]
    active_suggestions = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM suggestions WHERE visit_id = ? AND is_active = 1 "
            "AND assertion_type <> 'center_explanation' AND source_type <> 'center_explanation' "
            "ORDER BY created_at, rowid",
            (visit_id,),
        ).fetchall()
    ]

    task_changes: list[dict[str, Any]] = []
    used_target_indexes: set[int] = set()
    for task in active_tasks:
        target, matched_by = _match_mapping(
            field_key=str(task.get("field_key") or ""),
            table_index=int(task["table_index"]),
            target_by_key=target_by_key,
            target_by_index=target_by_index,
        )
        if target is not None and int(target["table_index"]) not in used_target_indexes:
            used_target_indexes.add(int(target["table_index"]))
            task_changes.append(
                {
                    "action": "preserve",
                    "task_id": task["id"],
                    "source_table_index": task["table_index"],
                    "target_table_index": target["table_index"],
                    "title": task["title"],
                    "target_title": target.get("target_description") or f"表 {target['table_index']}",
                    "matched_by": matched_by,
                }
            )
        else:
            task_changes.append(
                {
                    "action": "hide",
                    "task_id": task["id"],
                    "source_table_index": task["table_index"],
                    "target_table_index": None,
                    "title": task["title"],
                    "target_title": "",
                    "matched_by": "unmapped",
                }
            )
    for mapping in target_mappings:
        if int(mapping["table_index"]) not in used_target_indexes:
            task_changes.append(
                {
                    "action": "new",
                    "task_id": "",
                    "source_table_index": None,
                    "target_table_index": mapping["table_index"],
                    "title": "",
                    "target_title": mapping.get("target_description") or f"表 {mapping['table_index']}",
                    "matched_by": "new_template_area",
                }
            )

    def preview_rows(rows: list[dict[str, Any]], label_key: str) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for row in rows:
            target, matched_by = _match_mapping(
                field_key=str(row.get("field_key") or ""),
                table_index=int(row["target_table"]),
                target_by_key=target_by_key,
                target_by_index=target_by_index,
            )
            changes.append(
                {
                    "id": row["id"],
                    "action": "preserve" if target is not None else "hide",
                    "source_table_index": row["target_table"],
                    "target_table_index": target["table_index"] if target is not None else None,
                    "label": row.get(label_key, ""),
                    "matched_by": matched_by,
                }
            )
        return changes

    field_changes = preview_rows(active_fields, "value")
    suggestion_changes = preview_rows(active_suggestions, "title")
    summary = {
        "preserved_tasks": sum(item["action"] == "preserve" for item in task_changes),
        "hidden_tasks": sum(item["action"] == "hide" for item in task_changes),
        "new_tasks": sum(item["action"] == "new" for item in task_changes),
        "migratable_confirmed_fields": sum(item["action"] == "preserve" for item in field_changes),
        "hidden_confirmed_fields": sum(item["action"] == "hide" for item in field_changes),
        "migratable_suggestions": sum(item["action"] == "preserve" for item in suggestion_changes),
        "hidden_suggestions": sum(item["action"] == "hide" for item in suggestion_changes),
    }
    return {
        "can_switch": not errors,
        "reason": "；".join(errors),
        "visit": {"id": visit["id"], "code": visit["code"], "status": visit["status"]},
        "from_template": _template_view(source_template),
        "to_template": _template_view(target_template),
        "summary": summary,
        "task_changes": task_changes,
        "field_changes": field_changes,
        "suggestion_changes": suggestion_changes,
        "source_mapping_count": len(source_mappings),
        "target_mapping_count": len(target_mappings),
    }


def preview_template_switch(*, visit_id: str, target_template_id: str) -> dict[str, Any]:
    with get_connection() as connection:
        return _preview_with_connection(connection, visit_id, target_template_id)


def _initial_task_values(table_index: int) -> tuple[str, str]:
    initial_status = {
        1: ("已映射", "项目固定信息已载入"),
        2: ("已映射", "访视快照已创建"),
        4: ("已映射", "招募数据待 CRA 更新"),
    }
    return initial_status.get(table_index, ("待补录", "待 CRA 记录或确认"))


def _activate_target_tasks(
    connection,
    *,
    visit_id: str,
    target_mappings: list[dict[str, Any]],
    timestamp: str,
    task_completeness_mode: str,
) -> dict[str, str]:
    rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT rowid AS row_id, * FROM visit_tasks
            WHERE visit_id = ? AND task_type != ?
            ORDER BY is_active DESC, table_index, rowid
            """,
            (visit_id, SYSTEM_CHECK_TASK_TYPE),
        ).fetchall()
    ]
    active_rows = [row for row in rows if bool(row.get("is_active"))]
    inactive_rows = [row for row in rows if not bool(row.get("is_active"))]
    used_ids: set[str] = set()
    active_by_key: dict[str, list[dict[str, Any]]] = {}
    inactive_by_key: dict[str, list[dict[str, Any]]] = {}
    active_by_index: dict[int, list[dict[str, Any]]] = {}
    for row in active_rows:
        active_by_key.setdefault(str(row.get("field_key") or "").strip(), []).append(row)
        active_by_index.setdefault(int(row["table_index"]), []).append(row)
    for row in inactive_rows:
        inactive_by_key.setdefault(str(row.get("field_key") or "").strip(), []).append(row)

    for offset, row in enumerate(rows, start=1):
        connection.execute(
            "UPDATE visit_tasks SET table_index = ?, is_active = 0, updated_at = ? WHERE id = ?",
            (-900000 - offset, timestamp, row["id"]),
        )

    task_ids_by_key: dict[str, str] = {}
    for mapping in target_mappings:
        field_key = str(mapping.get("field_key") or "").strip() or f"table_{mapping['table_index']}"
        selected: dict[str, Any] | None = None
        for candidate in active_by_key.get(field_key, []):
            if candidate["id"] not in used_ids:
                selected = candidate
                break
        legacy_key = f"table_{mapping['table_index']}"
        if selected is None and field_key == legacy_key:
            for candidate in active_by_index.get(int(mapping["table_index"]), []):
                if candidate["id"] not in used_ids and str(candidate.get("field_key") or "").strip() == legacy_key:
                    selected = candidate
                    break
        requires_evidence = task_completeness_mode == "all_mappings" or (
            task_completeness_mode == "mapping_required" and bool(mapping.get("required"))
        )
        if selected is None:
            for candidate in inactive_by_key.get(field_key, []):
                if candidate["id"] not in used_ids:
                    selected = candidate
                    break

        if selected is None:
            status, evidence = _initial_task_values(int(mapping["table_index"]))
            task_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO visit_tasks (
                    id, visit_id, table_index, task_type, field_key, title, status, evidence,
                    requires_evidence, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, 'template_table', ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    task_id,
                    visit_id,
                    int(mapping["table_index"]),
                    field_key,
                    str(mapping.get("target_description") or f"表 {mapping['table_index']}").strip(),
                    status,
                    evidence,
                    1 if requires_evidence else 0,
                    timestamp,
                    timestamp,
                ),
            )
        else:
            task_id = selected["id"]
            used_ids.add(task_id)
            connection.execute(
                """
                UPDATE visit_tasks
                SET table_index = ?, field_key = ?, title = ?, requires_evidence = ?, is_active = 1, updated_at = ?
                WHERE id = ?
                """,
                (
                    int(mapping["table_index"]),
                    field_key,
                    str(mapping.get("target_description") or f"表 {mapping['table_index']}").strip(),
                    1 if requires_evidence else 0,
                    timestamp,
                    task_id,
                ),
            )
        task_ids_by_key[field_key] = task_id
    return task_ids_by_key


def _activate_template_data(
    connection,
    *,
    visit_id: str,
    target_mappings: list[dict[str, Any]],
    task_ids_by_key: dict[str, str],
) -> None:
    target_by_key, target_by_index = _mapping_indexes(target_mappings)
    confirmed_rows = connection.execute(
        "SELECT * FROM confirmed_fields WHERE visit_id = ? "
        "AND assertion_type <> 'center_explanation' AND source_type <> 'center_explanation'",
        (visit_id,),
    ).fetchall()
    for row in confirmed_rows:
        item = dict(row)
        target, _ = _match_mapping(
            field_key=str(item.get("field_key") or ""),
            table_index=int(item["target_table"]),
            target_by_key=target_by_key,
            target_by_index=target_by_index,
        )
        if target is None:
            connection.execute("UPDATE confirmed_fields SET is_active = 0 WHERE id = ?", (item["id"],))
        else:
            connection.execute(
                "UPDATE confirmed_fields SET target_table = ?, is_active = 1 WHERE id = ?",
                (int(target["table_index"]), item["id"]),
            )

    suggestion_rows = connection.execute(
        "SELECT * FROM suggestions WHERE visit_id = ? "
        "AND assertion_type <> 'center_explanation' AND source_type <> 'center_explanation'",
        (visit_id,),
    ).fetchall()
    for row in suggestion_rows:
        item = dict(row)
        target, _ = _match_mapping(
            field_key=str(item.get("field_key") or ""),
            table_index=int(item["target_table"]),
            target_by_key=target_by_key,
            target_by_index=target_by_index,
        )
        if target is None:
            connection.execute("UPDATE suggestions SET is_active = 0 WHERE id = ?", (item["id"],))
        else:
            key = str(target.get("field_key") or "").strip()
            connection.execute(
                """
                UPDATE suggestions
                SET target_table = ?, target_task_id = ?, is_active = 1
                WHERE id = ?
                """,
                (int(target["table_index"]), task_ids_by_key.get(key), item["id"]),
            )


def _apply_template_switch(
    connection,
    *,
    visit: dict[str, Any],
    target_template_id: str,
    timestamp: str,
) -> dict[str, Any]:
    target_template = _template(connection, target_template_id)
    if target_template is None:
        raise ValueError("未找到目标 Word 模板")
    target_mappings = _mappings(connection, target_template_id)
    template_metadata = json.loads(target_template.get("metadata_json") or "{}")
    template_completeness_rules = dict(template_metadata.get("template_completeness_rules") or {})
    task_completeness_mode = str(template_completeness_rules.get("task_mode") or "mapping_required")
    field_completeness_mode = str(template_completeness_rules.get("field_mode") or "slot_required")
    if task_completeness_mode not in {"mapping_required", "all_mappings", "none"}:
        task_completeness_mode = "mapping_required"
    if field_completeness_mode not in {"slot_required", "all_confirmed_text_slots", "none"}:
        field_completeness_mode = "slot_required"
    task_ids_by_key = _activate_target_tasks(
        connection,
        visit_id=visit["id"],
        target_mappings=target_mappings,
        timestamp=timestamp,
        task_completeness_mode=task_completeness_mode,
    )
    _activate_template_data(
        connection,
        visit_id=visit["id"],
        target_mappings=target_mappings,
        task_ids_by_key=task_ids_by_key,
    )
    template_field_slots = [
        dict(row)
        for row in connection.execute(
            """
            SELECT table_index, target_kind, label, field_key, target_locator, value_source, required
            FROM template_field_slots
            WHERE template_id = ?
            ORDER BY target_kind, table_index, created_at, id
            """,
            (target_template_id,),
        ).fetchall()
    ]
    snapshot = json.loads(visit.get("snapshot_json") or "{}")
    snapshot["template_id"] = target_template_id
    snapshot["template_contract"] = {
        "template_id": target_template["id"],
        "name": target_template["name"],
        "version": target_template["version"],
        "table_count": int(target_template.get("table_count") or 0),
        "profile": f"imv_{int(target_template.get('table_count') or 0)}_table",
    }
    snapshot["template_field_slots"] = template_field_slots
    snapshot["template_completeness_rules"] = {
        "task_mode": task_completeness_mode,
        "field_mode": field_completeness_mode,
    }
    snapshot["template_switched_at"] = timestamp
    connection.execute(
        "UPDATE visits SET template_id = ?, snapshot_json = ?, updated_at = ? WHERE id = ?",
        (target_template_id, json.dumps(snapshot, ensure_ascii=False), timestamp, visit["id"]),
    )
    return task_ids_by_key


def _audit(connection, *, visit: dict[str, Any], entity_id: str, action: str, actor_name: str, detail: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO audit_events (id, project_id, visit_id, entity_type, entity_id, action, actor_name, detail_json, created_at)
        VALUES (?, ?, ?, 'template_switch', ?, ?, ?, ?, ?)
        """,
        (
            uuid4().hex,
            visit["project_id"],
            visit["id"],
            entity_id,
            action,
            actor_name,
            json.dumps(detail, ensure_ascii=False),
            _now(),
        ),
    )


def switch_template(*, visit_id: str, target_template_id: str, actor_name: str) -> dict[str, Any]:
    timestamp = _now()
    with transaction() as connection:
        visit_row = connection.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if visit_row is None:
            raise ValueError("未找到当前访视")
        visit = dict(visit_row)
        preview = _preview_with_connection(connection, visit_id, target_template_id)
        if not preview["can_switch"]:
            raise ValueError(preview["reason"] or "当前模板不能切换")
        switch_id = uuid4().hex
        _apply_template_switch(
            connection,
            visit=visit,
            target_template_id=target_template_id,
            timestamp=timestamp,
        )
        connection.execute(
            """
            INSERT INTO template_switches (
                id, visit_id, from_template_id, to_template_id, preview_json, actor_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                switch_id,
                visit_id,
                visit["template_id"],
                target_template_id,
                json.dumps(preview, ensure_ascii=False),
                actor_name.strip() or "演示 CRA",
                timestamp,
            ),
        )
        _audit(
            connection,
            visit=visit,
            entity_id=switch_id,
            action="switched",
            actor_name=actor_name.strip() or "演示 CRA",
            detail={
                "from_template_id": visit["template_id"],
                "to_template_id": target_template_id,
                "summary": preview["summary"],
            },
        )
    return {"switch_id": switch_id, "preview": preview}


def rollback_template_switch(*, visit_id: str, switch_id: str, actor_name: str) -> dict[str, Any]:
    timestamp = _now()
    with transaction() as connection:
        visit_row = connection.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if visit_row is None:
            raise ValueError("未找到当前访视")
        visit = dict(visit_row)
        if visit["status"] not in EDITABLE_VISIT_STATUSES:
            raise ValueError("当前报告已提交审核或已批准，不能恢复模板")
        switch_row = connection.execute(
            "SELECT * FROM template_switches WHERE id = ? AND visit_id = ?", (switch_id, visit_id)
        ).fetchone()
        if switch_row is None:
            raise ValueError("未找到该模板切换记录")
        switch = dict(switch_row)
        if switch.get("rolled_back_at"):
            raise ValueError("该模板切换已恢复")
        if visit["template_id"] != switch["to_template_id"]:
            raise ValueError("只能恢复当前模板对应的最近一次切换")
        preview = _preview_with_connection(
            connection,
            visit_id,
            switch["from_template_id"],
            allow_inactive_target=True,
        )
        if not preview["can_switch"]:
            raise ValueError(preview["reason"] or "无法恢复上一模板")
        _apply_template_switch(
            connection,
            visit=visit,
            target_template_id=switch["from_template_id"],
            timestamp=timestamp,
        )
        actor = actor_name.strip() or "演示 CRA"
        connection.execute(
            "UPDATE template_switches SET rolled_back_at = ?, rolled_back_by = ? WHERE id = ?",
            (timestamp, actor, switch_id),
        )
        _audit(
            connection,
            visit=visit,
            entity_id=switch_id,
            action="rolled_back",
            actor_name=actor,
            detail={
                "from_template_id": switch["to_template_id"],
                "to_template_id": switch["from_template_id"],
                "summary": preview["summary"],
            },
        )
    return {"switch_id": switch_id, "preview": preview}
