from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from ..database import transaction
from ..repositories.visits import compute_confirmed_field_hash, get_revision, get_visit, list_action_items, list_work_records
from ..simulated_ai import create_suggestions
from .readiness import evaluate_report_readiness, readiness_error
from .template_mapping_suggestions import MAPPING_PROFILES


_SUBJECT_CODE_CANDIDATE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+|[A-Za-z]{1,4}[-_]?\d{3,6}|\d{3}[-_]\d{3})(?![A-Za-z0-9])"
)
_CRITICAL_EDIT_CATEGORIES = {"icf", "icf_list", "ae", "sae", "deviation", "regulatory"}
_ROUTING_INTENTS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "summary": ("overall_assessment", "site_visit_overview"),
    "icf": ("informed_consent",),
    "icf_list": ("informed_consent",),
    "ae": ("safety",),
    "sae": ("safety",),
    "deviation": ("protocol_compliance", "investigational_product"),
    "crf": ("data_quality",),
    "regulatory": ("ethics_compliance", "essential_documents"),
    "recruitment": ("subject_progress",),
    "investigational_product": ("investigational_product",),
    "document_archive": ("essential_documents", "laboratory_samples", "site_team"),
    "system_device": ("systems_equipment",),
    "action": ("findings_actions", "next_visit_plan"),
}
_ROUTING_TERMS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "summary": ("总体评价", "总体结论", "监查摘要", "监查总结", "监查结论", "小结"),
    "icf": ("知情", "同意", "icf"),
    "icf_list": ("知情", "同意", "icf", "签署"),
    "ae": ("不良事件", "ae", "安全"),
    "sae": ("严重不良", "sae", "安全"),
    "deviation": ("偏离", "违背", "依从", "方案执行", "protocol", "药物"),
    "crf": ("crf", "edc", "ecrf", "数据", "病例报告", "原始记录"),
    "regulatory": ("伦理", "批件", "法规", "gcp", "研究者手册"),
    "recruitment": ("筛选", "入组", "招募", "受试者", "脱落"),
    "investigational_product": ("药房", "研究药物", "试验用药", "药物", "ip"),
    "document_archive": ("文件", "归档", "存档", "实验室", "样本", "资质", "授权", "培训"),
    "system_device": ("iwrs", "ixrs", "epro", "系统", "设备", "仪器", "校准", "温度"),
    "action": ("行动项", "整改", "跟进", "后续", "计划"),
}
_PROFILE_TERMS_BY_KEY = {
    str(profile["field_key"]): tuple(str(term) for term in profile["terms"])
    for profile in MAPPING_PROFILES
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _audit(connection, *, project_id: str, visit_id: str, entity_type: str, entity_id: str, action: str, actor_name: str, detail: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO audit_events (id, project_id, visit_id, entity_type, entity_id, action, actor_name, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (uuid4().hex, project_id, visit_id, entity_type, entity_id, action, actor_name, json.dumps(detail, ensure_ascii=False), _now()),
    )


def _visit_context(connection, visit_id: str):
    row = connection.execute("SELECT id, project_id, site_id, visit_date, status, rule_pack_id FROM visits WHERE id = ?", (visit_id,)).fetchone()
    if row is None:
        raise ValueError("未找到当前访视")
    return row


def _require_editable_visit(visit) -> None:
    if visit["status"] not in {"draft", "returned"}:
        raise ValueError("当前报告已提交审核或已批准，不能新增或修改 CRA 工作底稿")


def cancel_draft_visit(*, visit_id: str, reason: str, actor_name: str) -> dict[str, Any]:
    cancellation_reason = reason.strip()
    cancellation_actor = actor_name.strip()
    if not cancellation_reason:
        raise ValueError("请填写取消草稿访视的原因")
    if not cancellation_actor:
        raise ValueError("请填写取消操作人")
    timestamp = _now()
    with transaction() as connection:
        visit = _visit_context(connection, visit_id)
        if visit["status"] != "draft":
            raise ValueError("只有尚未提交的草稿访视可以取消")
        formal_revision_count = int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM report_revisions WHERE visit_id = ? AND revision_type = 'formal'",
                (visit_id,),
            ).fetchone()["count"]
        )
        if formal_revision_count:
            raise ValueError("该访视已有正式报告修订，不能取消；请按既有修订或作废流程处理")
        connection.execute(
            "UPDATE visits SET status = 'cancelled', updated_at = ? WHERE id = ?",
            (timestamp, visit_id),
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="visit",
            entity_id=visit_id,
            action="draft_cancelled",
            actor_name=cancellation_actor,
            detail={
                "previous_status": visit["status"],
                "reason": cancellation_reason,
                "formal_revision_count": formal_revision_count,
                "cancelled_at": timestamp,
            },
        )
    return get_visit(visit_id) or {}


def _duplicate_comparison_text(value: str) -> str:
    return re.sub(r"[\s\u3000，,。；;：:、.!！？?（）()\[\]{}“”\"'‘’]+", "", value).casefold()


def find_duplicate_work_records(*, visit_id: str, text: str) -> list[dict[str, Any]]:
    """Return explainable exact-match candidates without merging or writing records."""
    normalized = _duplicate_comparison_text(text)
    if not normalized:
        return []
    candidates: list[dict[str, Any]] = []
    for record in list_work_records(visit_id):
        if record.get("record_status", "active") == "voided":
            continue
        if _duplicate_comparison_text(str(record.get("text") or "")) != normalized:
            continue
        candidates.append(
            {
                "id": record["id"],
                "text": record["text"],
                "record_kind": record.get("record_kind", "monitoring_note"),
                "created_by": record.get("created_by", ""),
                "linked_task_id": record.get("linked_task_id", ""),
                "recorded_at": record.get("recorded_at", ""),
                "tags": list(record.get("tags") or []),
                "record_status": record.get("record_status", "active"),
                "created_at": record.get("created_at", ""),
            }
        )
        if len(candidates) >= 8:
            break
    return candidates


def _work_record_payload(record: Any) -> dict[str, Any]:
    data = dict(record)
    try:
        tags = json.loads(data.get("tags_json") or "[]")
    except json.JSONDecodeError:
        tags = []
    return {
        "id": data["id"],
        "text": data["text"],
        "record_kind": data.get("record_kind", "monitoring_note"),
        "created_by": data.get("created_by", ""),
        "linked_task_id": data.get("linked_task_id", ""),
        "recorded_at": data.get("recorded_at", ""),
        "client_created_at": data.get("client_created_at", ""),
        "client_timezone": data.get("client_timezone", ""),
        "server_received_at": data.get("server_received_at", ""),
        "text_hash": data.get("text_hash", ""),
        "processing_status": data.get("processing_status", "completed"),
        "processing_error": data.get("processing_error", ""),
        "processed_at": data.get("processed_at", ""),
        "tags": tags,
        "client_idempotency_key": data.get("client_idempotency_key", ""),
        "corrected_record_id": data.get("corrected_record_id"),
        "correction_reason": data.get("correction_reason", ""),
        "record_status": data.get("record_status", "active"),
        "void_reason": data.get("void_reason", ""),
        "voided_at": data.get("voided_at", ""),
        "voided_by": data.get("voided_by", ""),
        "created_at": data.get("created_at", ""),
    }


def _normalize_subject_code(value: str) -> str:
    return value.strip().upper().replace("_", "-")


def _mask_subject_code(value: str) -> str:
    subject_code = value.strip()
    if not subject_code or subject_code == "未提供受试者编号":
        return ""
    if "-" in subject_code or "_" in subject_code:
        prefix, _, _ = subject_code.replace("_", "-").rpartition("-")
        return f"{prefix}-***" if prefix else "***"
    if len(subject_code) <= 2:
        return "**"
    return f"{subject_code[:2]}{'*' * max(2, len(subject_code) - 2)}"


def _pseudonymize_subject_context(source: str) -> tuple[str, dict[str, str]]:
    aliases_by_normalized_code: dict[str, str] = {}
    source_by_alias: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        raw_code = match.group(0)
        normalized_code = _normalize_subject_code(raw_code)
        alias = aliases_by_normalized_code.get(normalized_code)
        if alias is None:
            alias = f"SUBJ{len(aliases_by_normalized_code) + 1:03d}"
            aliases_by_normalized_code[normalized_code] = alias
            source_by_alias[alias] = raw_code
        return alias

    return _SUBJECT_CODE_CANDIDATE_PATTERN.sub(replace, source), source_by_alias


def _restore_pseudonymized_value(value: str, source_by_alias: dict[str, str]) -> str:
    restored = value
    for alias, raw_code in source_by_alias.items():
        restored = restored.replace(alias, raw_code)
    return restored


def _subject_metadata(
    *, extracted_subject: str, source_by_alias: dict[str, str], known_subject_codes: dict[str, str], display_mode: str
) -> dict[str, str]:
    subject_code = _restore_pseudonymized_value(extracted_subject, source_by_alias).strip()
    if not subject_code or subject_code == "未提供受试者编号":
        return {"subject_code": "未提供受试者编号", "subject_validation_status": "not_provided", "subject_display_code": ""}
    normalized_code = _normalize_subject_code(subject_code)
    validation_status = "valid" if normalized_code in known_subject_codes else "unverified"
    display_code = subject_code if display_mode == "full" else _mask_subject_code(subject_code)
    return {
        "subject_code": subject_code,
        "subject_validation_status": validation_status,
        "subject_display_code": display_code,
    }


def _routing_text(value: object) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").casefold())


def _route_proposals_to_active_tasks(
    proposals: list[dict[str, Any]],
    active_tasks: list[dict[str, Any]],
    *,
    linked_task_id: str = "",
) -> None:
    """Route local suggestions through the visit's frozen template-task mapping when possible."""
    tasks_by_id = {str(task.get("id") or ""): task for task in active_tasks}
    tasks_by_table = {int(task.get("table_index") or 0): task for task in active_tasks}
    explicit_task = tasks_by_id.get(linked_task_id.strip())
    for proposal in proposals:
        legacy_table = int(proposal.get("target_table") or 0)
        selected: dict[str, Any] | None = explicit_task
        routing_method = "cra_linked_task" if explicit_task is not None else ""
        category = str(proposal.get("category") or "summary")
        if selected is None:
            intents = _ROUTING_INTENTS_BY_CATEGORY.get(category, ())
            category_terms = _ROUTING_TERMS_BY_CATEGORY.get(category, ())
            scored_tasks: list[tuple[int, dict[str, Any]]] = []
            for task in active_tasks:
                field_key = str(task.get("field_key") or "")
                task_text = _routing_text(f"{field_key} {task.get('title', '')} {task.get('description', '')}")
                score = 0
                for intent_position, intent in enumerate(intents):
                    normalized_intent = _routing_text(intent)
                    if normalized_intent and (task_text.startswith(normalized_intent) or _routing_text(field_key).startswith(normalized_intent)):
                        score = max(score, 180 - intent_position * 10)
                    for term in _PROFILE_TERMS_BY_KEY.get(intent, ()):
                        normalized_term = _routing_text(term)
                        if normalized_term and normalized_term in task_text:
                            score = max(score, 100 - intent_position * 10 + min(len(normalized_term), 20))
                for term in category_terms:
                    normalized_term = _routing_text(term)
                    if normalized_term and normalized_term in task_text:
                        score = max(score, 70 + min(len(normalized_term), 20))
                if category == "system_device" and task.get("task_type") == "system_device_check":
                    score = max(score, 190)
                if score:
                    scored_tasks.append((score, task))
            if scored_tasks:
                selected = sorted(
                    scored_tasks,
                    key=lambda item: (
                        -item[0],
                        0 if int(item[1].get("table_index") or 0) == legacy_table else 1,
                        int(item[1].get("table_index") or 0),
                    ),
                )[0][1]
                routing_method = "template_mapping_terms"
            elif legacy_table in tasks_by_table:
                selected = tasks_by_table[legacy_table]
                routing_method = "legacy_table"
            elif active_tasks:
                selected = active_tasks[0]
                routing_method = "fallback_first_active_task"
                proposal["pending_reason"] = (
                    f"未从当前模板识别到“{proposal.get('title') or '该建议'}”的专属区域，"
                    f"已暂放至“{selected.get('title') or '首个任务'}”；请 CRA 确认或重新归类。"
                )
        if selected is None:
            continue
        proposal["target_task_id"] = str(selected.get("id") or "")
        proposal["target_table"] = int(selected.get("table_index") or legacy_table)
        proposal["field_key"] = str(selected.get("field_key") or f"table_{proposal['target_table']}")
        proposal["routing_method"] = routing_method


def _process_work_record(
    *, visit_id: str, record_id: str, source: str, actor_name: str, record_kind: str = "monitoring_note", linked_task_id: str = ""
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Run the local suggestion step after the raw work-paper record is durable."""
    source_type = "center_explanation" if record_kind == "center_explanation" else "work_record"
    engine_source, source_by_alias = _pseudonymize_subject_context(source)
    try:
        proposals = create_suggestions(engine_source, source_type=source_type)
        for proposal in proposals:
            for key in ("proposed_text", "source", "subject", "evidence_text", "entity_id"):
                if isinstance(proposal.get(key), str):
                    proposal[key] = _restore_pseudonymized_value(proposal[key], source_by_alias)
            proposal["evidence_text"] = source
            proposal["evidence_start"] = 0
            proposal["evidence_end"] = len(source)
    except Exception as exc:
        timestamp = _now()
        error_message = str(exc).strip()[:500] or "本地整理失败"
        with transaction() as connection:
            visit = _visit_context(connection, visit_id)
            record = connection.execute("SELECT text_hash FROM work_records WHERE id = ?", (record_id,)).fetchone()
            rule_pack = connection.execute("SELECT version FROM rule_packs WHERE id = ?", (visit["rule_pack_id"],)).fetchone()
            execution_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO ai_executions (
                    id, visit_id, source_record_id, provider, model_version, prompt_version, schema_version,
                    rule_pack_version, executed_at, input_record_hash, output_hash, validation_status,
                    retry_count, error_code, created_at
                ) VALUES (?, ?, ?, 'local_deterministic', 'simulated_ai.v2', 'keyword_rules.template_task_routing.v2', 'monitoring_suggestion.v1', ?, ?, ?, '', 'failed', 0, 'LOCAL_DETERMINISTIC_ERROR', ?)
                """,
                (
                    execution_id,
                    visit_id,
                    record_id,
                    rule_pack["version"] if rule_pack else "",
                    timestamp,
                    record["text_hash"] if record else "",
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE work_records SET processing_status = 'failed', processing_error = ?, processed_at = ? WHERE id = ?",
                (error_message, timestamp, record_id),
            )
            _audit(
                connection,
                project_id=visit["project_id"],
                visit_id=visit_id,
                entity_type="work_record",
                entity_id=record_id,
                action="processing_failed",
                actor_name=actor_name,
                detail={"error": error_message, "ai_execution_id": execution_id, "error_code": "LOCAL_DETERMINISTIC_ERROR"},
            )
        return [], {"processing_status": "failed", "processing_error": error_message, "processed_at": timestamp}

    timestamp = _now()
    with transaction() as connection:
        visit = _visit_context(connection, visit_id)
        record = connection.execute("SELECT text_hash FROM work_records WHERE id = ?", (record_id,)).fetchone()
        rule_pack = connection.execute("SELECT version FROM rule_packs WHERE id = ?", (visit["rule_pack_id"],)).fetchone()
        subject_rows = connection.execute("SELECT code FROM subject_codes WHERE site_id = ?", (visit["site_id"],)).fetchall()
        known_subject_codes = {_normalize_subject_code(str(row["code"] or "")): str(row["code"] or "") for row in subject_rows}
        project = connection.execute("SELECT metadata_json FROM projects WHERE id = ?", (visit["project_id"],)).fetchone()
        try:
            project_metadata = json.loads(project["metadata_json"] or "{}") if project else {}
        except json.JSONDecodeError:
            project_metadata = {}
        subject_display_mode = "full" if project_metadata.get("subject_code_display_mode") == "full" else "masked"
        active_tasks = [
            dict(row)
            for row in connection.execute(
                "SELECT id, table_index, field_key, title, task_type FROM visit_tasks WHERE visit_id = ? AND is_active = 1 ORDER BY table_index",
                (visit_id,),
            ).fetchall()
        ]
        _route_proposals_to_active_tasks(proposals, active_tasks, linked_task_id=linked_task_id)
        active_tasks_by_id = {str(task["id"]): task for task in active_tasks}
        active_tasks_by_table = {int(task["table_index"]): task for task in active_tasks}
        execution_id = uuid4().hex
        output_payload = [
            {
                "target_table": proposal["target_table"],
                "target_task_id": proposal.get("target_task_id", ""),
                "field_key": proposal.get("field_key", ""),
                "routing_method": proposal.get("routing_method", ""),
                "category": proposal["category"],
                "title": proposal["title"],
                "proposed_text": proposal["proposed_text"],
                "evidence_start": proposal.get("evidence_start", 0),
                "evidence_end": proposal.get("evidence_end", len(source)),
            }
            for proposal in proposals
        ]
        output_hash = hashlib.sha256(json.dumps(output_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        connection.execute(
            """
            INSERT INTO ai_executions (
                id, visit_id, source_record_id, provider, model_version, prompt_version, schema_version,
                rule_pack_version, executed_at, input_record_hash, output_hash, validation_status,
                retry_count, error_code, created_at
            ) VALUES (?, ?, ?, 'local_deterministic', 'simulated_ai.v2', 'keyword_rules.template_task_routing.v2', 'monitoring_suggestion.v1', ?, ?, ?, ?, 'valid', 0, '', ?)
            """,
            (
                execution_id,
                visit_id,
                record_id,
                rule_pack["version"] if rule_pack else "",
                timestamp,
                record["text_hash"] if record else "",
                output_hash,
                timestamp,
            ),
        )
        stored_suggestions: list[dict[str, Any]] = []
        for suggestion in proposals:
            task = active_tasks_by_id.get(str(suggestion.get("target_task_id") or "")) or active_tasks_by_table.get(
                int(suggestion.get("target_table") or 0)
            )
            suggestion_id = uuid4().hex
            subject = _subject_metadata(
                extracted_subject=str(suggestion.get("subject", "未提供受试者编号")),
                source_by_alias=source_by_alias,
                known_subject_codes=known_subject_codes,
                display_mode=subject_display_mode,
            )
            entity_id = str(suggestion.get("entity_id") or "").strip()
            if subject["subject_code"] != "未提供受试者编号":
                entity_id = subject["subject_code"]
            payload = {
                "id": suggestion_id,
                "target_table": suggestion["target_table"],
                "target_task_id": task["id"] if task else None,
                "field_key": task["field_key"] if task else suggestion.get("field_key") or f"table_{suggestion['target_table']}",
                "category": suggestion["category"],
                "title": suggestion["title"],
                "proposed_text": suggestion["proposed_text"],
                "source": source,
                "subject": subject["subject_code"],
                "subject_validation_status": subject["subject_validation_status"],
                "subject_display_code": subject["subject_display_code"],
                "value_type": suggestion.get("value_type", "narrative"),
                "assertion_type": suggestion.get("assertion_type", "reported_observation"),
                "source_type": suggestion.get("source_type", "work_record"),
                "evidence_text": suggestion.get("evidence_text", source),
                "evidence_start": int(suggestion.get("evidence_start", 0)),
                "evidence_end": int(suggestion.get("evidence_end", len(source))),
                "entity_type": "subject" if subject["subject_code"] != "未提供受试者编号" else suggestion.get("entity_type", "visit"),
                "entity_id": entity_id or visit_id,
                "pending_reason": suggestion.get("pending_reason", "需 CRA 对照原始记录确认"),
                "ai_execution_id": execution_id,
                "status": "pending",
                "created_at": timestamp,
                "confidence": 0.78 if suggestion["category"] in {"icf", "deviation", "ae", "sae"} else 0.66,
            }
            connection.execute(
                """
                INSERT INTO suggestions (
                    id, visit_id, source_record_id, target_task_id, target_table, field_key, category, title,
                    proposed_text, source_text, value_type, assertion_type, source_type, evidence_text,
                    evidence_start, evidence_end, entity_type, entity_id, pending_reason, ai_execution_id,
                    subject_code, subject_validation_status, subject_display_code, confidence, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    suggestion_id,
                    visit_id,
                    record_id,
                    payload["target_task_id"],
                    payload["target_table"],
                    payload["field_key"],
                    payload["category"],
                    payload["title"],
                    payload["proposed_text"],
                    source,
                    payload["value_type"],
                    payload["assertion_type"],
                    payload["source_type"],
                    payload["evidence_text"],
                    payload["evidence_start"],
                    payload["evidence_end"],
                    payload["entity_type"],
                    payload["entity_id"],
                    payload["pending_reason"],
                    payload["ai_execution_id"],
                    payload["subject"],
                    payload["subject_validation_status"],
                    payload["subject_display_code"],
                    payload["confidence"],
                    timestamp,
                ),
            )
            stored_suggestions.append(payload)
        processing_status = "completed" if stored_suggestions else "no_suggestions"
        connection.execute(
            "UPDATE work_records SET processing_status = ?, processing_error = '', processed_at = ? WHERE id = ?",
            (processing_status, timestamp, record_id),
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="work_record",
            entity_id=record_id,
            action="processing_completed",
            actor_name=actor_name,
            detail={
                "suggestion_count": len(stored_suggestions),
                "processing_status": processing_status,
                "ai_execution_id": execution_id,
                "output_hash": output_hash,
                "subject_context": "pseudonymized_before_local_extraction",
                "record_source_type": source_type,
                "routing_methods": sorted({str(item.get("routing_method") or "unresolved") for item in proposals}),
                "linked_task_id": linked_task_id.strip(),
            },
        )
    return stored_suggestions, {"processing_status": processing_status, "processing_error": "", "processed_at": timestamp}


def process_saved_work_record(
    *,
    visit_id: str,
    record_id: str,
    source: str,
    actor_name: str,
    record_kind: str = "monitoring_note",
    linked_task_id: str = "",
) -> None:
    """Run local post-save organization after the raw work-paper record is already durable."""
    _process_work_record(
        visit_id=visit_id,
        record_id=record_id,
        source=source,
        actor_name=actor_name,
        record_kind=record_kind,
        linked_task_id=linked_task_id,
    )


def add_work_record(
    *,
    visit_id: str,
    text: str,
    created_by: str = "演示 CRA",
    record_kind: str = "monitoring_note",
    corrected_record_id: str | None = None,
    correction_reason: str = "",
    linked_task_id: str = "",
    recorded_at: str = "",
    client_created_at: str = "",
    client_timezone: str = "",
    tags: list[str] | None = None,
    client_idempotency_key: str = "",
    defer_processing: bool = False,
) -> dict[str, Any]:
    source = text.strip()
    if not source:
        raise ValueError("监查记录不能为空")
    reason = correction_reason.strip()
    correction_target_id = (corrected_record_id or "").strip()
    if record_kind == "correction" and not correction_target_id:
        raise ValueError("更正记录必须关联原始监查记录")
    if record_kind == "correction" and not reason:
        raise ValueError("请填写更正原因")
    timestamp = _now()
    record_id = uuid4().hex
    normalized_task_id = linked_task_id.strip()
    normalized_recorded_at = recorded_at.strip()
    normalized_client_created_at = client_created_at.strip() or timestamp
    normalized_client_timezone = client_timezone.strip() or "unknown"
    normalized_tags = [str(item).strip() for item in (tags or []) if str(item).strip()]
    normalized_client_key = client_idempotency_key.strip()
    text_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    with transaction() as connection:
        visit = _visit_context(connection, visit_id)
        _require_editable_visit(visit)
        if normalized_client_key:
            existing = connection.execute(
                "SELECT * FROM work_records WHERE visit_id = ? AND client_idempotency_key = ?",
                (visit_id, normalized_client_key),
            ).fetchone()
            if existing is not None:
                existing_suggestions = connection.execute(
                    """
                    SELECT id, target_task_id, target_table, field_key, category, title, proposed_text, source_text,
                            value_type, assertion_type, source_type, evidence_text, evidence_start, evidence_end,
                           entity_type, entity_id, pending_reason, ai_execution_id, subject_code,
                           subject_validation_status, subject_display_code, confidence,
                           status, created_at
                    FROM suggestions
                    WHERE source_record_id = ? AND is_active = 1
                    ORDER BY created_at, rowid
                    """,
                    (existing["id"],),
                ).fetchall()
                return {
                    "record": _work_record_payload(existing),
                    "suggestions": [
                        {
                            "id": item["id"],
                            "target_task_id": item["target_task_id"],
                            "target_table": item["target_table"],
                            "field_key": item["field_key"],
                            "category": item["category"],
                            "title": item["title"],
                            "proposed_text": item["proposed_text"],
                            "source": item["source_text"],
                            "value_type": item["value_type"],
                            "assertion_type": item["assertion_type"],
                            "source_type": item["source_type"],
                            "evidence_text": item["evidence_text"],
                            "evidence_start": item["evidence_start"],
                            "evidence_end": item["evidence_end"],
                            "entity_type": item["entity_type"],
                            "entity_id": item["entity_id"],
                            "pending_reason": item["pending_reason"],
                            "ai_execution_id": item["ai_execution_id"],
                            "subject": item["subject_code"],
                            "subject_validation_status": item["subject_validation_status"],
                            "subject_display_code": item["subject_display_code"],
                            "confidence": item["confidence"],
                            "status": item["status"],
                            "created_at": item["created_at"],
                        }
                        for item in existing_suggestions
                    ],
                    "idempotent_reuse": True,
                }
        if correction_target_id:
            original = connection.execute(
                "SELECT id FROM work_records WHERE id = ? AND visit_id = ?",
                (correction_target_id, visit_id),
            ).fetchone()
            if original is None:
                raise ValueError("未找到需要更正的原始监查记录")
        connection.execute(
            """
            INSERT INTO work_records (
                id, visit_id, text, record_kind, created_by, linked_task_id, recorded_at,
                client_created_at, client_timezone, server_received_at, text_hash, processing_status,
                tags_json, client_idempotency_key, corrected_record_id, correction_reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                visit_id,
                source,
                record_kind,
                created_by,
                normalized_task_id,
                normalized_recorded_at,
                normalized_client_created_at,
                normalized_client_timezone,
                timestamp,
                text_hash,
                json.dumps(normalized_tags, ensure_ascii=False),
                normalized_client_key,
                correction_target_id or None,
                reason,
                timestamp,
            ),
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="work_record",
            entity_id=record_id,
            action="created",
            actor_name=created_by,
            detail={
                "processing_status": "pending",
                "record_kind": record_kind,
                "corrected_record_id": correction_target_id,
                "correction_reason": reason,
                "linked_task_id": normalized_task_id,
                "recorded_at": normalized_recorded_at,
                "client_created_at": normalized_client_created_at,
                "client_timezone": normalized_client_timezone,
                "server_received_at": timestamp,
                "text_hash": text_hash,
                "tags": normalized_tags,
                "client_idempotency_key": normalized_client_key,
            },
        )
    record_payload = {
        "id": record_id,
        "text": source,
        "record_kind": record_kind,
        "created_by": created_by,
        "linked_task_id": normalized_task_id,
        "recorded_at": normalized_recorded_at,
        "client_created_at": normalized_client_created_at,
        "client_timezone": normalized_client_timezone,
        "server_received_at": timestamp,
        "text_hash": text_hash,
        "processing_status": "pending",
        "processing_error": "",
        "processed_at": "",
        "tags": normalized_tags,
        "client_idempotency_key": normalized_client_key,
        "corrected_record_id": correction_target_id or None,
        "correction_reason": reason,
        "record_status": "active",
        "void_reason": "",
        "voided_at": "",
        "voided_by": "",
        "created_at": timestamp,
    }
    if defer_processing:
        return {"record": record_payload, "suggestions": [], "processing_deferred": True}
    stored_suggestions, processing = _process_work_record(
        visit_id=visit_id,
        record_id=record_id,
        source=source,
        actor_name=created_by,
        record_kind=record_kind,
        linked_task_id=normalized_task_id,
    )
    record_payload.update(processing)
    return {"record": record_payload, "suggestions": stored_suggestions}


def correct_work_record(
    *,
    visit_id: str,
    corrected_record_id: str,
    text: str,
    correction_reason: str,
    created_by: str = "演示 CRA",
) -> dict[str, Any]:
    original_record = next(
        (item for item in list_work_records(visit_id) if str(item.get("id") or "") == corrected_record_id),
        None,
    )
    return add_work_record(
        visit_id=visit_id,
        text=text,
        created_by=created_by,
        record_kind="correction",
        corrected_record_id=corrected_record_id,
        correction_reason=correction_reason,
        linked_task_id=str(original_record.get("linked_task_id") or "") if original_record else "",
    )


def void_work_record(
    *,
    visit_id: str,
    record_id: str,
    reason: str,
    actor_name: str = "演示 CRA",
) -> dict[str, Any]:
    """Retire one work-paper record without deleting its historical evidence."""
    void_reason = reason.strip()
    if not void_reason:
        raise ValueError("请填写撤销原因")
    timestamp = _now()
    with transaction() as connection:
        visit = _visit_context(connection, visit_id)
        _require_editable_visit(visit)
        record = connection.execute(
            "SELECT * FROM work_records WHERE id = ? AND visit_id = ?",
            (record_id, visit_id),
        ).fetchone()
        if record is None:
            raise ValueError("未找到该监查记录")
        if record["record_status"] == "voided":
            raise ValueError("该监查记录已撤销")
        connection.execute(
            """
            UPDATE work_records
            SET record_status = 'voided', void_reason = ?, voided_at = ?, voided_by = ?
            WHERE id = ?
            """,
            (void_reason, timestamp, actor_name, record_id),
        )
        deactivated_suggestions = connection.execute(
            "UPDATE suggestions SET is_active = 0 WHERE visit_id = ? AND source_record_id = ? AND is_active = 1",
            (visit_id, record_id),
        ).rowcount
        deactivated_confirmed_fields = connection.execute(
            "UPDATE confirmed_fields SET is_active = 0 WHERE visit_id = ? AND source_record_id = ? AND is_active = 1",
            (visit_id, record_id),
        ).rowcount
        working_revision_count = connection.execute(
            "SELECT COUNT(*) AS count FROM report_revisions WHERE visit_id = ? AND status IN ('draft', 'returned')",
            (visit_id,),
        ).fetchone()["count"]
        connection.execute("UPDATE visits SET updated_at = ? WHERE id = ?", (timestamp, visit_id))
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="work_record",
            entity_id=record_id,
            action="voided",
            actor_name=actor_name,
            detail={
                "reason": void_reason,
                "deactivated_suggestion_count": deactivated_suggestions,
                "deactivated_confirmed_field_count": deactivated_confirmed_fields,
                "working_revision_count": working_revision_count,
            },
        )
    return {
        "record": {
            "id": record_id,
            "record_status": "voided",
            "void_reason": void_reason,
            "voided_at": timestamp,
            "voided_by": actor_name,
        },
        "affected": {
            "suggestions": deactivated_suggestions,
            "confirmed_fields": deactivated_confirmed_fields,
            "working_revisions": working_revision_count,
        },
    }


def _create_finding(connection, *, visit_id: str, subject_code: str, category: str, description: str, source_suggestion_id: str, severity: str = "normal") -> str:
    finding_id = uuid4().hex
    timestamp = _now()
    connection.execute(
        """
        INSERT INTO findings (id, visit_id, subject_code, category, description, severity, status, source_suggestion_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
        """,
        (finding_id, visit_id, subject_code, category, description, severity, source_suggestion_id, timestamp, timestamp),
    )
    return finding_id


def _normalize_finding_ids(connection, *, visit_id: str, finding_ids: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw_id in finding_ids or []:
        finding_id = str(raw_id or "").strip()
        if finding_id and finding_id not in normalized:
            normalized.append(finding_id)
    if not normalized:
        return []
    placeholders = ", ".join("?" for _ in normalized)
    rows = connection.execute(
        f"SELECT id FROM findings WHERE visit_id = ? AND id IN ({placeholders})",
        (visit_id, *normalized),
    ).fetchall()
    found_ids = {row["id"] for row in rows}
    missing_ids = [finding_id for finding_id in normalized if finding_id not in found_ids]
    if missing_ids:
        raise ValueError("关联发现必须属于当前访视")
    return normalized


def _current_action_item_finding_ids(connection, *, action_item_id: str, legacy_finding_id: str | None) -> list[str]:
    linked_ids = [
        row["finding_id"]
        for row in connection.execute(
            "SELECT finding_id FROM action_item_findings WHERE action_item_id = ? ORDER BY created_at, rowid",
            (action_item_id,),
        ).fetchall()
    ]
    if legacy_finding_id and legacy_finding_id not in linked_ids:
        linked_ids.insert(0, legacy_finding_id)
    return linked_ids


def _replace_action_item_finding_links(
    connection,
    *,
    action_item_id: str,
    finding_ids: list[str],
    actor_name: str,
    timestamp: str,
) -> None:
    connection.execute("DELETE FROM action_item_findings WHERE action_item_id = ?", (action_item_id,))
    for finding_id in finding_ids:
        connection.execute(
            """
            INSERT INTO action_item_findings (id, action_item_id, finding_id, created_by, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (uuid4().hex, action_item_id, finding_id, actor_name, timestamp),
        )
    connection.execute(
        "UPDATE action_items SET finding_id = ?, updated_at = ? WHERE id = ?",
        (finding_ids[0] if finding_ids else None, timestamp, action_item_id),
    )


def _create_action_item(
    connection,
    *,
    visit_id: str,
    finding_id: str | None,
    finding_ids: list[str] | None = None,
    source_action_item_id: str | None = None,
    title: str,
    description: str,
    owner: str = "CRA / 中心待确认",
    due_date: str = "",
    actor_name: str = "演示 CRA",
) -> str:
    candidates = list(finding_ids or [])
    if finding_id:
        candidates.insert(0, finding_id)
    normalized_finding_ids = _normalize_finding_ids(connection, visit_id=visit_id, finding_ids=candidates)
    action_item_id = uuid4().hex
    timestamp = _now()
    connection.execute(
        """
        INSERT INTO action_items (id, visit_id, finding_id, source_action_item_id, title, description, owner, due_date, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
        """,
        (
            action_item_id,
            visit_id,
            normalized_finding_ids[0] if normalized_finding_ids else None,
            source_action_item_id,
            title,
            description,
            owner,
            due_date,
            timestamp,
            timestamp,
        ),
    )
    _replace_action_item_finding_links(
        connection,
        action_item_id=action_item_id,
        finding_ids=normalized_finding_ids,
        actor_name=actor_name,
        timestamp=timestamp,
    )
    return action_item_id


def _decide_suggestion_in_transaction(
    connection,
    *,
    visit,
    visit_id: str,
    suggestion_id: str,
    decision: Literal["accepted", "edited", "rejected"],
    actor_name: str,
    edited_text: str | None,
    decision_reason: str,
    timestamp: str,
) -> dict[str, Any]:
    suggestion = connection.execute(
        "SELECT * FROM suggestions WHERE id = ? AND visit_id = ? AND is_active = 1", (suggestion_id, visit_id)
    ).fetchone()
    if suggestion is None:
        raise ValueError("未找到该访视的建议")
    if suggestion["status"] != "pending":
        raise ValueError("该建议已处理")
    final_text = (edited_text or suggestion["proposed_text"]).strip() if decision in {"accepted", "edited"} else ""
    if decision in {"accepted", "edited"} and not final_text:
        raise ValueError("确认内容不能为空")
    normalized_decision_reason = decision_reason.strip()
    if decision == "edited" and suggestion["category"] in _CRITICAL_EDIT_CATEGORIES and not normalized_decision_reason:
        raise ValueError("修改知情同意、AE/SAE、方案偏离或法规文件等关键字段时必须填写原因")
    connection.execute(
        "UPDATE suggestions SET status = ?, final_text = ?, decided_at = ?, decided_by = ? WHERE id = ?",
        (decision, final_text, timestamp, actor_name, suggestion_id),
    )
    result: dict[str, Any] = {"suggestion_id": suggestion_id, "decision": decision, "final_text": final_text}
    if decision in {"accepted", "edited"}:
        is_center_explanation = suggestion["assertion_type"] == "center_explanation" or suggestion["source_type"] == "center_explanation"
        field_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO confirmed_fields (
                id, visit_id, suggestion_id, source_record_id, target_table, field_key, category,
                subject_code, assertion_type, source_type, subject_validation_status, subject_display_code,
                value, decision, decision_reason, confirmed_by, confirmed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                field_id,
                visit_id,
                suggestion_id,
                suggestion["source_record_id"],
                suggestion["target_table"],
                suggestion["field_key"] or f"table_{suggestion['target_table']}",
                suggestion["category"],
                suggestion["subject_code"],
                suggestion["assertion_type"],
                suggestion["source_type"],
                suggestion["subject_validation_status"],
                suggestion["subject_display_code"],
                final_text,
                decision,
                normalized_decision_reason,
                actor_name,
                timestamp,
            ),
        )
        if suggestion["target_task_id"] and not is_center_explanation:
            connection.execute(
                "UPDATE visit_tasks SET status = '已确认', evidence = ?, updated_at = ? WHERE id = ? AND is_active = 1",
                (f"CRA 已确认：{final_text[:52]}", timestamp, suggestion["target_task_id"]),
            )
        finding_id: str | None = None
        if not is_center_explanation and suggestion["category"] in {"ae", "sae", "deviation"}:
            finding_id = _create_finding(
                connection,
                visit_id=visit_id,
                subject_code=suggestion["subject_code"],
                category=suggestion["category"],
                description=final_text,
                source_suggestion_id=suggestion_id,
                severity="high" if suggestion["category"] in {"sae", "deviation"} else "normal",
            )
        if not is_center_explanation and suggestion["category"] == "action":
            action_item_id = _create_action_item(
                connection,
                visit_id=visit_id,
                finding_id=finding_id,
                title="CRA 记录的后续跟进事项",
                description=final_text,
                actor_name=actor_name,
            )
            result["action_item_id"] = action_item_id
        result["confirmed_field_id"] = field_id
    _audit(
        connection,
        project_id=visit["project_id"],
        visit_id=visit_id,
        entity_type="suggestion",
        entity_id=suggestion_id,
        action=decision,
        actor_name=actor_name,
        detail={
            "target_table": suggestion["target_table"],
            "category": suggestion["category"],
            "assertion_type": suggestion["assertion_type"],
            "source_type": suggestion["source_type"],
            "subject_validation_status": suggestion["subject_validation_status"],
            "decision_reason": normalized_decision_reason,
        },
    )
    return result


def decide_suggestion(
    *,
    visit_id: str,
    suggestion_id: str,
    decision: Literal["accepted", "edited", "rejected"],
    actor_name: str,
    edited_text: str | None = None,
    decision_reason: str = "",
) -> dict[str, Any]:
    timestamp = _now()
    with transaction() as connection:
        visit = _visit_context(connection, visit_id)
        _require_editable_visit(visit)
        return _decide_suggestion_in_transaction(
            connection,
            visit=visit,
            visit_id=visit_id,
            suggestion_id=suggestion_id,
            decision=decision,
            actor_name=actor_name,
            edited_text=edited_text,
            decision_reason=decision_reason,
            timestamp=timestamp,
        )


def assign_suggestion_target(
    *,
    visit_id: str,
    suggestion_id: str,
    target_task_id: str,
    actor_name: str,
) -> dict[str, Any]:
    """Let CRA correct the suggested template-task routing before confirming a fact."""
    normalized_task_id = target_task_id.strip()
    if not normalized_task_id:
        raise ValueError("请选择建议应归类到的监查任务")
    timestamp = _now()
    with transaction() as connection:
        visit = _visit_context(connection, visit_id)
        _require_editable_visit(visit)
        suggestion = connection.execute(
            "SELECT * FROM suggestions WHERE id = ? AND visit_id = ? AND is_active = 1",
            (suggestion_id, visit_id),
        ).fetchone()
        if suggestion is None:
            raise ValueError("未找到该访视的建议")
        if suggestion["status"] != "pending":
            raise ValueError("仅待 CRA 确认的建议可重新归类")
        target_task = connection.execute(
            "SELECT id, table_index, field_key, title, task_type FROM visit_tasks WHERE id = ? AND visit_id = ? AND is_active = 1",
            (normalized_task_id, visit_id),
        ).fetchone()
        if target_task is None:
            raise ValueError("请选择当前访视中有效的监查任务")
        connection.execute(
            "UPDATE suggestions SET target_task_id = ?, target_table = ?, field_key = ? WHERE id = ?",
            (target_task["id"], target_task["table_index"], target_task["field_key"], suggestion_id),
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="suggestion",
            entity_id=suggestion_id,
            action="target_reassigned",
            actor_name=actor_name,
            detail={
                "previous_target_task_id": suggestion["target_task_id"],
                "previous_target_table": suggestion["target_table"],
                "previous_field_key": suggestion["field_key"],
                "target_task_id": target_task["id"],
                "target_table": target_task["table_index"],
                "field_key": target_task["field_key"],
                "target_title": target_task["title"],
                "target_task_type": target_task["task_type"],
            },
        )
    return {
        "id": suggestion_id,
        "target_task_id": target_task["id"],
        "target_table": target_task["table_index"],
        "field_key": target_task["field_key"],
        "target_title": target_task["title"],
    }


def decide_suggestions_batch(
    *,
    visit_id: str,
    suggestion_ids: list[str],
    decision: Literal["accepted", "rejected"],
    actor_name: str,
) -> dict[str, Any]:
    selected_ids = list(dict.fromkeys(item.strip() for item in suggestion_ids if item.strip()))
    if not selected_ids:
        raise ValueError("请至少选择一条待确认建议")
    timestamp = _now()
    with transaction() as connection:
        visit = _visit_context(connection, visit_id)
        _require_editable_visit(visit)
        results = [
            _decide_suggestion_in_transaction(
                connection,
                visit=visit,
                visit_id=visit_id,
                suggestion_id=suggestion_id,
                decision=decision,
                actor_name=actor_name,
                edited_text=None,
                decision_reason="",
                timestamp=timestamp,
            )
            for suggestion_id in selected_ids
        ]
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="suggestion_batch",
            entity_id=uuid4().hex,
            action=decision,
            actor_name=actor_name,
            detail={"suggestion_ids": selected_ids, "count": len(results)},
        )
    return {"items": results}


def create_action_item(
    *,
    visit_id: str,
    title: str,
    description: str,
    owner: str,
    due_date: str = "",
    finding_id: str | None = None,
    finding_ids: list[str] | None = None,
    actor_name: str = "演示 CRA",
) -> dict[str, Any]:
    with transaction() as connection:
        visit = _visit_context(connection, visit_id)
        action_item_id = _create_action_item(
            connection,
            visit_id=visit_id,
            finding_id=finding_id,
            finding_ids=finding_ids,
            title=title.strip(),
            description=description.strip(),
            owner=owner.strip(),
            due_date=due_date.strip(),
            actor_name=actor_name,
        )
        linked_finding_ids = _current_action_item_finding_ids(
            connection,
            action_item_id=action_item_id,
            legacy_finding_id=None,
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="action_item",
            entity_id=action_item_id,
            action="created",
            actor_name=actor_name,
            detail={"title": title.strip(), "due_date": due_date.strip(), "finding_ids": finding_ids or ([finding_id] if finding_id else [])},
        )
        if linked_finding_ids:
            _audit(
                connection,
                project_id=visit["project_id"],
                visit_id=visit_id,
                entity_type="action_item_finding_link",
                entity_id=action_item_id,
                action="created",
                actor_name=actor_name,
                detail={"before_finding_ids": [], "after_finding_ids": linked_finding_ids},
            )
    return next((item for item in list_action_items(visit_id) if item["id"] == action_item_id), {})


def create_historical_action_follow_up(
    *,
    visit_id: str,
    source_action_item_id: str,
    actor_name: str,
) -> dict[str, Any]:
    with transaction() as connection:
        visit = _visit_context(connection, visit_id)
        _require_editable_visit(visit)
        source_action = connection.execute(
            """
            SELECT action_item.*, source_visit.project_id, source_visit.site_id,
                source_visit.code AS source_visit_code, source_visit.visit_date AS source_visit_date
            FROM action_items action_item
            JOIN visits source_visit ON source_visit.id = action_item.visit_id
            WHERE action_item.id = ?
            """,
            (source_action_item_id,),
        ).fetchone()
        if source_action is None:
            raise ValueError("未找到既往行动项")
        if source_action["visit_id"] == visit_id:
            raise ValueError("当前访视行动项无需再次带入")
        if source_action["project_id"] != visit["project_id"] or source_action["site_id"] != visit["site_id"]:
            raise ValueError("既往行动项必须属于当前项目和中心")
        if source_action["source_visit_date"] > visit["visit_date"]:
            raise ValueError("不能从后续访视带入行动项")
        if source_action["status"] == "closed":
            raise ValueError("已关闭的既往行动项无需带入")
        existing_follow_up = connection.execute(
            "SELECT id FROM action_items WHERE source_action_item_id = ? LIMIT 1",
            (source_action_item_id,),
        ).fetchone()
        if existing_follow_up is not None:
            raise ValueError("该既往行动项已在后续访视建立跟进")
        action_item_id = _create_action_item(
            connection,
            visit_id=visit_id,
            finding_id=None,
            source_action_item_id=source_action_item_id,
            title=f"既往事项跟进：{source_action['title']}"[:200],
            description=f"来源访视 {source_action['source_visit_code']}：{source_action['description']}",
            owner=source_action["owner"],
            due_date=source_action["due_date"],
            actor_name=actor_name,
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="historical_action_follow_up",
            entity_id=action_item_id,
            action="created",
            actor_name=actor_name,
            detail={
                "source_action_item_id": source_action_item_id,
                "source_visit_code": source_action["source_visit_code"],
                "source_visit_date": source_action["source_visit_date"],
            },
        )
    return next((item for item in list_action_items(visit_id) if item["id"] == action_item_id), {})


def update_action_item_finding_links(
    *,
    visit_id: str,
    action_item_id: str,
    finding_ids: list[str],
    actor_name: str,
) -> dict[str, Any]:
    timestamp = _now()
    with transaction() as connection:
        visit = _visit_context(connection, visit_id)
        _require_editable_visit(visit)
        action = connection.execute(
            "SELECT id, finding_id FROM action_items WHERE id = ? AND visit_id = ?",
            (action_item_id, visit_id),
        ).fetchone()
        if action is None:
            raise ValueError("未找到该访视的行动项")
        before_ids = _current_action_item_finding_ids(
            connection,
            action_item_id=action_item_id,
            legacy_finding_id=action["finding_id"],
        )
        normalized_finding_ids = _normalize_finding_ids(connection, visit_id=visit_id, finding_ids=finding_ids)
        _replace_action_item_finding_links(
            connection,
            action_item_id=action_item_id,
            finding_ids=normalized_finding_ids,
            actor_name=actor_name,
            timestamp=timestamp,
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="action_item_finding_link",
            entity_id=action_item_id,
            action="replaced",
            actor_name=actor_name,
            detail={"before_finding_ids": before_ids, "after_finding_ids": normalized_finding_ids},
        )
    return next((item for item in list_action_items(visit_id) if item["id"] == action_item_id), {})


def update_action_item(*, visit_id: str, action_item_id: str, patch: dict[str, Any], actor_name: str) -> dict[str, Any]:
    allowed = {"title", "description", "owner", "due_date", "status", "closure_note"}
    requested_fields = [(key, str(value).strip()) for key, value in patch.items() if key in allowed]
    status_change_note = str(patch.get("status_change_note") or "").strip()
    if not requested_fields:
        raise ValueError("没有可更新的行动项字段")
    timestamp = _now()
    with transaction() as connection:
        visit = _visit_context(connection, visit_id)
        action = connection.execute("SELECT * FROM action_items WHERE id = ? AND visit_id = ?", (action_item_id, visit_id)).fetchone()
        if action is None:
            raise ValueError("未找到该访视的行动项")
        fields = list(requested_fields)
        next_status = next((value for key, value in fields if key == "status"), None)
        if next_status == "closed":
            fields.append(("closed_at", timestamp))
        elif next_status in {"open", "in_progress"}:
            # `closed_at` describes the current closure only. Re-opening a
            # tracked issue must not leave a stale closed timestamp behind.
            fields.append(("closed_at", ""))
        fields.append(("updated_at", timestamp))
        assignments = ", ".join(f"{key} = ?" for key, _ in fields)
        connection.execute(f"UPDATE action_items SET {assignments} WHERE id = ?", (*[value for _, value in fields], action_item_id))
        audit_detail = {key: value for key, value in fields if key not in {"updated_at", "closed_at"}}
        if next_status and next_status != action["status"]:
            audit_detail["status_transition"] = {
                "from": action["status"],
                "to": next_status,
                "note": status_change_note,
                "cleared_closed_at": next_status in {"open", "in_progress"},
            }
        elif status_change_note:
            audit_detail["status_change_note"] = status_change_note
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="action_item",
            entity_id=action_item_id,
            action="updated",
            actor_name=actor_name,
            detail=audit_detail,
        )
        row = connection.execute("SELECT * FROM action_items WHERE id = ?", (action_item_id,)).fetchone()
    return dict(row)


def submit_revision(
    *,
    revision_id: str,
    actor_name: str,
    confirmed: bool,
    actor_member_id: str = "",
    idempotency_key: str = "",
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("请先勾选 CRA 确认声明，再提交报告")
    normalized_key = idempotency_key.strip()
    timestamp = _now()
    with transaction() as connection:
        revision = connection.execute("SELECT * FROM report_revisions WHERE id = ?", (revision_id,)).fetchone()
        if revision is None:
            raise ValueError("未找到报告修订版本")
        if revision["status"] != "draft":
            if (
                normalized_key
                and revision["status"] == "submitted"
                and str(revision["submission_idempotency_key"] or "") == normalized_key
            ):
                return get_revision(revision_id) or {}
            raise ValueError("请提交当前关联的工作草稿；历史正式版本不可重复提交")
        visit = _visit_context(connection, revision["visit_id"])
        readiness = evaluate_report_readiness(visit["id"])
        if not readiness["ready"]:
            raise ValueError(readiness_error(readiness))
        stored_field_hash = str(revision["confirmed_field_hash"] or "").strip()
        if stored_field_hash:
            current_field_hash = compute_confirmed_field_hash(visit["id"], connection=connection)
            if current_field_hash != stored_field_hash:
                raise ValueError(
                    "自上次生成报告后，确认字段或语言优化决定已发生变化，字段哈希不一致；请重新生成报告后再提交"
                )
        connection.execute(
            """
            UPDATE report_revisions
            SET revision_type = 'formal', status = 'submitted', submitted_at = ?, submitted_by = ?,
                submitted_by_member_id = ?, submission_idempotency_key = ?, review_started_at = '',
                review_started_by = '', review_started_by_member_id = ''
            WHERE id = ?
            """,
            (timestamp, actor_name, actor_member_id, normalized_key, revision_id),
        )
        connection.execute("UPDATE visits SET status = 'submitted', updated_at = ? WHERE id = ?", (timestamp, visit["id"]))
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit["id"],
            entity_type="report_revision",
            entity_id=revision_id,
            action="submitted",
            actor_name=actor_name,
            detail={"version": revision["version_number"], "cra_confirmation": True, "readiness": readiness["summary"]},
        )
    return get_revision(revision_id) or {}


def _create_related_working_revision(connection, *, revision, timestamp: str) -> dict[str, Any]:
    revision_id = uuid4().hex
    count = connection.execute(
        "SELECT COUNT(*) AS count FROM report_revisions WHERE visit_id = ?",
        (revision["visit_id"],),
    ).fetchone()["count"]
    version_number = f"V0.{int(count) + 1}"
    connection.execute(
        """
        INSERT INTO report_revisions (
            id, visit_id, parent_revision_id, version_number, revision_type, status,
            file_name, file_path, generated_at, submitted_at, submitted_by, created_at
        ) VALUES (?, ?, ?, ?, 'working', 'draft', '', '', '', '', '', ?)
        """,
        (revision_id, revision["visit_id"], revision["id"], version_number, timestamp),
    )
    return {"id": revision_id, "version_number": version_number, "parent_revision_id": revision["id"]}


def start_revision_review(*, revision_id: str, reviewer_name: str, reviewer_member_id: str = "") -> dict[str, Any]:
    timestamp = _now()
    with transaction() as connection:
        revision = connection.execute("SELECT * FROM report_revisions WHERE id = ?", (revision_id,)).fetchone()
        if revision is None:
            raise ValueError("未找到报告修订版本")
        if revision["status"] != "submitted":
            raise ValueError("只有待审核的正式报告可以开始审核")
        _require_distinct_submitter(revision, reviewer_name, action="开始审核")
        visit = _visit_context(connection, revision["visit_id"])
        if not str(revision["review_started_at"] or "").strip():
            connection.execute(
                "UPDATE report_revisions SET review_started_at = ?, review_started_by = ?, review_started_by_member_id = ? WHERE id = ?",
                (timestamp, reviewer_name.strip(), reviewer_member_id, revision_id),
            )
            _audit(
                connection,
                project_id=visit["project_id"],
                visit_id=visit["id"],
                entity_type="report_revision",
                entity_id=revision_id,
                action="review_started",
                actor_name=reviewer_name,
                detail={"version": revision["version_number"]},
            )
    return get_revision(revision_id) or {}


def withdraw_revision(*, revision_id: str, actor_name: str, reason: str) -> dict[str, Any]:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("请填写主动撤回原因")
    timestamp = _now()
    with transaction() as connection:
        revision = connection.execute("SELECT * FROM report_revisions WHERE id = ?", (revision_id,)).fetchone()
        if revision is None:
            raise ValueError("未找到报告修订版本")
        if revision["status"] != "submitted":
            raise ValueError("只有待审核报告可以由 CRA 主动撤回")
        if str(revision["review_started_at"] or "").strip():
            raise ValueError("PM/LM 已开始审核，CRA 不能主动撤回；请等待审核退回")
        visit = _visit_context(connection, revision["visit_id"])
        working_revision = _create_related_working_revision(connection, revision=revision, timestamp=timestamp)
        connection.execute(
            """
            UPDATE report_revisions
            SET status = 'withdrawn', withdrawn_at = ?, withdrawn_by = ?, withdrawn_reason = ?
            WHERE id = ?
            """,
            (timestamp, actor_name, normalized_reason, revision_id),
        )
        connection.execute("UPDATE visits SET status = 'draft', updated_at = ? WHERE id = ?", (timestamp, visit["id"]))
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit["id"],
            entity_type="report_revision",
            entity_id=revision_id,
            action="withdrawn_by_cra",
            actor_name=actor_name,
            detail={
                "version": revision["version_number"],
                "reason": normalized_reason,
                "working_revision_id": working_revision["id"],
                "working_version": working_revision["version_number"],
            },
        )
    return {
        "withdrawn_revision": get_revision(revision_id) or {},
        "working_revision": get_revision(working_revision["id"]) or {},
    }


def void_approved_revision(*, revision_id: str, actor_name: str, reason: str) -> dict[str, Any]:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("请填写作废原因")
    timestamp = _now()
    with transaction() as connection:
        revision = connection.execute("SELECT * FROM report_revisions WHERE id = ?", (revision_id,)).fetchone()
        if revision is None:
            raise ValueError("未找到报告修订版本")
        if revision["status"] != "approved":
            raise ValueError("只有已批准的正式报告可以作废")
        visit = _visit_context(connection, revision["visit_id"])
        working_revision = _create_related_working_revision(connection, revision=revision, timestamp=timestamp)
        connection.execute(
            """
            UPDATE report_revisions
            SET status = 'voided', voided_at = ?, voided_by = ?, void_reason = ?
            WHERE id = ?
            """,
            (timestamp, actor_name.strip(), normalized_reason, revision_id),
        )
        connection.execute("UPDATE visits SET status = 'draft', updated_at = ? WHERE id = ?", (timestamp, visit["id"]))
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit["id"],
            entity_type="report_revision",
            entity_id=revision_id,
            action="voided_by_qa_clinical_ops",
            actor_name=actor_name,
            detail={
                "version": revision["version_number"],
                "reason": normalized_reason,
                "working_revision_id": working_revision["id"],
                "working_version": working_revision["version_number"],
            },
        )
    return {
        "voided_revision": get_revision(revision_id) or {},
        "working_revision": get_revision(working_revision["id"]) or {},
    }


def _require_distinct_submitter(revision, reviewer_name: str, *, action: str) -> None:
    """BR-20: 提交人与批准人必须为不同用户；不设置同人例外.

    project_members rows are role-scoped (a CRA row and a PM/LM row always
    have different member_id even for the same real person), so comparing
    member_id would never catch the case BR-20 actually targets: one person
    registered under two role hats. Compare the human-readable submitter/
    reviewer identity instead.
    """
    submitted_by = str(revision["submitted_by"] or "").strip()
    if submitted_by and submitted_by == reviewer_name.strip():
        raise ValueError(f"提交人与批准人须为不同用户，当前操作人与提交人「{submitted_by}」相同，不能{action}")


def _require_no_open_comments(connection, revision_id: str) -> None:
    """FR-11: 批准前必须确认无未处理审核意见."""
    open_count = connection.execute(
        "SELECT COUNT(*) AS count FROM review_comments WHERE revision_id = ? AND status = 'open' AND comment_type = 'pm_lm_review'",
        (revision_id,),
    ).fetchone()["count"]
    if open_count:
        raise ValueError(f"存在 {open_count} 条未处理的审核意见，须先由 CRA 处置完毕才能批准")


def review_revision(
    *,
    revision_id: str,
    action: Literal["comment", "returned", "approved"],
    message: str,
    reviewer_name: str,
    target_key: str = "",
    reviewer_member_id: str = "",
    idempotency_key: str = "",
) -> dict[str, Any]:
    timestamp = _now()
    normalized_key = idempotency_key.strip()
    with transaction() as connection:
        revision = connection.execute("SELECT * FROM report_revisions WHERE id = ?", (revision_id,)).fetchone()
        if revision is None:
            raise ValueError("未找到报告修订版本")
        visit = _visit_context(connection, revision["visit_id"])
        if revision["status"] != "submitted":
            if (
                action == "approved"
                and normalized_key
                and revision["status"] == "approved"
                and str(revision["approval_idempotency_key"] or "") == normalized_key
            ):
                return {"action": "approved", "status": "approved", "revision_id": revision_id, "idempotent_reuse": True}
            raise ValueError("报告尚未提交，暂不能审核")
        if action == "approved":
            _require_distinct_submitter(revision, reviewer_name, action="批准")
            _require_no_open_comments(connection, revision_id)
        if not str(revision["review_started_at"] or "").strip():
            connection.execute(
                "UPDATE report_revisions SET review_started_at = ?, review_started_by = ?, review_started_by_member_id = ? WHERE id = ?",
                (timestamp, reviewer_name.strip(), reviewer_member_id, revision_id),
            )
            _audit(
                connection,
                project_id=visit["project_id"],
                visit_id=visit["id"],
                entity_type="report_revision",
                entity_id=revision_id,
                action="review_started",
                actor_name=reviewer_name,
                detail={"version": revision["version_number"], "implicit": True},
            )
        comment_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO review_comments (id, revision_id, target_key, comment_type, action, message, reviewer_name, status, created_at)
            VALUES (?, ?, ?, 'pm_lm_review', ?, ?, ?, 'open', ?)
            """,
            (comment_id, revision_id, target_key, action, message.strip() or "未填写补充说明", reviewer_name.strip(), timestamp),
        )
        if action == "returned":
            connection.execute(
                "UPDATE report_revisions SET status = 'returned', decided_by_member_id = ? WHERE id = ?",
                (reviewer_member_id, revision_id),
            )
            working_revision = _create_related_working_revision(connection, revision=revision, timestamp=timestamp)
            connection.execute("UPDATE visits SET status = 'returned', updated_at = ? WHERE id = ?", (timestamp, visit["id"]))
        elif action == "approved":
            connection.execute(
                "UPDATE report_revisions SET status = 'approved', decided_by_member_id = ?, approval_idempotency_key = ? WHERE id = ?",
                (reviewer_member_id, normalized_key, revision_id),
            )
            connection.execute("UPDATE visits SET status = 'approved', updated_at = ? WHERE id = ?", (timestamp, visit["id"]))
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit["id"],
            entity_type="review_comment",
            entity_id=comment_id,
            action=action,
            actor_name=reviewer_name,
            detail={
                "revision_id": revision_id,
                "target_key": target_key,
                "comment_type": "pm_lm_review",
                "working_revision_id": working_revision["id"] if action == "returned" else "",
                "working_version": working_revision["version_number"] if action == "returned" else "",
            },
        )
        row = connection.execute("SELECT * FROM review_comments WHERE id = ?", (comment_id,)).fetchone()
    return dict(row)


def create_specialist_review_comment(
    *,
    revision_id: str,
    action: Literal["specialist_comment", "specialist_concurrence"],
    message: str,
    reviewer_name: str,
    target_key: str = "",
) -> dict[str, Any]:
    """Record a specialist note without changing the PM/LM review state machine."""
    normalized_message = message.strip()
    if action == "specialist_comment" and not normalized_message:
        raise ValueError("请填写专项批注内容")
    if action == "specialist_concurrence" and not normalized_message:
        normalized_message = "已阅，无补充专项意见。"
    timestamp = _now()
    with transaction() as connection:
        revision = connection.execute("SELECT * FROM report_revisions WHERE id = ?", (revision_id,)).fetchone()
        if revision is None:
            raise ValueError("未找到报告修订版本")
        if revision["status"] != "submitted":
            raise ValueError("只有待审核的正式报告可以记录专项意见")
        visit = _visit_context(connection, revision["visit_id"])
        comment_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO review_comments (id, revision_id, target_key, comment_type, action, message, reviewer_name, status, created_at)
            VALUES (?, ?, ?, ?, 'comment', ?, ?, 'open', ?)
            """,
            (comment_id, revision_id, target_key, action, normalized_message, reviewer_name.strip(), timestamp),
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit["id"],
            entity_type="specialist_review_comment",
            entity_id=comment_id,
            action=action,
            actor_name=reviewer_name,
            detail={
                "revision_id": revision_id,
                "target_key": target_key,
                "comment_type": action,
                "report_status": revision["status"],
            },
        )
        row = connection.execute("SELECT * FROM review_comments WHERE id = ?", (comment_id,)).fetchone()
    return dict(row)


def resolve_review_comment(
    *,
    visit_id: str,
    comment_id: str,
    resolution: Literal["accepted", "declined"],
    note: str,
    actor_name: str,
) -> dict[str, Any]:
    timestamp = _now()
    with transaction() as connection:
        visit = _visit_context(connection, visit_id)
        comment = connection.execute(
            """
            SELECT rc.*
            FROM review_comments rc
            JOIN report_revisions rr ON rr.id = rc.revision_id
            WHERE rc.id = ? AND rr.visit_id = ?
            """,
            (comment_id, visit_id),
        ).fetchone()
        if comment is None:
            raise ValueError("未找到该访视的审核意见")
        if comment["status"] != "open":
            raise ValueError("该审核意见已处理")
        resolution_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO review_comment_resolutions (id, review_comment_id, resolution, note, resolved_by, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (resolution_id, comment_id, resolution, note.strip(), actor_name, timestamp),
        )
        connection.execute(
            "UPDATE review_comments SET status = 'resolved', resolved_at = ? WHERE id = ?",
            (timestamp, comment_id),
        )
        _audit(
            connection,
            project_id=visit["project_id"],
            visit_id=visit_id,
            entity_type="review_comment",
            entity_id=comment_id,
            action=f"cra_{resolution}",
            actor_name=actor_name,
            detail={
                "target_key": comment["target_key"],
                "comment_type": comment["comment_type"] or "pm_lm_review",
                "note": note.strip(),
                "resolution_id": resolution_id,
            },
        )
        row = connection.execute(
            """
            SELECT rc.*, rcr.resolution, rcr.note AS resolution_note, rcr.resolved_by
            FROM review_comments rc
            JOIN review_comment_resolutions rcr ON rcr.review_comment_id = rc.id
            WHERE rc.id = ?
            """,
            (comment_id,),
        ).fetchone()
    return dict(row)
