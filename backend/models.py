from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProjectUpdate(BaseModel):
    project: dict[str, str] = Field(default_factory=dict)
    visit: dict[str, str] = Field(default_factory=dict)
    recruitment: dict[str, int] = Field(default_factory=dict)


class RecordCreate(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    created_by: str = Field(default="演示 CRA", max_length=80)
    record_kind: Literal["monitoring_note", "center_explanation"] = "monitoring_note"
    linked_task_id: str = Field(default="", max_length=120)
    recorded_at: str = Field(default="", max_length=40)
    client_created_at: str = Field(default="", max_length=64)
    client_timezone: str = Field(default="", max_length=96)
    tags: list[str] = Field(default_factory=list)
    client_idempotency_key: str = Field(default="", max_length=120)


class RecordDuplicatePreview(BaseModel):
    text: str = Field(min_length=1, max_length=3000)


class RecordCorrectionCreate(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    correction_reason: str = Field(min_length=1, max_length=1000)
    created_by: str = Field(default="演示 CRA", max_length=80)


class RecordVoidRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    actor_name: str = Field(default="演示 CRA", max_length=80)


class SuggestionDecision(BaseModel):
    decision: Literal["accepted", "edited", "rejected"]
    edited_text: str | None = Field(default=None, max_length=3000)
    decision_reason: str = Field(default="", max_length=1000)
    actor_name: str = Field(default="演示 CRA", max_length=80)


class SuggestionTargetAssignment(BaseModel):
    target_task_id: str = Field(min_length=1, max_length=120)
    actor_name: str = Field(default="演示 CRA", max_length=80)


class SuggestionBatchDecision(BaseModel):
    suggestion_ids: list[str] = Field(default_factory=list)
    decision: Literal["accepted", "rejected"]
    actor_name: str = Field(default="演示 CRA", max_length=80)


class ReviewCreate(BaseModel):
    action: Literal["comment", "returned", "approved"]
    message: str = Field(default="", max_length=2000)
    reviewer_name: str = Field(default="PM/LM 审核人", max_length=80)
    target_key: str = Field(default="", max_length=120)


class SpecialistReviewCreate(BaseModel):
    action: Literal["specialist_comment", "specialist_concurrence"]
    message: str = Field(default="", max_length=2000)
    reviewer_name: str = Field(default="医学监察／数据管理", max_length=80)
    target_key: str = Field(default="", max_length=120)


class SubmitRequest(BaseModel):
    cra_name: str = Field(default="演示 CRA", max_length=80)
    confirmed: bool = False


class RevisionWithdrawRequest(BaseModel):
    cra_name: str = Field(default="演示 CRA", max_length=80)
    reason: str = Field(min_length=1, max_length=3000)


class RevisionVoidRequest(BaseModel):
    actor_name: str = Field(default="QA/临床运营审批人", min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=3000)


class ReviewStartRequest(BaseModel):
    reviewer_name: str = Field(default="PM/LM 审核人", min_length=1, max_length=80)


class ActionItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=3000)
    owner: str = Field(default="CRA / 中心待确认", max_length=120)
    due_date: str = Field(default="", max_length=30)
    finding_id: str | None = None
    finding_ids: list[str] = Field(default_factory=list)
    actor_name: str = Field(default="演示 CRA", max_length=80)


class ActionItemPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=3000)
    owner: str | None = Field(default=None, max_length=120)
    due_date: str | None = Field(default=None, max_length=30)
    status: Literal["open", "in_progress", "closed"] | None = None
    status_change_note: str | None = Field(default=None, max_length=3000)
    closure_note: str | None = Field(default=None, max_length=3000)
    actor_name: str = Field(default="演示 CRA", max_length=80)


class ActionItemFindingLinksUpdate(BaseModel):
    finding_ids: list[str] = Field(default_factory=list)
    actor_name: str = Field(default="演示 CRA", max_length=80)


class HistoricalActionFollowUpCreate(BaseModel):
    actor_name: str = Field(default="演示 CRA", max_length=80)


class ProjectCreate(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    sponsor: str = Field(default="", max_length=200)
    metadata: dict[str, object] = Field(default_factory=dict)


class ProjectPatch(BaseModel):
    code: str | None = Field(default=None, max_length=80)
    name: str | None = Field(default=None, max_length=200)
    sponsor: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=40)
    metadata: dict[str, object] | None = None


class ProjectEligibilityAssessmentCreate(BaseModel):
    assessment_scope: str = Field(default="IMV_DOCX", max_length=80)
    blinding_mode: Literal["open_label", "blinded_with_separation"] = "open_label"
    processes_nonblind_data: bool = False
    contains_direct_identifiers: bool = False
    requires_full_blind_separation: bool = False
    uses_editable_docx_only: bool = True
    requires_ctms_etmf_integration: bool = False
    assessment_note: str = Field(default="", max_length=3000)
    effective_from: str = Field(default="", max_length=40)
    effective_to: str = Field(default="", max_length=40)
    actor_name: str = Field(default="项目管理员", min_length=1, max_length=120)


class ProjectEligibilityAssessmentPatch(BaseModel):
    assessment_scope: str | None = Field(default=None, max_length=80)
    blinding_mode: Literal["open_label", "blinded_with_separation"] | None = None
    processes_nonblind_data: bool | None = None
    contains_direct_identifiers: bool | None = None
    requires_full_blind_separation: bool | None = None
    uses_editable_docx_only: bool | None = None
    requires_ctms_etmf_integration: bool | None = None
    assessment_note: str | None = Field(default=None, max_length=3000)
    effective_from: str | None = Field(default=None, max_length=40)
    effective_to: str | None = Field(default=None, max_length=40)
    actor_name: str = Field(default="项目管理员", min_length=1, max_length=120)


class ProjectEligibilityAssessmentApproval(BaseModel):
    action: Literal["submit", "approve", "reject", "withdraw"]
    actor_name: str = Field(default="演示审批人", min_length=1, max_length=120)
    note: str = Field(default="", max_length=3000)


class SiteCreate(BaseModel):
    project_id: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    pi_name: str = Field(default="", max_length=120)
    ethics_date: str = Field(default="", max_length=80)
    protocol_version: str = Field(default="", max_length=120)
    icf_version: str = Field(default="", max_length=120)


class SitePatch(BaseModel):
    code: str | None = Field(default=None, max_length=80)
    name: str | None = Field(default=None, max_length=200)
    pi_name: str | None = Field(default=None, max_length=120)
    ethics_date: str | None = Field(default=None, max_length=80)
    protocol_version: str | None = Field(default=None, max_length=120)
    icf_version: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, max_length=40)


class SiteMasterVersionCreate(BaseModel):
    version_label: str = Field(min_length=1, max_length=160)
    pi_name: str = Field(default="", max_length=120)
    site_address: str = Field(default="", max_length=500)
    site_team: str = Field(default="", max_length=500)
    key_roles: dict[str, str] = Field(default_factory=dict)
    effective_from: str = Field(default="", max_length=40)
    effective_to: str = Field(default="", max_length=40)
    created_by: str = Field(default="项目管理员", max_length=120)


class SiteMasterVersionPatch(BaseModel):
    version_label: str | None = Field(default=None, max_length=160)
    pi_name: str | None = Field(default=None, max_length=120)
    site_address: str | None = Field(default=None, max_length=500)
    site_team: str | None = Field(default=None, max_length=500)
    key_roles: dict[str, str] | None = None
    effective_from: str | None = Field(default=None, max_length=40)
    effective_to: str | None = Field(default=None, max_length=40)
    status: Literal["active", "superseded", "inactive"] | None = None


class ControlledDocumentPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    version: str | None = Field(default=None, max_length=120)
    version_date: str | None = Field(default=None, max_length=40)
    effective_from: str | None = Field(default=None, max_length=40)
    effective_to: str | None = Field(default=None, max_length=40)
    status: Literal["active", "superseded", "inactive"] | None = None
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=3000)


class ImportBatchCommit(BaseModel):
    actor_name: str = Field(default="项目管理员", max_length=120)


class VisitCreate(BaseModel):
    project_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=80)
    visit_type: str = Field(min_length=1, max_length=120)
    visit_date: str = Field(min_length=1, max_length=40)
    activity_start_date: str = Field(default="", max_length=40)
    visit_method: str = Field(default="现场", max_length=40)
    visit_location: str = Field(default="", max_length=300)
    contact_persons: str = Field(default="", max_length=300)
    report_date: str | None = Field(default=None, max_length=40)
    site_team: str = Field(default="", max_length=300)
    monitoring_team: str = Field(default="", max_length=300)
    next_visit: str = Field(default="", max_length=120)
    cra_name: str = Field(default="演示 CRA", max_length=80)
    template_id: str | None = None
    rule_pack_id: str | None = None


class VisitPatch(BaseModel):
    code: str | None = Field(default=None, max_length=80)
    visit_type: str | None = Field(default=None, max_length=120)
    visit_date: str | None = Field(default=None, max_length=40)
    activity_start_date: str | None = Field(default=None, max_length=40)
    visit_method: str | None = Field(default=None, max_length=40)
    visit_location: str | None = Field(default=None, max_length=300)
    contact_persons: str | None = Field(default=None, max_length=300)
    report_date: str | None = Field(default=None, max_length=40)
    site_team: str | None = Field(default=None, max_length=300)
    monitoring_team: str | None = Field(default=None, max_length=300)
    next_visit: str | None = Field(default=None, max_length=120)
    cra_name: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=40)
    recruitment: dict[str, int] | None = None


class VisitCancellationRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=3000)
    actor_name: str = Field(default="演示 CRA", min_length=1, max_length=80)


class TemplateSwitchRequest(BaseModel):
    target_template_id: str = Field(min_length=1)
    actor_name: str = Field(default="演示 CRA", max_length=80)


class TemplateSwitchRollbackRequest(BaseModel):
    actor_name: str = Field(default="演示 CRA", max_length=80)


class VisitDateReassessmentRequest(BaseModel):
    visit_date: str = Field(min_length=1, max_length=40)
    rule_pack_id: str = Field(default="", max_length=120)
    actor_name: str = Field(default="演示 CRA", max_length=80)


class MasterDataRefreshRequest(BaseModel):
    actor_name: str = Field(default="演示 CRA", max_length=80)
    selected_targets: list[str] = Field(default_factory=list, max_length=30)
    reason: str = Field(min_length=1, max_length=3000)


class MasterDataRefreshRollbackRequest(BaseModel):
    actor_name: str = Field(default="演示 CRA", max_length=80)
    reason: str = Field(min_length=1, max_length=3000)


class ClarificationRefreshRequest(BaseModel):
    actor_name: str = Field(default="演示 CRA", max_length=80)


class ClarificationResponseRequest(BaseModel):
    action: Literal["answer", "select_candidate", "supplement", "manual_escalation"]
    answer_text: str = Field(default="", max_length=3000)
    selected_candidate_id: str = Field(default="", max_length=120)
    actor_name: str = Field(default="演示 CRA", max_length=80)


class TaskPatch(BaseModel):
    status: str = Field(min_length=1, max_length=40)
    evidence: str = Field(default="", max_length=3000)
    execution_date: str = Field(default="", max_length=40)
    checked_scope: str = Field(default="", max_length=500)
    rationale: str = Field(default="", max_length=3000)
    completed_by: str = Field(default="演示 CRA", max_length=80)


class SubjectCodesUpdate(BaseModel):
    subject_codes: list[dict[str, str]] = Field(default_factory=list)


class ReportGenerateRequest(BaseModel):
    created_by: str = Field(default="演示 CRA", max_length=80)


class TemplateMappingPatch(BaseModel):
    field_key: str | None = Field(default=None, max_length=120)
    target_description: str | None = Field(default=None, max_length=300)
    required: bool | None = None


class TemplateFieldSlotCreate(BaseModel):
    table_index: int = Field(default=0, ge=0)
    target_kind: str = Field(default="table_cell", max_length=40)
    label: str = Field(default="", max_length=160)
    field_key: str = Field(default="", max_length=120)
    target_locator: str = Field(default="", max_length=240)
    value_source: str = Field(default="confirmed_text", max_length=80)
    required: bool = False


class TemplateFieldSlotPatch(BaseModel):
    table_index: int | None = Field(default=None, ge=0)
    target_kind: str | None = Field(default=None, max_length=40)
    label: str | None = Field(default=None, max_length=160)
    field_key: str | None = Field(default=None, max_length=120)
    target_locator: str | None = Field(default=None, max_length=240)
    value_source: str | None = Field(default=None, max_length=80)
    required: bool | None = None


class TemplateFieldSlotSuggestionImportRequest(BaseModel):
    actor_name: str = Field(default="项目管理员", min_length=1, max_length=120)


class TemplateMappingSuggestionImportRequest(BaseModel):
    actor_name: str = Field(default="项目管理员", min_length=1, max_length=120)


class TemplateVisitTypeKeywordsPatch(BaseModel):
    visit_type_keywords: list[str] = Field(default_factory=list, max_length=30)


class TemplateCompletenessRulesPatch(BaseModel):
    task_mode: Literal["mapping_required", "all_mappings", "none"] = "mapping_required"
    field_mode: Literal["slot_required", "all_confirmed_text_slots", "none"] = "slot_required"


class TemplateRevisionDraftCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    version: str = Field(default="", max_length=80)
    actor_name: str = Field(default="项目管理员", min_length=1, max_length=120)


class ProjectMemberCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["CRA", "PM_LM", "PROJECT_ADMIN", "QA_CLINICAL_OPS", "MEDICAL_DATA_REVIEWER"]


class ProjectMemberPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    role: Literal["CRA", "PM_LM", "PROJECT_ADMIN", "QA_CLINICAL_OPS", "MEDICAL_DATA_REVIEWER"] | None = None
    status: Literal["active", "inactive"] | None = None


class CurrentRoleUpdate(BaseModel):
    role: Literal["CRA", "PM_LM", "PROJECT_ADMIN", "QA_CLINICAL_OPS", "MEDICAL_DATA_REVIEWER"]


class OfflineDraftSync(BaseModel):
    client_id: str = Field(min_length=1, max_length=120)
    payload: dict[str, str] = Field(default_factory=dict)
    base_updated_at: str = Field(min_length=1, max_length=240)
    actor_name: str = Field(default="演示 CRA", max_length=80)


class SyncConflictResolve(BaseModel):
    resolution: Literal["local", "server"]
    actor_name: str = Field(default="演示 CRA", max_length=80)


class EscalationCreate(BaseModel):
    action_item_id: str | None = None
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=3000)
    severity: Literal["high", "urgent"] = "high"
    target_role: Literal["PM_LM", "PROJECT_ADMIN"] = "PM_LM"
    actor_name: str = Field(default="演示 CRA", max_length=80)


class EscalationDisposition(BaseModel):
    action: Literal["acknowledge", "close"]
    note: str = Field(default="", max_length=3000)
    actor_name: str = Field(default="PM/LM 审核人", min_length=1, max_length=80)


class AdministratorHandoverCreate(BaseModel):
    from_member_id: str = Field(min_length=1)
    to_member_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=3000)
    authorization_basis: str = Field(min_length=1, max_length=3000)
    note: str = Field(default="", max_length=3000)
    actor_name: str = Field(default="项目管理员", min_length=1, max_length=80)


class AdministratorHandoverAcknowledgement(BaseModel):
    acknowledgement_note: str = Field(min_length=1, max_length=3000)
    actor_name: str = Field(default="演示 CRA", min_length=1, max_length=80)


class TaskBulkPatch(BaseModel):
    task_ids: list[str] = Field(min_length=1)
    status: str = Field(min_length=1, max_length=40)
    evidence: str = Field(default="", max_length=3000)
    actor_name: str = Field(default="演示 CRA", max_length=80)


class RulePackCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(default="V1.0", max_length=80)
    effective_from: str = Field(default="", max_length=40)
    effective_to: str = Field(default="", max_length=40)
    content: dict[str, object] = Field(default_factory=dict)


class RulePackPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    version: str | None = Field(default=None, max_length=80)
    effective_from: str | None = Field(default=None, max_length=40)
    effective_to: str | None = Field(default=None, max_length=40)
    content: dict[str, object] | None = None


class ConfigurationApprovalAction(BaseModel):
    action: Literal["submit", "approve", "reject", "withdraw", "deactivate"]
    actor_name: str = Field(default="演示审批人", min_length=1, max_length=120)
    note: str = Field(default="", max_length=3000)


class AdapterConfigPatch(BaseModel):
    provider: Literal["deterministic", "openai_compatible"] | None = None
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=160)
    enabled: bool | None = None


class LanguageSuggestionDecision(BaseModel):
    decision: Literal["accepted", "edited", "rejected"]
    actor_name: str = Field(default="演示 CRA", max_length=80)
    edited_text: str | None = Field(default=None, max_length=5000)


class LanguageSuggestionRevocationRequest(BaseModel):
    actor_name: str = Field(default="演示 CRA", max_length=80)
    reason: str = Field(min_length=1, max_length=3000)


class ReviewCommentResolve(BaseModel):
    resolution: Literal["accepted", "declined"]
    note: str = Field(default="", max_length=3000)
    actor_name: str = Field(default="演示 CRA", max_length=80)
