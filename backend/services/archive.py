from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from ..repositories.catalog import get_rule_pack
from ..repositories.visits import (
    create_audit_event,
    get_revision,
    get_visit,
    list_action_items,
    list_attachments,
    list_audit_events,
    list_ai_executions,
    list_confirmed_fields,
    list_revisions,
    list_suggestions,
    list_work_records,
)
from .language import effective_language_by_field, list_language_suggestions
from .clarifications import list_clarification_items


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)


def _visit_or_raise(visit_id: str) -> dict[str, Any]:
    visit = get_visit(visit_id)
    if visit is None:
        raise ValueError("未找到当前访视")
    return visit


def _frozen_rule_pack(visit: dict[str, Any]) -> dict[str, Any]:
    snapshot_rule = dict((visit.get("snapshot") or {}).get("rule_pack") or {})
    live_rule = get_rule_pack(visit["rule_pack_id"]) or {}
    if not snapshot_rule:
        return live_rule
    if not snapshot_rule.get("content"):
        snapshot_rule["content"] = live_rule.get("content", {})
    return {**live_rule, **snapshot_rule}


def build_evidence_chain(visit_id: str) -> dict[str, Any]:
    visit = _visit_or_raise(visit_id)
    records = {record["id"]: record for record in list_work_records(visit_id)}
    suggestions = {suggestion["id"]: suggestion for suggestion in list_suggestions(visit_id)}
    executions = {execution["id"]: execution for execution in list_ai_executions(visit_id)}
    language_by_field = effective_language_by_field(visit_id)
    language_history = list_language_suggestions(visit_id)
    fields: list[dict[str, Any]] = []
    for confirmed in list_confirmed_fields(visit_id, include_center_explanations=True):
        report_included = (
            confirmed.get("assertion_type") != "center_explanation"
            and confirmed.get("source_type") != "center_explanation"
        )
        language = language_by_field.get(confirmed["id"])
        source_record = records.get(confirmed.get("source_record_id", ""), {})
        source_suggestion = suggestions.get(confirmed.get("suggestion_id", ""), {})
        execution = executions.get(source_suggestion.get("ai_execution_id", ""), {})
        fields.append(
            {
                "confirmed_field_id": confirmed["id"],
                "target_table": confirmed["target_table"],
                "field_key": confirmed["field_key"],
                "category": confirmed["category"],
                "subject_code": confirmed.get("subject_code", ""),
                "confirmed_text": confirmed["value"],
                "report_included": report_included,
                "report_text": (language.get("final_text") if language else confirmed["value"])
                if report_included
                else "",
                "decision": confirmed.get("decision", "accepted"),
                "decision_reason": confirmed.get("decision_reason", ""),
                "assertion_type": confirmed.get("assertion_type", "reported_observation"),
                "source_type": confirmed.get("source_type", "work_record"),
                "subject_validation_status": confirmed.get("subject_validation_status", "not_provided"),
                "subject_display_code": confirmed.get("subject_display_code", ""),
                "confirmed_by": confirmed["confirmed_by"],
                "confirmed_at": confirmed["confirmed_at"],
                "source_record": {
                    "id": source_record.get("id", ""),
                    "text": source_record.get("text", ""),
                    "record_kind": source_record.get("record_kind", "monitoring_note"),
                    "created_by": source_record.get("created_by", ""),
                    "created_at": source_record.get("created_at", ""),
                    "text_hash": source_record.get("text_hash", ""),
                    "client_created_at": source_record.get("client_created_at", ""),
                    "client_timezone": source_record.get("client_timezone", ""),
                    "server_received_at": source_record.get("server_received_at", ""),
                },
                "source_suggestion": {
                    "id": source_suggestion.get("id", ""),
                    "title": source_suggestion.get("title", ""),
                    "proposed_text": source_suggestion.get("proposed_text", ""),
                    "status": source_suggestion.get("status", ""),
                    "value_type": source_suggestion.get("value_type", ""),
                    "assertion_type": source_suggestion.get("assertion_type", ""),
                    "source_type": source_suggestion.get("source_type", ""),
                    "evidence_text": source_suggestion.get("evidence_text", ""),
                    "evidence_start": source_suggestion.get("evidence_start", 0),
                    "evidence_end": source_suggestion.get("evidence_end", 0),
                    "entity_type": source_suggestion.get("entity_type", ""),
                    "entity_id": source_suggestion.get("entity_id", ""),
                    "pending_reason": source_suggestion.get("pending_reason", ""),
                    "ai_execution_id": source_suggestion.get("ai_execution_id", ""),
                    "subject_validation_status": source_suggestion.get("subject_validation_status", "not_provided"),
                    "subject_display_code": source_suggestion.get("subject_display_code", ""),
                },
                "ai_execution": {
                    "id": execution.get("id", ""),
                    "provider": execution.get("provider", ""),
                    "model_version": execution.get("model_version", ""),
                    "prompt_version": execution.get("prompt_version", ""),
                    "schema_version": execution.get("schema_version", ""),
                    "rule_pack_version": execution.get("rule_pack_version", ""),
                    "executed_at": execution.get("executed_at", ""),
                    "input_record_hash": execution.get("input_record_hash", ""),
                    "output_hash": execution.get("output_hash", ""),
                    "validation_status": execution.get("validation_status", ""),
                    "retry_count": execution.get("retry_count", 0),
                    "error_code": execution.get("error_code", ""),
                },
                "language": language
                or {
                    "id": "",
                    "status": "not_applied",
                    "original_text": confirmed["value"],
                    "proposed_text": "",
                    "final_text": confirmed["value"],
                    "change_summary": "未采用语言优化建议",
                },
            }
        )
    return {
        "visit": {
            "id": visit["id"],
            "code": visit["code"],
            "template_name": visit.get("template_name", ""),
            "template_version": visit.get("template_version", ""),
        },
        "rule_pack": _frozen_rule_pack(visit),
        "fields": fields,
        "language_history": language_history,
        "ai_executions": list(executions.values()),
        "clarifications": list_clarification_items(visit_id),
    }


def _audit_rows(visit_id: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for event in list_audit_events(visit_id):
        rows.append(
            {
                "row_type": "audit_event",
                "created_at": event.get("created_at", ""),
                "entity_type": event.get("entity_type", ""),
                "entity_id": event.get("entity_id", ""),
                "action": event.get("action", ""),
                "actor_name": event.get("actor_name", ""),
                "status": "",
                "summary": "",
                "detail": json.dumps(event.get("detail", {}), ensure_ascii=False),
            }
        )
    for revision in list_revisions(visit_id):
        rows.append(
            {
                "row_type": "report_revision",
                "created_at": revision.get("created_at", ""),
                "entity_type": "report_revision",
                "entity_id": revision.get("id", ""),
                "action": "snapshot",
                "actor_name": revision.get("submitted_by", ""),
                "status": revision.get("status", ""),
                "summary": revision.get("version_number", ""),
                "detail": json.dumps({"file_name": revision.get("file_name", ""), "generated_at": revision.get("generated_at", "")}, ensure_ascii=False),
            }
        )
    for action_item in list_action_items(visit_id):
        rows.append(
            {
                "row_type": "action_item",
                "created_at": action_item.get("created_at", ""),
                "entity_type": "action_item",
                "entity_id": action_item.get("id", ""),
                "action": "snapshot",
                "actor_name": action_item.get("owner", ""),
                "status": action_item.get("status", ""),
                "summary": action_item.get("title", ""),
                "detail": json.dumps({"description": action_item.get("description", ""), "closure_note": action_item.get("closure_note", "")}, ensure_ascii=False),
            }
        )
    for attachment in list_attachments(visit_id):
        rows.append(
            {
                "row_type": "attachment",
                "created_at": attachment.get("created_at", ""),
                "entity_type": "attachment",
                "entity_id": attachment.get("id", ""),
                "action": "retained",
                "actor_name": attachment.get("created_by", ""),
                "status": "retained",
                "summary": attachment.get("file_name", ""),
                "detail": json.dumps({"description": attachment.get("description", ""), "action_item_id": attachment.get("action_item_id", "")}, ensure_ascii=False),
            }
        )
    return sorted(rows, key=lambda item: item.get("created_at", ""), reverse=True)


def build_audit_csv(visit_id: str) -> bytes:
    _visit_or_raise(visit_id)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=["row_type", "created_at", "entity_type", "entity_id", "action", "actor_name", "status", "summary", "detail"],
    )
    writer.writeheader()
    writer.writerows(_audit_rows(visit_id))
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def export_audit_csv(*, visit_id: str, actor_name: str = "演示系统") -> tuple[bytes, str]:
    visit = _visit_or_raise(visit_id)
    create_audit_event(
        project_id=visit["project_id"],
        visit_id=visit_id,
        entity_type="audit_export",
        entity_id=visit_id,
        action="csv_exported",
        actor_name=actor_name,
        detail={"format": "csv"},
    )
    filename = f"{_safe_name(visit['code'])}_audit_trail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return build_audit_csv(visit_id), filename


def build_handover_package(*, revision_id: str, actor_name: str = "演示系统") -> tuple[bytes, str]:
    revision = get_revision(revision_id)
    if revision is None:
        raise ValueError("未找到报告修订版本")
    visit = _visit_or_raise(revision["visit_id"])
    report_file = Path(revision["file_path"])
    if not report_file.exists():
        raise ValueError("未找到已生成的 Word 文件")
    rule_pack = _frozen_rule_pack(visit)
    create_audit_event(
        project_id=visit["project_id"],
        visit_id=visit["id"],
        entity_type="handover_package",
        entity_id=revision_id,
        action="exported",
        actor_name=actor_name,
        detail={"revision": revision["version_number"], "file_name": revision["file_name"]},
    )
    manifest = {
        "package_type": "monitoring-report-system-external-signature-handover",
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "visit": {
            "id": visit["id"],
            "code": visit["code"],
            "visit_type": visit["visit_type"],
            "visit_date": visit["visit_date"],
        },
        "template": {"name": visit.get("template_name", ""), "version": visit.get("template_version", "")},
        "rule_pack": {
            "id": rule_pack.get("id", ""),
            "name": rule_pack.get("name", ""),
            "version": rule_pack.get("version", ""),
            "effective_from": rule_pack.get("effective_from", ""),
            "effective_to": rule_pack.get("effective_to", ""),
        },
        "revision": {
            "id": revision["id"],
            "version_number": revision["version_number"],
            "status": revision["status"],
            "file_name": revision["file_name"],
        },
    }
    readme = (
        "监查 Mentor 系统外签署交接包\n\n"
        "本交接包用于将已由 CRA 确认并在系统中生成的监查报告，移交至客户既有 SOP、电子签名和 eTMF 归档流程。\n"
        "系统内的生成、提交或批准状态不构成电子签名，也不替代申办方/CRO 的正式归档要求。\n"
        "请由授权人员依照客户 SOP 完成签署、复核、归档及保留期限管理。\n\n"
        "内容清单：\n"
        "- report/：选定修订版 Word 监查报告\n"
        "- audit/：当前访视审计轨迹 CSV\n"
        "- evidence/：字段、来源工作记录、AI 执行和 CRA 决策的证据链 JSON\n"
        "- manifest.json：访视、模板、规则包和修订版元数据\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(report_file, arcname=f"report/{revision['file_name']}")
        archive.writestr("audit/audit_trail.csv", build_audit_csv(visit["id"]))
        archive.writestr("evidence/evidence_chain.json", json.dumps(build_evidence_chain(visit["id"]), ensure_ascii=False, indent=2))
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("README.txt", readme)
    filename = f"{_safe_name(visit['code'])}_{revision['version_number']}_signature_handover.zip"
    return buffer.getvalue(), filename
