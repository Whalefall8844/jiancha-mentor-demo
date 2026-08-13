from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from .auth import (
    Actor,
    ActorAuthMiddleware,
    SYSTEM_ADMIN_ROLE,
    get_actor,
    require_project_scope,
    require_roles,
)
from .database import get_connection, initialize_database, reset_database
from .models import (
    ActionItemCreate,
    ActionItemFindingLinksUpdate,
    ActionItemPatch,
    AdapterConfigPatch,
    AdministratorHandoverAcknowledgement,
    AdministratorHandoverCreate,
    ConfigurationApprovalAction,
    ControlledDocumentPatch,
    ClarificationRefreshRequest,
    ClarificationResponseRequest,
    CurrentRoleUpdate,
    EscalationCreate,
    EscalationDisposition,
    HistoricalActionFollowUpCreate,
    ImportBatchCommit,
    OfflineDraftSync,
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberPatch,
    ProjectEligibilityAssessmentApproval,
    ProjectEligibilityAssessmentCreate,
    ProjectEligibilityAssessmentPatch,
    ProjectPatch,
    ProjectUpdate,
    RecordCreate,
    RecordCorrectionCreate,
    RecordDuplicatePreview,
    RecordVoidRequest,
    ReportGenerateRequest,
    RevisionVoidRequest,
    RevisionWithdrawRequest,
    ReviewCommentResolve,
    ReviewCreate,
    ReviewStartRequest,
    SpecialistReviewCreate,
    RulePackCreate,
    RulePackPatch,
    SiteCreate,
    SiteMasterVersionCreate,
    SiteMasterVersionPatch,
    SitePatch,
    SubjectCodesUpdate,
    SubmitRequest,
    SuggestionBatchDecision,
    SuggestionDecision,
    SuggestionTargetAssignment,
    SyncConflictResolve,
    TaskBulkPatch,
    TaskPatch,
    TemplateFieldSlotCreate,
    TemplateFieldSlotPatch,
    TemplateFieldSlotSuggestionImportRequest,
    TemplateMappingSuggestionImportRequest,
    TemplateCompletenessRulesPatch,
    TemplateMappingPatch,
    TemplateRevisionDraftCreate,
    TemplateVisitTypeKeywordsPatch,
    TemplateSwitchRequest,
    TemplateSwitchRollbackRequest,
    LanguageSuggestionDecision,
    LanguageSuggestionRevocationRequest,
    MasterDataRefreshRequest,
    MasterDataRefreshRollbackRequest,
    VisitCreate,
    VisitCancellationRequest,
    VisitDateReassessmentRequest,
    VisitPatch,
)
from .repositories.catalog import (
    create_rule_pack,
    create_configuration_audit_event,
    create_project,
    create_project_member,
    create_site,
    get_setting,
    get_project,
    get_rule_pack,
    get_site,
    get_template,
    list_projects,
    list_project_members,
    list_rule_packs,
    list_sites,
    list_subject_codes,
    list_templates,
    save_subject_codes,
    set_setting,
    update_project as update_project_record,
    update_project_member,
    update_rule_pack,
    update_site,
    update_template_mapping,
)
from .repositories.controlled_data import (
    create_controlled_document,
    create_site_master_version,
    get_controlled_document,
    get_site_master_version,
    list_controlled_documents,
    list_site_master_versions,
    patch_controlled_document,
    patch_site_master_version,
    resolve_frozen_master_data,
)
from .repositories.visits import (
    create_visit,
    get_revision,
    get_project_history_insights,
    get_visit,
    list_action_items,
    create_audit_event,
    list_revisions,
    list_tasks,
    update_task,
    update_visit,
)
from .services.monitoring import (
    add_work_record,
    assign_suggestion_target,
    cancel_draft_visit,
    correct_work_record,
    create_action_item,
    create_historical_action_follow_up,
    decide_suggestion,
    decide_suggestions_batch,
    resolve_review_comment,
    review_revision,
    create_specialist_review_comment,
    start_revision_review,
    submit_revision,
    process_saved_work_record,
    update_action_item,
    update_action_item_finding_links,
    void_approved_revision,
    withdraw_revision,
    find_duplicate_work_records,
    void_work_record,
)
from .services.language import (
    decide_language_suggestion,
    generate_language_suggestions,
    get_adapter_config,
    list_language_suggestions,
    revoke_language_suggestion,
    update_adapter_config,
)
from .services.project_eligibility import (
    create_project_eligibility_assessment,
    get_current_approved_assessment,
    list_project_eligibility_assessments,
    transition_project_eligibility_assessment,
    update_project_eligibility_assessment,
)
from .services.archive import build_evidence_chain, build_handover_package, export_audit_csv
from .services.imports import build_import_error_csv, commit_master_data_import, get_import_batch, get_project_import_quality, import_master_data, preview_master_data_import
from .services.reports import generate_revision
from .services.readiness import evaluate_report_readiness
from .services.clarifications import list_clarification_items, refresh_clarification_items, resolve_clarification_item
from .services.attachments import get_stored_attachment, list_visit_attachments, save_attachment
from .services.controlled_documents import get_stored_controlled_document, save_controlled_document_file
from .services.continuity import (
    acknowledge_administrator_visit_handover,
    bulk_complete_visit_tasks,
    create_administrator_visit_handover,
    create_escalation,
    dispose_escalation,
    get_visit_operations,
    get_visit_sync_token,
    list_offline_drafts,
    list_sync_conflicts,
    resolve_sync_conflict,
    sync_offline_draft,
)
from .services.templates import (
    create_template_field_slot_detail,
    delete_template_field_slot_detail,
    export_template_configuration_package,
    import_high_confidence_template_field_slot_suggestions,
    import_high_confidence_template_mapping_suggestions,
    import_template_configuration_package,
    create_template_revision_draft,
    get_template_detail as build_template_detail,
    get_template_recommendations,
    register_template,
    replace_template_revision_document,
    update_template_field_slot_detail,
    update_template_completeness_rules,
    update_template_visit_type_keywords,
)
from .services.configuration_approval import transition_rule_pack, transition_template
from .services.rule_eligibility import attach_rule_eligibility
from .services.template_switching import preview_template_switch, rollback_template_switch, switch_template
from .services.visit_date_reassessment import apply_visit_date_reassessment, preview_visit_date_reassessment
from .services.master_data_refresh import apply_master_data_refresh, preview_master_data_refresh, rollback_master_data_refresh
from .services.workspace import build_workspace, default_workspace


app = FastAPI(title="监查 Mentor Demo", version="0.3.0")
# Registered before CORSMiddleware so that, once Starlette builds its stack,
# CORSMiddleware ends up *outside* ActorAuthMiddleware and still attaches
# CORS headers to 401/403 responses produced by the auth layer.
app.add_middleware(ActorAuthMiddleware, fastapi_app=app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
initialize_database()


def _workspace_or_404(visit_id: str) -> dict[str, Any]:
    workspace = build_workspace(visit_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="未找到访视")
    return workspace


def _revision_or_404(revision_id: str) -> dict[str, Any]:
    revision = get_revision(revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="未找到报告修订版本")
    return revision


def _legacy_workspace(workspace: dict[str, Any]) -> dict[str, Any]:
    """Retain the original four-page demo contract while the frontend moves to the workspace API."""
    payload = dict(workspace)
    payload["table_tasks"] = [{**task, "index": task["table_index"]} for task in workspace["table_tasks"]]
    payload["system_check_tasks"] = [
        {**task, "index": task["table_index"]} for task in workspace.get("system_check_tasks", [])
    ]
    payload["suggestions"] = [
        {
            **suggestion,
            "source": suggestion.get("source_text", ""),
            "subject": suggestion.get("subject_code", ""),
        }
        for suggestion in workspace["suggestions"]
    ]
    payload["confirmed_items"] = [
        {
            **item,
            "text": item.get("value", ""),
            "subject": item.get("subject_code", ""),
        }
        for item in workspace["confirmed_items"]
    ]
    payload["center_explanations"] = [
        {
            **item,
            "text": item.get("value", ""),
            "subject": item.get("subject_code", ""),
        }
        for item in workspace.get("center_explanations", [])
    ]
    payload["ae_records"] = [
        {
            "id": finding["id"],
            "subject": finding.get("subject_code", ""),
            "description": finding.get("description", ""),
            "is_sae": finding.get("category") == "sae",
        }
        for finding in workspace["findings"]
        if finding.get("category") in {"ae", "sae"}
    ]
    payload["deviations"] = [
        {
            "id": finding["id"],
            "subject": finding.get("subject_code", ""),
            "description": finding.get("description", ""),
        }
        for finding in workspace["findings"]
        if finding.get("category") == "deviation"
    ]
    return payload


def _default_legacy_workspace() -> dict[str, Any]:
    workspace = default_workspace()
    if workspace is None:
        raise HTTPException(status_code=404, detail="未找到默认访视")
    return _legacy_workspace(workspace)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/settings/current-role")
def get_current_role() -> dict[str, str]:
    return {"role": get_setting("current_role", "CRA")}


@app.put("/api/settings/current-role")
def put_current_role(payload: CurrentRoleUpdate) -> dict[str, str]:
    """Switch the demo's acting identity.

    The role label alone is not a trustworthy identity (see backend/auth.py):
    switching it also re-points the ``current_member_id`` demo fallback at a
    real ``project_members`` row with that role in the active visit's
    project, so that server-side role checks and the BR-20 submitter/approver
    distinction reflect what the tester actually selected.
    """
    workspace = default_workspace()
    project_id = workspace["visit"]["project_id"] if workspace else ""
    with get_connection() as connection:
        member = connection.execute(
            "SELECT id FROM project_members WHERE project_id = ? AND role = ? AND status = 'active' ORDER BY created_at LIMIT 1",
            (project_id, payload.role),
        ).fetchone()
    if member is not None:
        set_setting("current_member_id", member["id"])
        set_setting("current_actor_kind", "project_member")
    set_setting("current_role", payload.role)
    return {"role": payload.role}


@app.get("/api/ai-adapter")
def get_ai_adapter() -> dict[str, Any]:
    return get_adapter_config()


@app.put("/api/ai-adapter")
def put_ai_adapter(payload: AdapterConfigPatch) -> dict[str, Any]:
    return update_adapter_config(payload.model_dump(exclude_none=True))


# Portfolio and master-data APIs
@app.get("/api/projects")
def get_projects() -> dict[str, list[dict[str, Any]]]:
    return {"items": list_projects()}


@app.post("/api/projects", status_code=201)
def post_project(payload: ProjectCreate) -> dict[str, Any]:
    return create_project(**payload.model_dump())


@app.get("/api/projects/{project_id}")
def get_project_by_id(project_id: str) -> dict[str, Any]:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    return project


@app.patch("/api/projects/{project_id}")
def patch_project(project_id: str, payload: ProjectPatch) -> dict[str, Any]:
    before = get_project(project_id)
    if before is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    project = update_project_record(project_id, payload.model_dump(exclude_none=True))
    if project is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    patch = payload.model_dump(exclude_none=True)
    if "metadata" in patch:
        create_configuration_audit_event(
            entity_type="project",
            entity_id=project_id,
            project_id=project_id,
            action="metadata_updated",
            actor_name="项目管理员",
            detail={"before": before.get("metadata", {}), "after": project.get("metadata", {})},
        )
    return next((item for item in list_projects() if item["id"] == project_id), project)


@app.get("/api/projects/{project_id}/eligibility-assessments")
def get_project_eligibility_assessments(project_id: str) -> dict[str, Any]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    return {
        "items": list_project_eligibility_assessments(project_id),
        "current_approved": get_current_approved_assessment(project_id),
    }


@app.post("/api/projects/{project_id}/eligibility-assessments", status_code=201)
def post_project_eligibility_assessment(
    project_id: str,
    payload: ProjectEligibilityAssessmentCreate,
) -> dict[str, Any]:
    values = payload.model_dump()
    actor_name = values.pop("actor_name")
    try:
        return create_project_eligibility_assessment(
            project_id=project_id,
            actor_name=actor_name,
            payload=values,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/projects/{project_id}/eligibility-assessments/{assessment_id}")
def patch_project_eligibility_assessment(
    project_id: str,
    assessment_id: str,
    payload: ProjectEligibilityAssessmentPatch,
) -> dict[str, Any]:
    values = payload.model_dump(exclude_none=True)
    actor_name = values.pop("actor_name", "项目管理员")
    try:
        return update_project_eligibility_assessment(
            project_id=project_id,
            assessment_id=assessment_id,
            actor_name=actor_name,
            payload=values,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/eligibility-assessments/{assessment_id}/approval")
def post_project_eligibility_assessment_approval(
    project_id: str,
    assessment_id: str,
    payload: ProjectEligibilityAssessmentApproval,
) -> dict[str, Any]:
    try:
        return transition_project_eligibility_assessment(
            project_id=project_id,
            assessment_id=assessment_id,
            **payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/sites")
def get_project_sites(project_id: str) -> dict[str, list[dict[str, Any]]]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    return {"items": list_sites(project_id)}


@app.get("/api/projects/{project_id}/visits")
def get_project_visits(project_id: str, site_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    from .repositories.visits import list_visits

    return {"items": list_visits(project_id, site_id)}


@app.get("/api/projects/{project_id}/import-quality")
def get_project_import_quality_route(project_id: str) -> dict[str, Any]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    return get_project_import_quality(project_id=project_id)


@app.get("/api/projects/{project_id}/history-insights")
def get_project_history_insights_route(
    project_id: str,
    site_id: str | None = None,
    as_of: str = "",
) -> dict[str, Any]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    if site_id:
        site = get_site(site_id)
        if site is None or site.get("project_id") != project_id:
            raise HTTPException(status_code=404, detail="未找到该项目下的中心")
    return get_project_history_insights(project_id, site_id=site_id, as_of=as_of)


@app.get("/api/projects/{project_id}/rule-packs")
def get_project_rule_packs(project_id: str, include_inactive: bool = False) -> dict[str, list[dict[str, Any]]]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    return {"items": list_rule_packs(project_id, include_inactive=include_inactive)}


@app.get("/api/projects/{project_id}/rule-packs/eligibility")
def get_project_rule_pack_eligibility(project_id: str, visit_date: str = "", include_inactive: bool = False) -> dict[str, Any]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    return {
        "visit_date": visit_date.strip(),
        "items": attach_rule_eligibility(list_rule_packs(project_id, include_inactive=include_inactive), visit_date.strip()),
    }


@app.post("/api/projects/{project_id}/rule-packs", status_code=201)
def post_project_rule_pack(project_id: str, payload: RulePackCreate) -> dict[str, Any]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    rule_pack = create_rule_pack(project_id=project_id, **payload.model_dump())
    create_audit_event(
        project_id=project_id,
        visit_id=None,
        entity_type="rule_pack",
        entity_id=rule_pack["id"],
        action="created",
        actor_name="项目管理员",
        detail={"name": rule_pack["name"], "version": rule_pack["version"]},
    )
    return rule_pack


@app.patch("/api/rule-packs/{rule_pack_id}")
def patch_rule_pack(rule_pack_id: str, payload: RulePackPatch) -> dict[str, Any]:
    before = get_rule_pack(rule_pack_id)
    if before is None:
        raise HTTPException(status_code=404, detail="未找到规则包")
    try:
        rule_pack = update_rule_pack(rule_pack_id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    create_audit_event(
        project_id=before["project_id"],
        visit_id=None,
        entity_type="rule_pack",
        entity_id=rule_pack_id,
        action="updated",
        actor_name="项目管理员",
        detail=payload.model_dump(exclude_none=True),
    )
    return rule_pack or {}


@app.post("/api/rule-packs/{rule_pack_id}/approval-actions")
def post_rule_pack_approval_action(rule_pack_id: str, payload: ConfigurationApprovalAction) -> dict[str, Any]:
    try:
        return transition_rule_pack(rule_pack_id=rule_pack_id, **payload.model_dump())["item"]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/members")
def get_project_members(project_id: str, include_inactive: bool = False) -> dict[str, list[dict[str, Any]]]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    return {"items": list_project_members(project_id, include_inactive=include_inactive)}


@app.post("/api/projects/{project_id}/members", status_code=201)
def post_project_member(project_id: str, payload: ProjectMemberCreate) -> dict[str, Any]:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    member = create_project_member(project_id=project_id, **payload.model_dump())
    create_audit_event(
        project_id=project_id,
        visit_id=None,
        entity_type="project_member",
        entity_id=member["id"],
        action="created",
        actor_name="项目管理员",
        detail={"display_name": member["display_name"], "role": member["role"]},
    )
    return member


@app.patch("/api/projects/{project_id}/members/{member_id}")
def patch_project_member(project_id: str, member_id: str, payload: ProjectMemberPatch) -> dict[str, Any]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    member = update_project_member(project_id, member_id, payload.model_dump(exclude_none=True))
    if member is None:
        raise HTTPException(status_code=404, detail="未找到项目成员")
    create_audit_event(
        project_id=project_id,
        visit_id=None,
        entity_type="project_member",
        entity_id=member_id,
        action="updated",
        actor_name="项目管理员",
        detail=payload.model_dump(exclude_none=True),
    )
    return member


@app.get("/api/templates")
def get_templates(include_non_active: bool = False) -> dict[str, list[dict[str, Any]]]:
    return {"items": list_templates(include_non_active=include_non_active)}


@app.get("/api/projects/{project_id}/template-recommendations")
def get_project_template_recommendations(project_id: str, visit_type: str = "") -> dict[str, Any]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    return get_template_recommendations(visit_type)


@app.get("/api/templates/{template_id}")
def get_template_by_id(template_id: str) -> dict[str, Any]:
    detail = build_template_detail(template_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="未找到 Word 模板")
    return detail


@app.post("/api/templates", status_code=201)
async def post_template(
    file: UploadFile = File(...),
    display_name: str = Form(default=""),
    version: str = Form(default="V1.0"),
    actor_name: str = Form(default="项目管理员"),
) -> dict[str, Any]:
    try:
        detail = register_template(
            file_name=file.filename or "monitoring-template.docx",
            content=await file.read(),
            display_name=display_name,
            version=version,
            actor_name=actor_name,
        )
        create_configuration_audit_event(
            entity_type="template",
            entity_id=detail["template"]["id"],
            action="created",
            actor_name=actor_name,
            detail={"name": detail["template"]["name"], "version": detail["template"]["version"]},
        )
        return detail
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/templates/{template_id}/revision-drafts", status_code=201)
def post_template_revision_draft(template_id: str, payload: TemplateRevisionDraftCreate) -> dict[str, Any]:
    try:
        detail = create_template_revision_draft(template_id=template_id, **payload.model_dump())
        revision_of = detail["template"].get("metadata", {}).get("revision_of", {})
        create_configuration_audit_event(
            entity_type="template",
            entity_id=detail["template"]["id"],
            action="revision_draft_created",
            actor_name=payload.actor_name,
            detail={
                "from_template_id": template_id,
                "from_name": revision_of.get("name", ""),
                "from_version": revision_of.get("version", ""),
                "name": detail["template"]["name"],
                "version": detail["template"]["version"],
            },
        )
        return detail
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/templates/{template_id}/document")
async def put_template_document(
    template_id: str,
    file: UploadFile = File(...),
    actor_name: str = Form(default="项目管理员"),
) -> dict[str, Any]:
    try:
        detail = replace_template_revision_document(
            template_id=template_id,
            file_name=file.filename or "monitoring-template.docx",
            content=await file.read(),
            actor_name=actor_name,
        )
        replaced_from = detail["template"].get("metadata", {}).get("document_replaced_from", {})
        create_configuration_audit_event(
            entity_type="template",
            entity_id=template_id,
            action="revision_document_replaced",
            actor_name=actor_name,
            detail={
                "from_file_name": replaced_from.get("source_file_name", ""),
                "from_table_count": replaced_from.get("table_count", 0),
                "to_file_name": detail["template"].get("metadata", {}).get("source_file_name", ""),
                "to_table_count": detail["template"].get("table_count", 0),
            },
        )
        return detail
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/templates/{template_id}/configuration-package")
def get_template_configuration_package(template_id: str) -> Response:
    package = export_template_configuration_package(template_id)
    if package is None:
        raise HTTPException(status_code=404, detail="未找到 Word 模板")
    return Response(
        content=json.dumps(package, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="template-{template_id}-configuration.json"',
        },
    )


@app.post("/api/templates/{template_id}/configuration-package-imports", status_code=201)
async def post_template_configuration_package_import(
    template_id: str,
    file: UploadFile = File(...),
    actor_name: str = Form(default="项目管理员"),
) -> dict[str, Any]:
    try:
        try:
            package = json.loads((await file.read()).decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请上传可读取的 JSON 模板配置包") from exc
        result = import_template_configuration_package(
            template_id=template_id,
            package=package,
            actor_name=actor_name,
        )
        create_configuration_audit_event(
            entity_type="template",
            entity_id=template_id,
            action="configuration_package_imported",
            actor_name=actor_name,
            detail={
                "source_template": result["source_template"],
                "source_mapping_count": result["source_mapping_count"],
                "applied_mapping_count": result["applied_mapping_count"],
                "skipped_mapping_count": result["skipped_mapping_count"],
                "source_field_slot_count": result["source_field_slot_count"],
                "applied_field_slot_count": result["applied_field_slot_count"],
                "skipped_field_slot_count": result["skipped_field_slot_count"],
            },
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/templates/{template_id}/mappings/{mapping_id}")
def patch_template_mapping(
    template_id: str,
    mapping_id: str,
    payload: TemplateMappingPatch,
) -> dict[str, Any]:
    if get_template(template_id) is None:
        raise HTTPException(status_code=404, detail="未找到 Word 模板")
    try:
        mapping = update_template_mapping(template_id, mapping_id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if mapping is None:
        raise HTTPException(status_code=404, detail="未找到模板映射项")
    return build_template_detail(template_id) or {}


@app.post("/api/templates/{template_id}/field-slots", status_code=201)
def post_template_field_slot(template_id: str, payload: TemplateFieldSlotCreate) -> dict[str, Any]:
    if get_template(template_id) is None:
        raise HTTPException(status_code=404, detail="未找到 Word 模板")
    try:
        detail = create_template_field_slot_detail(template_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="未找到 Word 模板")
    return detail


@app.post("/api/templates/{template_id}/field-slot-suggestion-imports", status_code=201)
def post_template_field_slot_suggestion_import(
    template_id: str,
    payload: TemplateFieldSlotSuggestionImportRequest,
) -> dict[str, Any]:
    try:
        result = import_high_confidence_template_field_slot_suggestions(template_id=template_id)
        create_configuration_audit_event(
            entity_type="template",
            entity_id=template_id,
            action="high_confidence_field_slot_suggestions_imported",
            actor_name=payload.actor_name,
            detail={
                "candidate_count": result["candidate_count"],
                "created_count": result["created_count"],
                "adopted_default_count": result["adopted_default_count"],
                "skipped_existing_count": result["skipped_existing_count"],
                "created_labels": result["created_labels"],
                "adopted_default_labels": result["adopted_default_labels"],
                "skipped_existing_labels": result["skipped_existing_labels"],
            },
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/templates/{template_id}/mapping-suggestion-imports", status_code=201)
def post_template_mapping_suggestion_import(
    template_id: str,
    payload: TemplateMappingSuggestionImportRequest,
) -> dict[str, Any]:
    try:
        result = import_high_confidence_template_mapping_suggestions(template_id=template_id)
        create_configuration_audit_event(
            entity_type="template",
            entity_id=template_id,
            action="high_confidence_mapping_suggestions_imported",
            actor_name=payload.actor_name,
            detail={
                "candidate_count": result["candidate_count"],
                "adopted_count": result["adopted_count"],
                "skipped_existing_count": result["skipped_existing_count"],
                "missing_mapping_count": result["missing_mapping_count"],
                "adopted_labels": result["adopted_labels"],
                "skipped_existing_labels": result["skipped_existing_labels"],
                "missing_mapping_labels": result["missing_mapping_labels"],
            },
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/templates/{template_id}/field-slots/{slot_id}")
def patch_template_field_slot(
    template_id: str,
    slot_id: str,
    payload: TemplateFieldSlotPatch,
) -> dict[str, Any]:
    if get_template(template_id) is None:
        raise HTTPException(status_code=404, detail="未找到 Word 模板")
    try:
        detail = update_template_field_slot_detail(template_id, slot_id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="未找到报告填写位")
    return detail


@app.delete("/api/templates/{template_id}/field-slots/{slot_id}")
def delete_template_field_slot(template_id: str, slot_id: str) -> dict[str, Any]:
    if get_template(template_id) is None:
        raise HTTPException(status_code=404, detail="未找到 Word 模板")
    try:
        detail = delete_template_field_slot_detail(template_id, slot_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="未找到报告填写位")
    return detail


@app.patch("/api/templates/{template_id}/visit-type-keywords")
def patch_template_visit_type_keywords(
    template_id: str,
    payload: TemplateVisitTypeKeywordsPatch,
) -> dict[str, Any]:
    try:
        detail = update_template_visit_type_keywords(template_id, payload.visit_type_keywords)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="未找到 Word 模板")
    return detail


@app.patch("/api/templates/{template_id}/completeness-rules")
def patch_template_completeness_rules(
    template_id: str,
    payload: TemplateCompletenessRulesPatch,
) -> dict[str, Any]:
    try:
        detail = update_template_completeness_rules(template_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="未找到 Word 模板")
    return detail


@app.post("/api/templates/{template_id}/approval-actions")
def post_template_approval_action(template_id: str, payload: ConfigurationApprovalAction) -> dict[str, Any]:
    try:
        transition_template(template_id=template_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return build_template_detail(template_id) or {}


@app.post("/api/sites", status_code=201)
def post_site(payload: SiteCreate) -> dict[str, Any]:
    if get_project(payload.project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    return create_site(**payload.model_dump())


@app.patch("/api/sites/{site_id}")
def patch_site(site_id: str, payload: SitePatch) -> dict[str, Any]:
    site = update_site(site_id, payload.model_dump(exclude_none=True))
    if site is None:
        raise HTTPException(status_code=404, detail="未找到中心")
    return site


@app.get("/api/sites/{site_id}/master-versions")
def get_site_master_versions(site_id: str, include_inactive: bool = True) -> dict[str, list[dict[str, Any]]]:
    if get_site(site_id) is None:
        raise HTTPException(status_code=404, detail="未找到中心")
    return {"items": list_site_master_versions(site_id, include_inactive=include_inactive)}


@app.post("/api/sites/{site_id}/master-versions", status_code=201)
def post_site_master_version(site_id: str, payload: SiteMasterVersionCreate) -> dict[str, Any]:
    site = get_site(site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="未找到中心")
    version = create_site_master_version(site_id=site_id, **payload.model_dump())
    create_audit_event(
        project_id=site["project_id"],
        visit_id=None,
        entity_type="site_master_version",
        entity_id=version["id"],
        action="created",
        actor_name=payload.created_by,
        detail={"site_id": site_id, "version_label": version["version_label"], "effective_from": version["effective_from"]},
    )
    return version


@app.patch("/api/site-master-versions/{version_id}")
def patch_site_master_version_record(version_id: str, payload: SiteMasterVersionPatch) -> dict[str, Any]:
    current = get_site_master_version(version_id)
    if current is None:
        raise HTTPException(status_code=404, detail="未找到中心资料版本")
    version = patch_site_master_version(version_id, payload.model_dump(exclude_none=True))
    site = get_site(current["site_id"]) or {}
    create_audit_event(
        project_id=site.get("project_id", ""),
        visit_id=None,
        entity_type="site_master_version",
        entity_id=version_id,
        action="updated",
        actor_name="项目管理员",
        detail={"changed": list(payload.model_dump(exclude_none=True).keys())},
    )
    return version or {}


@app.get("/api/projects/{project_id}/controlled-documents")
def get_project_controlled_documents(
    project_id: str,
    site_id: str = "",
    include_inactive: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    return {"items": list_controlled_documents(project_id, site_id=site_id or None, include_inactive=include_inactive)}


@app.get("/api/projects/{project_id}/sites/{site_id}/master-data-preview")
def get_master_data_preview(project_id: str, site_id: str, visit_date: str) -> dict[str, Any]:
    site = get_site(site_id)
    if get_project(project_id) is None or site is None or site.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail="未找到项目或中心")
    return {"master_data": resolve_frozen_master_data(project_id=project_id, site_id=site_id, visit_date=visit_date)}


@app.post("/api/projects/{project_id}/controlled-documents", status_code=201)
async def post_controlled_document(
    project_id: str,
    document_type: str = Form(...),
    title: str = Form(...),
    site_id: str = Form(default=""),
    version: str = Form(default=""),
    version_date: str = Form(default=""),
    effective_from: str = Form(default=""),
    effective_to: str = Form(default=""),
    source_reference: str = Form(default=""),
    notes: str = Form(default=""),
    actor_name: str = Form(default="项目管理员"),
    file: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目")
    if site_id:
        site = get_site(site_id)
        if site is None or site.get("project_id") != project_id:
            raise HTTPException(status_code=422, detail="受控文件所属中心不在当前项目内")
    file_metadata: dict[str, str] = {}
    if file is not None and file.filename:
        file_metadata = save_controlled_document_file(
            project_id=project_id,
            site_id=site_id,
            file_name=file.filename,
            content=await file.read(),
        )
    try:
        document = create_controlled_document(
            project_id=project_id,
            site_id=site_id or None,
            document_type=document_type,
            title=title,
            version=version,
            version_date=version_date,
            effective_from=effective_from,
            effective_to=effective_to,
            source_reference=source_reference,
            notes=notes,
            created_by=actor_name,
            **file_metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    create_audit_event(
        project_id=project_id,
        visit_id=None,
        entity_type="controlled_document",
        entity_id=document["id"],
        action="created",
        actor_name=actor_name,
        detail={"document_type": document["document_type"], "version": document["version"], "site_id": site_id},
    )
    return document


@app.patch("/api/controlled-documents/{document_id}")
def patch_controlled_document_record(document_id: str, payload: ControlledDocumentPatch) -> dict[str, Any]:
    current = get_controlled_document(document_id)
    if current is None:
        raise HTTPException(status_code=404, detail="未找到受控文件")
    document = patch_controlled_document(document_id, payload.model_dump(exclude_none=True))
    create_audit_event(
        project_id=current["project_id"],
        visit_id=None,
        entity_type="controlled_document",
        entity_id=document_id,
        action="updated",
        actor_name="项目管理员",
        detail={"changed": list(payload.model_dump(exclude_none=True).keys())},
    )
    return document or {}


@app.get("/api/controlled-documents/{document_id}/download")
def download_controlled_document(document_id: str) -> FileResponse:
    document = get_controlled_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="未找到受控文件")
    stored = get_stored_controlled_document(document.get("stored_path", ""))
    if stored is None:
        raise HTTPException(status_code=404, detail="该受控文件未上传源文件")
    return FileResponse(stored, filename=document.get("source_file_name") or stored.name)


@app.get("/api/sites/{site_id}/subject-codes")
def get_site_subject_codes(site_id: str) -> dict[str, list[dict[str, Any]]]:
    if get_site(site_id) is None:
        raise HTTPException(status_code=404, detail="未找到中心")
    return {"items": list_subject_codes(site_id)}


@app.put("/api/sites/{site_id}/subject-codes")
def put_site_subject_codes(site_id: str, payload: SubjectCodesUpdate) -> dict[str, list[dict[str, Any]]]:
    if get_site(site_id) is None:
        raise HTTPException(status_code=404, detail="未找到中心")
    return {"items": save_subject_codes(site_id, payload.subject_codes)}


@app.post("/api/imports/{scope}")
async def post_master_data_import(
    scope: str,
    file: UploadFile = File(...),
    project_id: str = Form(default=""),
    site_id: str = Form(default=""),
    actor_name: str = Form(default="演示管理员"),
) -> dict[str, Any]:
    try:
        return import_master_data(
            scope=scope,
            file_name=file.filename or "upload.xlsx",
            content=await file.read(),
            default_project_id=project_id,
            default_site_id=site_id,
            actor_name=actor_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/imports/{scope}/preview")
async def post_master_data_import_preview(
    scope: str,
    file: UploadFile = File(...),
    project_id: str = Form(default=""),
    site_id: str = Form(default=""),
    actor_name: str = Form(default="项目管理员"),
    source_system: str = Form(default=""),
    source_reference: str = Form(default=""),
    source_exported_at: str = Form(default=""),
    import_profile_id: str = Form(default=""),
    import_profile_name: str = Form(default=""),
    column_mapping_json: str = Form(default="{}"),
) -> dict[str, Any]:
    try:
        try:
            column_mapping = json.loads(column_mapping_json or "{}")
        except ValueError as exc:
            raise ValueError("导入配置的字段预映射不是有效 JSON") from exc
        if not isinstance(column_mapping, dict):
            raise ValueError("导入配置的字段预映射格式无效")
        return preview_master_data_import(
            scope=scope,
            file_name=file.filename or "upload.xlsx",
            content=await file.read(),
            default_project_id=project_id,
            default_site_id=site_id,
            actor_name=actor_name,
            source_system=source_system,
            source_reference=source_reference,
            source_exported_at=source_exported_at,
            import_profile_id=import_profile_id,
            import_profile_name=import_profile_name,
            column_mapping=column_mapping,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/import-batches/{batch_id}")
def get_master_data_import_batch(batch_id: str) -> dict[str, Any]:
    batch = get_import_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="未找到导入预检批次")
    return batch


@app.get("/api/import-batches/{batch_id}/error-report")
def download_master_data_import_error_report(batch_id: str) -> Response:
    try:
        content, filename = build_import_error_csv(batch_id=batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/import-batches/{batch_id}/commit")
def commit_master_data_import_batch(batch_id: str, payload: ImportBatchCommit) -> dict[str, Any]:
    try:
        return commit_master_data_import(batch_id=batch_id, actor_name=payload.actor_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# Visit workspace APIs
@app.post("/api/visits", status_code=201)
def post_visit(payload: VisitCreate) -> dict[str, Any]:
    if get_project(payload.project_id) is None or get_site(payload.site_id) is None:
        raise HTTPException(status_code=404, detail="未找到项目或中心")
    if payload.template_id and get_template(payload.template_id) is None:
        raise HTTPException(status_code=404, detail="未找到 Word 模板")
    try:
        visit = create_visit(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    set_setting("current_visit_id", visit["id"])
    return _workspace_or_404(visit["id"])


@app.get("/api/visits/{visit_id}")
def get_visit_by_id(visit_id: str) -> dict[str, Any]:
    visit = get_visit(visit_id)
    if visit is None:
        raise HTTPException(status_code=404, detail="未找到访视")
    return visit


@app.patch("/api/visits/{visit_id}")
def patch_visit(visit_id: str, payload: VisitPatch) -> dict[str, Any]:
    visit = update_visit(visit_id, payload.model_dump(exclude_none=True))
    if visit is None:
        raise HTTPException(status_code=404, detail="未找到访视")
    return _workspace_or_404(visit_id)


@app.post("/api/visits/{visit_id}/cancel")
def post_visit_cancel(visit_id: str, payload: VisitCancellationRequest) -> dict[str, Any]:
    try:
        visit = cancel_draft_visit(
            visit_id=visit_id,
            reason=payload.reason,
            actor_name=payload.actor_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"visit": visit}


@app.get("/api/visits/{visit_id}/template-switch-preview")
def get_template_switch_preview(visit_id: str, template_id: str) -> dict[str, Any]:
    try:
        return preview_template_switch(visit_id=visit_id, target_template_id=template_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/visits/{visit_id}/template-switch")
def post_template_switch(visit_id: str, payload: TemplateSwitchRequest) -> dict[str, Any]:
    try:
        result = switch_template(
            visit_id=visit_id,
            target_template_id=payload.target_template_id,
            actor_name=payload.actor_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}


@app.post("/api/visits/{visit_id}/template-switches/{switch_id}/rollback")
def post_template_switch_rollback(
    visit_id: str,
    switch_id: str,
    payload: TemplateSwitchRollbackRequest,
) -> dict[str, Any]:
    try:
        result = rollback_template_switch(visit_id=visit_id, switch_id=switch_id, actor_name=payload.actor_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}


@app.get("/api/visits/{visit_id}/date-reassessment-preview")
def get_visit_date_reassessment_preview(visit_id: str, visit_date: str, rule_pack_id: str = "") -> dict[str, Any]:
    try:
        return preview_visit_date_reassessment(
            visit_id=visit_id,
            visit_date=visit_date,
            target_rule_pack_id=rule_pack_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/visits/{visit_id}/date-reassess")
def post_visit_date_reassessment(visit_id: str, payload: VisitDateReassessmentRequest) -> dict[str, Any]:
    try:
        result = apply_visit_date_reassessment(
            visit_id=visit_id,
            visit_date=payload.visit_date,
            target_rule_pack_id=payload.rule_pack_id,
            actor_name=payload.actor_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}


@app.get("/api/visits/{visit_id}/master-data-refresh-preview")
def get_visit_master_data_refresh_preview(visit_id: str) -> dict[str, Any]:
    try:
        return preview_master_data_refresh(visit_id=visit_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/visits/{visit_id}/master-data-refresh")
def post_visit_master_data_refresh(visit_id: str, payload: MasterDataRefreshRequest) -> dict[str, Any]:
    try:
        result = apply_master_data_refresh(
            visit_id=visit_id,
            actor_name=payload.actor_name,
            selected_targets=payload.selected_targets,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}


@app.post("/api/visits/{visit_id}/master-data-refresh/rollback")
def post_visit_master_data_refresh_rollback(visit_id: str, payload: MasterDataRefreshRollbackRequest) -> dict[str, Any]:
    try:
        result = rollback_master_data_refresh(
            visit_id=visit_id,
            actor_name=payload.actor_name,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}


@app.get("/api/visits/{visit_id}/workspace")
def get_visit_workspace(visit_id: str) -> dict[str, Any]:
    set_setting("current_visit_id", visit_id)
    return _workspace_or_404(visit_id)


@app.get("/api/visits/{visit_id}/clarifications")
def get_visit_clarifications(visit_id: str) -> dict[str, list[dict[str, Any]]]:
    _workspace_or_404(visit_id)
    return {"items": list_clarification_items(visit_id)}


@app.post("/api/visits/{visit_id}/clarifications/refresh")
def post_visit_clarifications_refresh(
    visit_id: str,
    payload: ClarificationRefreshRequest,
) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        items = refresh_clarification_items(visit_id=visit_id, actor_name=payload.actor_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"items": items, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}


@app.post("/api/visits/{visit_id}/clarifications/{item_id}/response")
def post_visit_clarification_response(
    visit_id: str,
    item_id: str,
    payload: ClarificationResponseRequest,
) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        item = resolve_clarification_item(
            visit_id=visit_id,
            item_id=item_id,
            action=payload.action,
            answer_text=payload.answer_text,
            selected_candidate_id=payload.selected_candidate_id,
            actor_name=payload.actor_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"item": item, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}


@app.get("/api/visits/{visit_id}/tasks")
def get_visit_tasks(visit_id: str) -> dict[str, list[dict[str, Any]]]:
    _workspace_or_404(visit_id)
    return {"items": list_tasks(visit_id)}


@app.patch("/api/visits/{visit_id}/tasks/{task_id}")
def patch_visit_task(visit_id: str, task_id: str, payload: TaskPatch) -> dict[str, Any]:
    task = next((item for item in list_tasks(visit_id) if item["id"] == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="未找到访视任务")
    try:
        updated = update_task(task_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    workspace = _workspace_or_404(visit_id)
    create_audit_event(
        project_id=workspace["visit"]["project_id"],
        visit_id=visit_id,
        entity_type="visit_task",
        entity_id=task_id,
        action="execution_updated",
        actor_name=payload.completed_by,
        detail={
            "before": {key: task.get(key, "") for key in ("status", "evidence", "execution_date", "checked_scope", "rationale", "completed_by")},
            "after": {key: (updated or {}).get(key, "") for key in ("status", "evidence", "execution_date", "checked_scope", "rationale", "completed_by")},
        },
    )
    return _workspace_or_404(visit_id)


@app.post("/api/visits/{visit_id}/tasks/bulk-update")
def post_visit_task_bulk_update(visit_id: str, payload: TaskBulkPatch) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        updated = bulk_complete_visit_tasks(
            visit_id=visit_id,
            task_ids=payload.task_ids,
            status=payload.status,
            evidence=payload.evidence,
            actor_name=payload.actor_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"items": updated, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}


@app.post("/api/visits/{visit_id}/records", status_code=201)
def post_visit_record(visit_id: str, payload: RecordCreate, background_tasks: BackgroundTasks) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        result = add_work_record(
            visit_id=visit_id,
            text=payload.text,
            created_by=payload.created_by,
            record_kind=payload.record_kind,
            linked_task_id=payload.linked_task_id,
            recorded_at=payload.recorded_at,
            client_created_at=payload.client_created_at,
            client_timezone=payload.client_timezone,
            tags=payload.tags,
            client_idempotency_key=payload.client_idempotency_key,
            defer_processing=True,
        )
        if not result.get("idempotent_reuse"):
            record = result["record"]
            background_tasks.add_task(
                process_saved_work_record,
                visit_id=visit_id,
                record_id=str(record["id"]),
                source=str(record["text"]),
                actor_name=str(record["created_by"]),
                record_kind=str(record["record_kind"]),
                linked_task_id=str(record.get("linked_task_id") or ""),
            )
        return {**result, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/visits/{visit_id}/records/duplicate-preview")
def preview_visit_record_duplicates(visit_id: str, payload: RecordDuplicatePreview) -> dict[str, list[dict[str, Any]]]:
    _workspace_or_404(visit_id)
    return {"items": find_duplicate_work_records(visit_id=visit_id, text=payload.text)}


@app.post("/api/visits/{visit_id}/records/{record_id}/corrections", status_code=201)
def post_visit_record_correction(visit_id: str, record_id: str, payload: RecordCorrectionCreate) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        result = correct_work_record(
            visit_id=visit_id,
            corrected_record_id=record_id,
            text=payload.text,
            correction_reason=payload.correction_reason,
            created_by=payload.created_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}


@app.post("/api/visits/{visit_id}/records/{record_id}/void")
def post_visit_record_void(visit_id: str, record_id: str, payload: RecordVoidRequest) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        result = void_work_record(
            visit_id=visit_id,
            record_id=record_id,
            reason=payload.reason,
            actor_name=payload.actor_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}


@app.get("/api/visits/{visit_id}/offline-drafts")
def get_visit_offline_drafts(visit_id: str) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    return {
        "items": list_offline_drafts(visit_id),
        "conflicts": list_sync_conflicts(visit_id),
        "sync_token": get_visit_sync_token(visit_id),
    }


@app.post("/api/visits/{visit_id}/offline-drafts/sync", status_code=201)
def post_visit_offline_draft_sync(visit_id: str, payload: OfflineDraftSync) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        return sync_offline_draft(visit_id=visit_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/visits/{visit_id}/sync-conflicts/{conflict_id}/resolve")
def post_visit_sync_conflict_resolution(visit_id: str, conflict_id: str, payload: SyncConflictResolve) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        return resolve_sync_conflict(visit_id=visit_id, conflict_id=conflict_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/visits/{visit_id}/operations")
def get_visit_operations_queue(visit_id: str) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    return get_visit_operations(visit_id)


@app.post("/api/visits/{visit_id}/escalations", status_code=201)
def post_visit_escalation(visit_id: str, payload: EscalationCreate) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        return create_escalation(visit_id=visit_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/visits/{visit_id}/escalations/{escalation_id}/disposition")
def post_visit_escalation_disposition(
    visit_id: str,
    escalation_id: str,
    payload: EscalationDisposition,
) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        return dispose_escalation(visit_id=visit_id, escalation_id=escalation_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/visits/{visit_id}/administrator-handovers", status_code=201)
def post_administrator_visit_handover(visit_id: str, payload: AdministratorHandoverCreate) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        return create_administrator_visit_handover(visit_id=visit_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/visits/{visit_id}/handovers/{handover_id}/recipient-confirmation")
def post_administrator_handover_recipient_confirmation(
    visit_id: str,
    handover_id: str,
    payload: AdministratorHandoverAcknowledgement,
) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        return acknowledge_administrator_visit_handover(
            visit_id=visit_id,
            handover_id=handover_id,
            **payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/visits/{visit_id}/suggestions/{suggestion_id}/decision")
def post_visit_suggestion_decision(visit_id: str, suggestion_id: str, payload: SuggestionDecision) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    return decide_suggestion(
        visit_id=visit_id,
        suggestion_id=suggestion_id,
        decision=payload.decision,
        actor_name=payload.actor_name,
        edited_text=payload.edited_text,
        decision_reason=payload.decision_reason,
    )


@app.post("/api/visits/{visit_id}/suggestions/{suggestion_id}/target-assignment")
def post_visit_suggestion_target_assignment(
    visit_id: str,
    suggestion_id: str,
    payload: SuggestionTargetAssignment,
) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        item = assign_suggestion_target(
            visit_id=visit_id,
            suggestion_id=suggestion_id,
            target_task_id=payload.target_task_id,
            actor_name=payload.actor_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"item": item, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}


@app.post("/api/visits/{visit_id}/suggestions/batch-decision")
def post_visit_suggestion_batch_decision(visit_id: str, payload: SuggestionBatchDecision) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        result = decide_suggestions_batch(
            visit_id=visit_id,
            suggestion_ids=payload.suggestion_ids,
            decision=payload.decision,
            actor_name=payload.actor_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "workspace": _legacy_workspace(_workspace_or_404(visit_id))}


@app.get("/api/visits/{visit_id}/language-suggestions")
def get_visit_language_suggestions(visit_id: str) -> dict[str, list[dict[str, Any]]]:
    _workspace_or_404(visit_id)
    return {"items": list_language_suggestions(visit_id)}


@app.post("/api/visits/{visit_id}/language-suggestions/generate", status_code=201)
def post_visit_language_suggestions(visit_id: str, payload: ReportGenerateRequest) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        created = generate_language_suggestions(visit_id=visit_id, actor_name=payload.created_by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"items": created, "workspace": _workspace_or_404(visit_id)}


@app.post("/api/visits/{visit_id}/language-suggestions/{suggestion_id}/decision")
def post_visit_language_suggestion_decision(
    visit_id: str,
    suggestion_id: str,
    payload: LanguageSuggestionDecision,
) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        item = decide_language_suggestion(
            visit_id=visit_id,
            suggestion_id=suggestion_id,
            decision=payload.decision,
            actor_name=payload.actor_name,
            edited_text=payload.edited_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"item": item, "workspace": _workspace_or_404(visit_id)}


@app.post("/api/visits/{visit_id}/language-suggestions/{suggestion_id}/revoke")
def post_visit_language_suggestion_revoke(
    visit_id: str,
    suggestion_id: str,
    payload: LanguageSuggestionRevocationRequest,
) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        item = revoke_language_suggestion(
            visit_id=visit_id,
            suggestion_id=suggestion_id,
            actor_name=payload.actor_name,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"item": item, "workspace": _workspace_or_404(visit_id)}


@app.get("/api/visits/{visit_id}/evidence-chain")
def get_visit_evidence_chain(visit_id: str) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    return build_evidence_chain(visit_id)


@app.get("/api/visits/{visit_id}/audit-export")
def get_visit_audit_export(visit_id: str):
    _workspace_or_404(visit_id)
    content, filename = export_audit_csv(visit_id=visit_id)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/visits/{visit_id}/action-items", status_code=201)
def post_action_item(visit_id: str, payload: ActionItemCreate) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    return create_action_item(visit_id=visit_id, **payload.model_dump())


@app.patch("/api/visits/{visit_id}/action-items/{action_item_id}")
def patch_action_item(visit_id: str, action_item_id: str, payload: ActionItemPatch) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    patch = payload.model_dump(exclude_none=True)
    actor_name = patch.pop("actor_name", "演示 CRA")
    return update_action_item(visit_id=visit_id, action_item_id=action_item_id, patch=patch, actor_name=actor_name)


@app.put("/api/visits/{visit_id}/action-items/{action_item_id}/findings")
def put_action_item_finding_links(
    visit_id: str,
    action_item_id: str,
    payload: ActionItemFindingLinksUpdate,
) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        return update_action_item_finding_links(
            visit_id=visit_id,
            action_item_id=action_item_id,
            finding_ids=payload.finding_ids,
            actor_name=payload.actor_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/visits/{visit_id}/historical-actions/{source_action_item_id}/follow-up", status_code=201)
def post_historical_action_follow_up(
    visit_id: str,
    source_action_item_id: str,
    payload: HistoricalActionFollowUpCreate,
) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        return create_historical_action_follow_up(
            visit_id=visit_id,
            source_action_item_id=source_action_item_id,
            actor_name=payload.actor_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/visits/{visit_id}/action-items")
def get_action_items(visit_id: str) -> dict[str, list[dict[str, Any]]]:
    _workspace_or_404(visit_id)
    return {"items": list_action_items(visit_id)}


@app.get("/api/visits/{visit_id}/attachments")
def get_visit_attachments(visit_id: str, action_item_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    _workspace_or_404(visit_id)
    return {"items": list_visit_attachments(visit_id, action_item_id)}


@app.post("/api/visits/{visit_id}/attachments", status_code=201)
async def post_visit_attachment(
    visit_id: str,
    file: UploadFile = File(...),
    action_item_id: str = Form(default=""),
    description: str = Form(default=""),
    actor_name: str = Form(default="演示 CRA"),
) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        return save_attachment(
            visit_id=visit_id,
            file_name=file.filename or "evidence.bin",
            content=await file.read(),
            description=description,
            created_by=actor_name,
            action_item_id=action_item_id or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/attachments/{attachment_id}/download")
def get_attachment_download(attachment_id: str):
    attachment = get_stored_attachment(attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="未找到附件")
    stored_file = Path(attachment["stored_path"])
    if not stored_file.exists():
        raise HTTPException(status_code=404, detail="未找到已留存的附件文件")
    return FileResponse(path=stored_file, filename=attachment["file_name"])


@app.get("/api/visits/{visit_id}/revisions")
def get_visit_revisions(visit_id: str) -> dict[str, list[dict[str, Any]]]:
    _workspace_or_404(visit_id)
    return {"items": list_revisions(visit_id)}


@app.get("/api/visits/{visit_id}/report-readiness")
def get_visit_report_readiness(visit_id: str) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        return evaluate_report_readiness(visit_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/visits/{visit_id}/revisions/generate", status_code=201)
def post_visit_revision(visit_id: str, payload: ReportGenerateRequest) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        return generate_revision(visit_id=visit_id, created_by=payload.created_by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/revisions/{revision_id}/download")
def get_revision_download(revision_id: str):
    revision = _revision_or_404(revision_id)
    report_file = Path(revision["file_path"])
    if not report_file.exists():
        raise HTTPException(status_code=404, detail="未找到已生成的 Word 文件")
    return FileResponse(
        path=report_file,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=revision["file_name"],
    )


@app.get("/api/revisions/{revision_id}/handover-package")
def get_revision_handover_package(revision_id: str):
    _revision_or_404(revision_id)
    try:
        content, filename = build_handover_package(revision_id=revision_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/revisions/{revision_id}/submit")
def post_revision_submit(revision_id: str, payload: SubmitRequest, actor: Actor = Depends(get_actor)) -> dict[str, Any]:
    _revision_or_404(revision_id)
    try:
        return submit_revision(
            revision_id=revision_id,
            actor_name=actor.display_name or payload.cra_name,
            actor_member_id=actor.member_id,
            confirmed=payload.confirmed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/revisions/{revision_id}/withdraw")
def post_revision_withdraw(revision_id: str, payload: RevisionWithdrawRequest) -> dict[str, Any]:
    revision = _revision_or_404(revision_id)
    try:
        result = withdraw_revision(
            revision_id=revision_id,
            actor_name=payload.cra_name,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "workspace": _legacy_workspace(_workspace_or_404(revision["visit_id"]))}


@app.post("/api/revisions/{revision_id}/void")
def post_revision_void(revision_id: str, payload: RevisionVoidRequest) -> dict[str, Any]:
    revision = _revision_or_404(revision_id)
    try:
        result = void_approved_revision(
            revision_id=revision_id,
            actor_name=payload.actor_name,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "workspace": _legacy_workspace(_workspace_or_404(revision["visit_id"]))}


@app.post("/api/revisions/{revision_id}/review-start")
def post_revision_review_start(
    revision_id: str, payload: ReviewStartRequest, actor: Actor = Depends(get_actor)
) -> dict[str, Any]:
    revision = _revision_or_404(revision_id)
    try:
        updated = start_revision_review(
            revision_id=revision_id,
            reviewer_name=actor.display_name or payload.reviewer_name,
            reviewer_member_id=actor.member_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"revision": updated, "workspace": _legacy_workspace(_workspace_or_404(revision["visit_id"]))}


@app.post("/api/revisions/{revision_id}/reviews", status_code=201)
def post_revision_review(revision_id: str, payload: ReviewCreate, actor: Actor = Depends(get_actor)) -> dict[str, Any]:
    _revision_or_404(revision_id)
    try:
        return review_revision(
            revision_id=revision_id,
            action=payload.action,
            message=payload.message,
            reviewer_name=actor.display_name or payload.reviewer_name,
            reviewer_member_id=actor.member_id,
            target_key=payload.target_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/revisions/{revision_id}/specialist-comments", status_code=201)
def post_revision_specialist_comment(revision_id: str, payload: SpecialistReviewCreate) -> dict[str, Any]:
    _revision_or_404(revision_id)
    try:
        return create_specialist_review_comment(
            revision_id=revision_id,
            action=payload.action,
            message=payload.message,
            reviewer_name=payload.reviewer_name,
            target_key=payload.target_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/visits/{visit_id}/review-comments/{comment_id}/resolve")
def post_review_comment_resolution(
    visit_id: str,
    comment_id: str,
    payload: ReviewCommentResolve,
) -> dict[str, Any]:
    _workspace_or_404(visit_id)
    try:
        item = resolve_review_comment(
            visit_id=visit_id,
            comment_id=comment_id,
            resolution=payload.resolution,
            note=payload.note,
            actor_name=payload.actor_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"item": item, "workspace": _workspace_or_404(visit_id)}


# Compatibility APIs for the existing four-page demo. They now operate on the SQLite visit workspace.
@app.get("/api/state")
def get_state(visit_id: str | None = None) -> dict[str, Any]:
    if visit_id:
        return _legacy_workspace(_workspace_or_404(visit_id))
    return _default_legacy_workspace()


@app.put("/api/project")
def put_project(payload: ProjectUpdate) -> dict[str, Any]:
    workspace = default_workspace()
    if workspace is None:
        raise HTTPException(status_code=404, detail="未找到默认访视")
    project = workspace["project"]
    site = workspace["site"]
    metadata = {**get_project(workspace["visit"]["project_id"]).get("metadata", {}), "approval_number": payload.project.get("approval_number", project.get("approval_number", "")), "sop_version": payload.project.get("sop_version", project.get("sop_version", ""))}
    update_project_record(
        workspace["visit"]["project_id"],
        {
            "name": payload.project.get("study_name", project.get("study_name", "")),
            "code": payload.project.get("study_id", project.get("study_id", "")),
            "sponsor": payload.project.get("sponsor", project.get("sponsor", "")),
            "metadata": metadata,
        },
    )
    update_site(
        workspace["visit"]["site_id"],
        {
            "name": payload.project.get("site_name", site.get("site_name", "")),
            "pi_name": payload.project.get("pi_name", site.get("pi_name", "")),
            "protocol_version": payload.project.get("protocol_version", site.get("protocol_version", "")),
            "icf_version": payload.project.get("icf_version", site.get("icf_version", "")),
            "ethics_date": payload.project.get("ethics_date", site.get("ethics_date", "")),
        },
    )
    update_visit(workspace["visit"]["id"], {**payload.visit, "recruitment": payload.recruitment})
    return _default_legacy_workspace()


@app.post("/api/records")
def post_record(payload: RecordCreate) -> dict[str, Any]:
    workspace = default_workspace()
    if workspace is None:
        raise HTTPException(status_code=404, detail="未找到默认访视")
    result = add_work_record(
        visit_id=workspace["visit"]["id"],
        text=payload.text,
        created_by=payload.created_by,
        record_kind=payload.record_kind,
        linked_task_id=payload.linked_task_id,
        recorded_at=payload.recorded_at,
        client_created_at=payload.client_created_at,
        client_timezone=payload.client_timezone,
        tags=payload.tags,
        client_idempotency_key=payload.client_idempotency_key,
    )
    return {**result, "state": _default_legacy_workspace()}


@app.post("/api/suggestions/{suggestion_id}/decision")
def post_suggestion_decision(suggestion_id: str, payload: SuggestionDecision) -> dict[str, Any]:
    workspace = default_workspace()
    if workspace is None:
        raise HTTPException(status_code=404, detail="未找到默认访视")
    decide_suggestion(
        visit_id=workspace["visit"]["id"],
        suggestion_id=suggestion_id,
        decision=payload.decision,
        actor_name=payload.actor_name,
        edited_text=payload.edited_text,
        decision_reason=payload.decision_reason,
    )
    return _default_legacy_workspace()


@app.post("/api/report/generate")
def post_report_generate():
    workspace = default_workspace()
    if workspace is None:
        raise HTTPException(status_code=404, detail="未找到默认访视")
    try:
        revision = generate_revision(visit_id=workspace["visit"]["id"], created_by=workspace["visit"].get("cra_name", "演示 CRA"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    report_file = Path(revision["file_path"])
    return FileResponse(
        path=report_file,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=revision["file_name"],
    )


@app.post("/api/report/submit")
def post_report_submit(payload: SubmitRequest) -> dict[str, Any]:
    workspace = default_workspace()
    if workspace is None:
        raise HTTPException(status_code=404, detail="未找到默认访视")
    revisions = list_revisions(workspace["visit"]["id"])
    if not revisions:
        raise HTTPException(status_code=409, detail="请先生成该访视的 Word 报告")
    try:
        submit_revision(revision_id=revisions[0]["id"], actor_name=payload.cra_name, confirmed=payload.confirmed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    update_visit(workspace["visit"]["id"], {"cra_name": payload.cra_name})
    return _default_legacy_workspace()


@app.post("/api/reviews")
def post_review(payload: ReviewCreate) -> dict[str, Any]:
    workspace = default_workspace()
    if workspace is None:
        raise HTTPException(status_code=404, detail="未找到默认访视")
    revisions = list_revisions(workspace["visit"]["id"])
    if not revisions:
        raise HTTPException(status_code=409, detail="请先生成并提交报告")
    review_revision(
        revision_id=revisions[0]["id"],
        action=payload.action,
        message=payload.message,
        reviewer_name=payload.reviewer_name,
        target_key=payload.target_key,
    )
    return _default_legacy_workspace()


@app.post("/api/reset")
def reset_demo() -> dict[str, Any]:
    reset_database()
    return _default_legacy_workspace()
