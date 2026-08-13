from __future__ import annotations

from copy import deepcopy
import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..database import get_connection, transaction
from ..repositories.controlled_data import resolve_frozen_master_data


EDITABLE_VISIT_STATUSES = {"draft", "returned"}
SITE_PROFILE_TARGET = "site_profile"
DOCUMENT_TARGET_PREFIX = "document:"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _profile_view(profile: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(profile.get("id") or ""),
        "version_label": str(profile.get("version_label") or ""),
        "pi_name": str(profile.get("pi_name") or ""),
        "site_team": str(profile.get("site_team") or ""),
        "display": str(profile.get("version_label") or profile.get("pi_name") or "未登记版本"),
    }


def _document_view(document: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(document.get("id") or ""),
        "title": str(document.get("title") or ""),
        "version": str(document.get("version") or ""),
        "version_date": str(document.get("version_date") or ""),
        "display": str(document.get("display") or ""),
    }


def _document_target(document_type: str) -> str:
    return f"{DOCUMENT_TARGET_PREFIX}{document_type.strip().casefold()}"


def _master_data_changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_profile = _profile_view(dict(before.get("site_profile") or {}))
    after_profile = _profile_view(dict(after.get("site_profile") or {}))
    profile_changed = before_profile != after_profile
    before_documents = dict(before.get("documents") or {})
    after_documents = dict(after.get("documents") or {})
    ordered_types = ["protocol", "icf", "ethics"]
    document_types = [*ordered_types, *sorted((set(before_documents) | set(after_documents)) - set(ordered_types))]
    document_changes: list[dict[str, Any]] = []
    for document_type in document_types:
        before_view = _document_view(dict(before_documents.get(document_type) or {}))
        after_view = _document_view(dict(after_documents.get(document_type) or {}))
        document_changes.append(
            {
                "document_type": document_type,
                "target": _document_target(document_type),
                "changed": before_view != after_view,
                "from": before_view,
                "to": after_view,
            }
        )
    return {
        "site_profile": {
            "target": SITE_PROFILE_TARGET,
            "changed": profile_changed,
            "from": before_profile,
            "to": after_profile,
        },
        "documents": document_changes,
        "changed_count": int(profile_changed) + sum(item["changed"] for item in document_changes),
    }


def _available_targets(changes: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    if changes["site_profile"]["changed"]:
        targets.append(SITE_PROFILE_TARGET)
    targets.extend(item["target"] for item in changes["documents"] if item["changed"])
    return targets


def _normalise_targets(selected_targets: list[str]) -> list[str]:
    normalized: list[str] = []
    for target in selected_targets:
        value = str(target or "").strip().casefold()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _merge_selected_master_data(
    *,
    before_master_data: dict[str, Any],
    after_master_data: dict[str, Any],
    selected_targets: list[str],
) -> dict[str, Any]:
    selected = set(selected_targets)
    merged = deepcopy(before_master_data)
    if SITE_PROFILE_TARGET in selected:
        merged["site_profile"] = deepcopy(dict(after_master_data.get("site_profile") or {}))
    before_documents = dict(merged.get("documents") or {})
    after_documents = dict(after_master_data.get("documents") or {})
    for target in selected:
        if not target.startswith(DOCUMENT_TARGET_PREFIX):
            continue
        document_type = target.removeprefix(DOCUMENT_TARGET_PREFIX)
        if document_type in after_documents:
            before_documents[document_type] = deepcopy(dict(after_documents[document_type] or {}))
        else:
            before_documents.pop(document_type, None)
    merged["documents"] = before_documents
    return merged


def _site_team_change(visit: dict[str, Any], before_master_data: dict[str, Any], after_master_data: dict[str, Any]) -> dict[str, str]:
    current = str(visit.get("site_team") or "").strip()
    prior_default = str((before_master_data.get("site_profile") or {}).get("site_team") or "").strip()
    next_default = str((after_master_data.get("site_profile") or {}).get("site_team") or "").strip()
    should_refresh = not current or current == prior_default
    return {
        "action": "refresh" if should_refresh else "preserve_manual",
        "from": current,
        "to": next_default if should_refresh else current,
        "message": "中心团队将随当前有效中心资料版本刷新。"
        if should_refresh
        else "保留当前已由 CRA 手工维护的中心团队。",
    }


def _rollback_candidate(connection, visit: dict[str, Any]) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT * FROM master_data_refreshes
        WHERE visit_id = ? AND rolled_back_at = ''
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (visit["id"],),
    ).fetchone()
    if row is None:
        return {
            "can_rollback": False,
            "reason": "尚无可撤销的固定资料采纳记录。",
            "refresh_id": "",
            "selected_targets": [],
            "created_at": "",
        }
    refresh = dict(row)
    if visit["status"] not in EDITABLE_VISIT_STATUSES:
        return {
            "can_rollback": False,
            "reason": "当前报告已提交审核或已批准，不能撤销固定资料采纳。",
            "refresh_id": refresh["id"],
            "selected_targets": json.loads(refresh["selected_targets_json"] or "[]"),
            "created_at": refresh["created_at"],
        }
    snapshot = json.loads(visit.get("snapshot_json") or "{}")
    current_master_data = dict(snapshot.get("master_data") or {})
    after_master_data = json.loads(refresh["after_master_data_json"] or "{}")
    same_snapshot = _canonical_json(current_master_data) == _canonical_json(after_master_data)
    same_team = str(visit.get("site_team") or "") == str(refresh.get("after_site_team") or "")
    if not same_snapshot or not same_team:
        return {
            "can_rollback": False,
            "reason": "当前访视快照已被后续操作更新，不能撤销此次固定资料采纳。",
            "refresh_id": refresh["id"],
            "selected_targets": json.loads(refresh["selected_targets_json"] or "[]"),
            "created_at": refresh["created_at"],
        }
    return {
        "can_rollback": True,
        "reason": "",
        "refresh_id": refresh["id"],
        "selected_targets": json.loads(refresh["selected_targets_json"] or "[]"),
        "created_at": refresh["created_at"],
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _preview_with_connection(connection, visit_id: str) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
    if row is None:
        raise ValueError("未找到当前访视")
    visit = dict(row)
    snapshot = json.loads(visit.get("snapshot_json") or "{}")
    errors: list[str] = []
    if visit["status"] not in EDITABLE_VISIT_STATUSES:
        errors.append("当前报告已提交审核或已批准，不能刷新固定资料快照。")
    before_master_data = dict(snapshot.get("master_data") or {})
    after_master_data = resolve_frozen_master_data(
        project_id=visit["project_id"],
        site_id=visit["site_id"],
        visit_date=str(visit["visit_date"] or "").strip(),
        connection=connection,
    )
    changes = _master_data_changes(before_master_data, after_master_data)
    available_targets = _available_targets(changes)
    site_team = _site_team_change(visit, before_master_data, after_master_data)
    has_changes = bool(available_targets)
    if not errors and not has_changes:
        errors.append("当前冻结资料已经匹配该活动结束日期的有效版本。")
    return {
        "can_apply": not errors,
        "has_changes": has_changes,
        "reason": "；".join(errors),
        "visit": {
            "id": visit["id"],
            "code": visit["code"],
            "status": visit["status"],
            "visit_date": visit["visit_date"],
        },
        "master_data_changes": changes,
        "available_targets": available_targets,
        "site_team": site_team,
        "summary": {
            "changed_master_items": changes["changed_count"],
            "site_team_action": site_team["action"],
        },
        "rollback": _rollback_candidate(connection, visit),
        "_before_master_data": before_master_data,
        "_after_master_data": after_master_data,
    }


def preview_master_data_refresh(*, visit_id: str) -> dict[str, Any]:
    with get_connection() as connection:
        preview = _preview_with_connection(connection, visit_id)
    preview.pop("_before_master_data", None)
    preview.pop("_after_master_data", None)
    return preview


def apply_master_data_refresh(*, visit_id: str, actor_name: str, selected_targets: list[str], reason: str) -> dict[str, Any]:
    adoption_reason = reason.strip()
    if not adoption_reason:
        raise ValueError("请填写采纳固定资料变更的原因。")
    timestamp = _now()
    with transaction() as connection:
        row = connection.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if row is None:
            raise ValueError("未找到当前访视")
        visit = dict(row)
        preview = _preview_with_connection(connection, visit_id)
        if not preview["can_apply"]:
            raise ValueError(preview["reason"] or "当前访视不能刷新固定资料快照。")
        selected = _normalise_targets(selected_targets)
        available = set(preview["available_targets"])
        unsupported = [target for target in selected if target not in available]
        if unsupported:
            raise ValueError("所选固定资料项已变化，请重新检查差异后再采纳。")
        if not selected:
            raise ValueError("请至少选择一项发生变化的固定资料后再采纳。")
        before_master_data = deepcopy(preview["_before_master_data"])
        after_master_data = _merge_selected_master_data(
            before_master_data=before_master_data,
            after_master_data=preview["_after_master_data"],
            selected_targets=selected,
        )
        before_site_team = str(visit.get("site_team") or "")
        after_site_team = (
            str(preview["site_team"]["to"])
            if SITE_PROFILE_TARGET in selected
            else before_site_team
        )
        snapshot = json.loads(visit.get("snapshot_json") or "{}")
        snapshot["master_data"] = after_master_data
        snapshot["master_data_refreshed_at"] = timestamp
        snapshot["master_data_refresh_count"] = int(snapshot.get("master_data_refresh_count") or 0) + 1
        refresh_id = uuid4().hex
        actor = actor_name.strip() or "演示 CRA"
        connection.execute(
            """
            UPDATE visits
            SET site_team = ?, snapshot_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (after_site_team, json.dumps(snapshot, ensure_ascii=False), timestamp, visit_id),
        )
        connection.execute(
            """
            INSERT INTO master_data_refreshes (
                id, visit_id, selected_targets_json, before_master_data_json, after_master_data_json,
                before_site_team, after_site_team, actor_name, adoption_reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                refresh_id,
                visit_id,
                json.dumps(selected, ensure_ascii=False),
                json.dumps(before_master_data, ensure_ascii=False),
                json.dumps(after_master_data, ensure_ascii=False),
                before_site_team,
                after_site_team,
                actor,
                adoption_reason,
                timestamp,
            ),
        )
        public_preview = {key: value for key, value in preview.items() if not key.startswith("_")}
        public_preview["selected_targets"] = selected
        public_preview["adoption_reason"] = adoption_reason
        connection.execute(
            """
            INSERT INTO audit_events (id, project_id, visit_id, entity_type, entity_id, action, actor_name, detail_json, created_at)
            VALUES (?, ?, ?, 'master_data_refresh', ?, 'adopted', ?, ?, ?)
            """,
            (
                uuid4().hex,
                visit["project_id"],
                visit_id,
                refresh_id,
                actor,
                json.dumps(public_preview, ensure_ascii=False),
                timestamp,
            ),
        )
    return {"refresh_id": refresh_id, "preview": public_preview}


def rollback_master_data_refresh(*, visit_id: str, actor_name: str, reason: str) -> dict[str, Any]:
    rollback_reason = reason.strip()
    if not rollback_reason:
        raise ValueError("请填写撤销固定资料采纳的原因。")
    timestamp = _now()
    with transaction() as connection:
        row = connection.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if row is None:
            raise ValueError("未找到当前访视")
        visit = dict(row)
        if visit["status"] not in EDITABLE_VISIT_STATUSES:
            raise ValueError("当前报告已提交审核或已批准，不能撤销固定资料采纳。")
        candidate = _rollback_candidate(connection, visit)
        if not candidate["can_rollback"]:
            raise ValueError(candidate["reason"] or "当前没有可撤销的固定资料采纳记录。")
        refresh = connection.execute(
            "SELECT * FROM master_data_refreshes WHERE id = ? AND visit_id = ?",
            (candidate["refresh_id"], visit_id),
        ).fetchone()
        if refresh is None:
            raise ValueError("未找到可撤销的固定资料采纳记录。")
        refresh_data = dict(refresh)
        snapshot = json.loads(visit.get("snapshot_json") or "{}")
        before_master_data = json.loads(refresh_data["before_master_data_json"] or "{}")
        snapshot["master_data"] = before_master_data
        snapshot["master_data_rolled_back_at"] = timestamp
        snapshot["master_data_rollback_count"] = int(snapshot.get("master_data_rollback_count") or 0) + 1
        actor = actor_name.strip() or "演示 CRA"
        connection.execute(
            """
            UPDATE visits
            SET site_team = ?, snapshot_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (refresh_data["before_site_team"], json.dumps(snapshot, ensure_ascii=False), timestamp, visit_id),
        )
        connection.execute(
            """
            UPDATE master_data_refreshes
            SET rolled_back_at = ?, rolled_back_by = ?, rollback_reason = ?
            WHERE id = ?
            """,
            (timestamp, actor, rollback_reason, refresh_data["id"]),
        )
        connection.execute(
            """
            INSERT INTO audit_events (id, project_id, visit_id, entity_type, entity_id, action, actor_name, detail_json, created_at)
            VALUES (?, ?, ?, 'master_data_refresh', ?, 'rolled_back', ?, ?, ?)
            """,
            (
                uuid4().hex,
                visit["project_id"],
                visit_id,
                refresh_data["id"],
                actor,
                json.dumps(
                    {
                        "refresh_id": refresh_data["id"],
                        "selected_targets": json.loads(refresh_data["selected_targets_json"] or "[]"),
                        "reason": rollback_reason,
                        "adopted_at": refresh_data["created_at"],
                        "rolled_back_at": timestamp,
                    },
                    ensure_ascii=False,
                ),
                timestamp,
            ),
        )
    return {"refresh_id": refresh_data["id"], "rollback_reason": rollback_reason}
