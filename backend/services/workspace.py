from __future__ import annotations

from typing import Any

from ..repositories.catalog import (
    get_project,
    get_rule_pack,
    get_setting,
    get_site,
    get_template,
    list_project_members,
    list_subject_codes,
)
from ..repositories.visits import (
    get_visit,
    list_action_items,
    list_audit_events,
    list_attachments,
    list_confirmed_fields,
    list_findings,
    list_historical_open_action_items,
    list_revisions,
    list_suggestions,
    list_template_switches,
    list_visit_date_reassessments,
    list_tasks,
    list_visit_review_comments,
    list_work_records,
)
from .continuity import get_visit_sync_token
from .clarifications import list_clarification_items
from .language import effective_language_by_field, list_language_suggestions
from .readiness import evaluate_report_readiness
from .system_checks import SYSTEM_CHECK_TASK_TYPE, normalize_system_checks


EMPTY_RECRUITMENT = {
    "screened": 0,
    "screen_failed": 0,
    "treated": 0,
    "ae_dropout": 0,
    "other_dropout": 0,
    "completed_treatment": 0,
    "follow_up": 0,
    "follow_up_dropout": 0,
    "completed_follow_up": 0,
}


def _workflow_stage(
    report_status: str,
    readiness: dict[str, Any],
    records: list[dict[str, Any]],
    suggestions: list[dict[str, Any]],
    language_suggestions: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    confirmed_items: list[dict[str, Any]],
) -> str:
    """Return an operational read model without changing the persisted report status."""
    persistent_stage = {
        "submitted": "under_review",
        "returned": "returned",
        "approved": "approved",
        "cancelled": "cancelled",
    }.get(report_status)
    if persistent_stage:
        return persistent_stage

    pending_suggestions = any(item.get("status") == "pending" for item in suggestions)
    pending_language = any(item.get("status") == "pending" for item in language_suggestions)
    has_task_progress = any(
        (task.get("status") or "").strip() not in {"", "未开始", "待补录"}
        for task in tasks
    )
    active_records = [record for record in records if record.get("record_status", "active") != "voided"]
    has_working_context = bool(active_records or suggestions or language_suggestions or confirmed_items or has_task_progress)

    if readiness.get("ready") and not pending_suggestions and not pending_language:
        return "ready_to_submit"
    if has_working_context:
        return "pending_cra_confirmation"
    return "draft"


def build_workspace(visit_id: str) -> dict[str, Any] | None:
    visit = get_visit(visit_id)
    if visit is None:
        return None
    project = get_project(visit["project_id"]) or {}
    site = get_site(visit["site_id"]) or {}
    template = get_template(visit["template_id"]) or {}
    snapshot = visit.get("snapshot", {})
    template_field_slots = list(snapshot.get("template_field_slots") or [])
    live_rule_pack = get_rule_pack(visit["rule_pack_id"]) or {}
    frozen_rule_pack = dict(snapshot.get("rule_pack") or {})
    if frozen_rule_pack and not frozen_rule_pack.get("content"):
        frozen_rule_pack["content"] = live_rule_pack.get("content", {})
    rule_pack = {**live_rule_pack, **frozen_rule_pack} if frozen_rule_pack else live_rule_pack
    recruitment = snapshot.get("recruitment", EMPTY_RECRUITMENT)
    master_data = dict(snapshot.get("master_data") or {})
    visit_context = dict(snapshot.get("visit_context") or {})
    trial_control = dict(snapshot.get("trial_control") or {})
    frozen_project_eligibility = dict(snapshot.get("project_eligibility") or {})
    frozen_profile = dict(master_data.get("site_profile") or {})
    frozen_documents = dict(master_data.get("documents") or {})

    def document_display(document_type: str, fallback: str) -> str:
        document = dict(frozen_documents.get(document_type) or {})
        return str(document.get("display") or fallback)

    revisions = list_revisions(visit_id)
    latest_revision = revisions[0] if revisions else None
    all_confirmed_items = list_confirmed_fields(visit_id, include_center_explanations=True)
    confirmed_items = [
        item
        for item in all_confirmed_items
        if item.get("assertion_type") != "center_explanation" and item.get("source_type") != "center_explanation"
    ]
    center_explanations = [
        item
        for item in all_confirmed_items
        if item.get("assertion_type") == "center_explanation" or item.get("source_type") == "center_explanation"
    ]
    language_suggestions = list_language_suggestions(visit_id)
    records = list_work_records(visit_id)
    records_by_id = {record["id"]: record for record in records}
    for record in records:
        record["modification_history"] = []
    for record in records:
        original_id = record.get("corrected_record_id")
        original = records_by_id.get(original_id) if original_id else None
        if original is not None:
            original["modification_history"].append(
                {
                    "record_id": record["id"],
                    "kind": "correction",
                    "reason": record.get("correction_reason", ""),
                    "actor_name": record.get("created_by", ""),
                    "created_at": record.get("created_at", ""),
                    "record_status": record.get("record_status", "active"),
                }
            )
    suggestions = list_suggestions(visit_id)
    accepted_language = effective_language_by_field(visit_id)
    for item in confirmed_items:
        language = accepted_language.get(item["id"])
        item["report_text"] = language.get("final_text") if language else item.get("value", "")
        item["language_suggestion_id"] = language.get("id") if language else ""
        item["language_status"] = language.get("status") if language else ""
    findings = list_findings(visit_id)
    action_items = list_action_items(visit_id)
    all_tasks = list_tasks(visit_id)
    clarification_items = list_clarification_items(visit_id)
    # The visit owns the current workflow state. The newest revision may already
    # be a newly-created working draft after PM/LM return, while the visit must
    # still visibly remain in the returned stage until CRA re-submits it.
    report_status = visit.get("status") or (latest_revision.get("status") if latest_revision else "draft")
    readiness = evaluate_report_readiness(visit_id)
    workflow_stage = _workflow_stage(
        report_status,
        readiness,
        records,
        suggestions,
        language_suggestions,
        all_tasks,
        confirmed_items,
    )
    table_tasks = [task for task in all_tasks if task.get("task_type", "template_table") != SYSTEM_CHECK_TASK_TYPE]
    system_check_tasks = [task for task in all_tasks if task.get("task_type") == SYSTEM_CHECK_TASK_TYPE]
    try:
        frozen_system_checks = normalize_system_checks(rule_pack.get("content") or {})
    except ValueError:
        frozen_system_checks = []
    descriptions_by_key = {item["field_key"]: item["description"] for item in frozen_system_checks}
    descriptions_by_index = {item["table_index"]: item["description"] for item in frozen_system_checks}
    for task in system_check_tasks:
        task["description"] = descriptions_by_key.get(task.get("field_key", ""), descriptions_by_index.get(task["table_index"], ""))

    project_view = {
        "id": project.get("id", ""),
        "study_name": project.get("name", ""),
        "study_id": project.get("code", ""),
        "sponsor": project.get("sponsor", ""),
        "approval_number": project.get("metadata", {}).get("approval_number", ""),
        "sop_version": project.get("metadata", {}).get("sop_version", ""),
        "blinding_mode": trial_control.get("blinding_mode") or project.get("metadata", {}).get("blinding_mode", "open_label"),
        "subject_code_display_mode": project.get("metadata", {}).get("subject_code_display_mode", "masked"),
        "trial_control": trial_control,
        "status": project.get("status", "active"),
    }
    if frozen_project_eligibility:
        project_view["project_eligibility"] = frozen_project_eligibility
    site_view = {
        "id": site.get("id", ""),
        "site_code": site.get("code", ""),
        "site_name": site.get("name", ""),
        "pi_name": frozen_profile.get("pi_name") or site.get("pi_name", ""),
        "site_address": frozen_profile.get("site_address", ""),
        "key_roles": frozen_profile.get("key_roles", {}),
        "site_profile_version": frozen_profile.get("version_label", ""),
        "ethics_date": document_display("ethics", site.get("ethics_date", "")),
        "protocol_version": document_display("protocol", site.get("protocol_version", "")),
        "icf_version": document_display("icf", site.get("icf_version", "")),
    }
    visit_view = {
        "id": visit["id"],
        "project_id": visit["project_id"],
        "site_id": visit["site_id"],
        "code": visit["code"],
        "visit_type": visit["visit_type"],
        "visit_date": visit["visit_date"],
        "activity_start_date": visit.get("activity_start_date") or visit_context.get("activity_start_date") or visit["visit_date"],
        "activity_end_date": visit["visit_date"],
        "visit_method": visit.get("visit_method") or visit_context.get("visit_method") or "现场",
        "visit_location": visit.get("visit_location") or visit_context.get("visit_location") or "",
        "contact_persons": visit.get("contact_persons") or visit_context.get("contact_persons") or "",
        "report_date": visit["report_date"],
        "site_team": visit["site_team"],
        "monitoring_team": visit["monitoring_team"],
        "next_visit": visit["next_visit"],
        "cra_name": visit["cra_name"],
        "status": visit["status"],
        "updated_at": visit["updated_at"],
        "sync_token": get_visit_sync_token(visit_id),
        "snapshot": snapshot,
    }
    legacy_project = {
        **project_view,
        **site_view,
    }
    return {
        "project": legacy_project,
        "site": site_view,
        "visit": visit_view,
        "template": template,
        "template_field_slots": template_field_slots,
        "template_switches": list_template_switches(visit_id),
        "visit_date_reassessments": list_visit_date_reassessments(visit_id),
        "rule_pack": rule_pack,
        "master_data": master_data,
        "recruitment": {**EMPTY_RECRUITMENT, **recruitment},
        "table_tasks": table_tasks,
        "system_check_tasks": system_check_tasks,
        "subject_codes": list_subject_codes(visit["site_id"]),
        "records": records,
        "suggestions": suggestions,
        "confirmed_items": confirmed_items,
        "center_explanations": center_explanations,
        "clarification_items": clarification_items,
        "language_suggestions": language_suggestions,
        "findings": findings,
        "action_items": action_items,
        "historical_open_actions": list_historical_open_action_items(visit_id),
        "attachments": list_attachments(visit_id),
        "revisions": revisions,
        "review_comments": list_visit_review_comments(visit_id),
        "audit_events": list_audit_events(visit_id),
        "project_members": list_project_members(visit["project_id"], include_inactive=True),
        "current_role": get_setting("current_role", "CRA"),
        "report_status": report_status,
        "workflow_stage": workflow_stage,
        "workflow_stage_summary": {
            "readiness_block_count": readiness["summary"]["block_count"],
            "pending_suggestion_count": sum(item.get("status") == "pending" for item in suggestions),
            "pending_language_count": sum(item.get("status") == "pending" for item in language_suggestions),
            "open_clarification_count": sum(
                item.get("status") in {"open", "manual_required"} for item in clarification_items
            ),
        },
        "last_generated_at": latest_revision.get("generated_at") if latest_revision else None,
        "last_generated_file": latest_revision.get("file_name") if latest_revision else None,
        "last_submitted_at": latest_revision.get("submitted_at") if latest_revision else None,
    }


def default_workspace() -> dict[str, Any] | None:
    return build_workspace(get_setting("current_visit_id"))
