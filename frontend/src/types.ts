export type ReportStatus = 'draft' | 'submitted' | 'returned' | 'withdrawn' | 'approved' | 'voided' | 'cancelled'
export type WorkflowStage = 'draft' | 'pending_cra_confirmation' | 'ready_to_submit' | 'under_review' | 'returned' | 'approved' | 'cancelled'
export type UserRole = 'CRA' | 'PM_LM' | 'PROJECT_ADMIN' | 'QA_CLINICAL_OPS' | 'MEDICAL_DATA_REVIEWER'
export type ConfigurationStatus = 'draft' | 'pending_approval' | 'active' | 'rejected' | 'inactive'
export type ConfigurationApprovalAction = 'submit' | 'approve' | 'reject' | 'withdraw' | 'deactivate'
export type ProjectEligibilityAssessmentStatus = 'draft' | 'pending_approval' | 'approved' | 'rejected' | 'withdrawn'
export type TaskExecutionStatus = '待补录' | '未开始' | '进行中' | '待 CRA 确认' | '已确认' | '已执行且未发现' | '已执行且有发现' | '未检查' | '暂无法检查' | '不适用' | '已完成'

export interface TableTask {
  id: string
  index: number
  table_index?: number
  task_type?: 'template_table' | 'system_device_check' | string
  field_key?: string
  title: string
  description?: string
  status: string
  evidence: string
  execution_date?: string
  checked_scope?: string
  rationale?: string
  completed_by?: string
  requires_evidence?: number
  updated_at?: string
}

export interface TaskExecutionPatch {
  status: TaskExecutionStatus
  evidence: string
  execution_date: string
  checked_scope: string
  rationale: string
  completed_by: string
}

export interface ReportReadiness {
  ready: boolean
  blocks: Array<{ code: string; task_id: string; task_index: number; message: string }>
  warnings: Array<{ code: string; escalation_id?: string; message: string }>
  summary: {
    task_count: number
    required_tasks: number
    terminal_required_tasks: number
    block_count: number
    warning_count: number
  }
}

export type ClarificationIssueType = 'missing' | 'conflict'
export type ClarificationStatus = 'open' | 'manual_required' | 'resolved'

export interface ClarificationCandidate {
  id: string
  kind: 'confirmed_field' | 'frozen_document' | string
  value: string
  versions?: string[]
  dates?: string[]
  target_table?: number
  field_key?: string
  category?: string
  subject_code?: string
  subject_display_code?: string
  source?: Record<string, string>
}

export interface ClarificationResponse {
  id: string
  clarification_item_id: string
  answer_text: string
  selected_candidate_id: string
  response_status: 'valid' | 'invalid' | 'escalated' | string
  invalid_reason: string
  actor_name: string
  created_at: string
}

export interface ClarificationItem {
  id: string
  visit_id: string
  issue_key: string
  issue_type: ClarificationIssueType
  severity: 'high' | 'medium' | 'low' | string
  is_blocking: boolean
  status: ClarificationStatus
  title: string
  prompt: string
  reason: string
  target_task_id: string | null
  target_table: number
  field_key: string
  candidates: ClarificationCandidate[]
  source: Record<string, unknown>
  resolution: Record<string, unknown>
  invalid_attempts: number
  created_at: string
  updated_at: string
  resolved_at: string
  resolved_by: string
  responses: ClarificationResponse[]
}

export interface RecordItem {
  id: string
  text: string
  record_kind?: 'monitoring_note' | 'center_explanation' | 'correction' | string
  created_by?: string
  linked_task_id?: string
  recorded_at?: string
  client_created_at?: string
  client_timezone?: string
  server_received_at?: string
  text_hash?: string
  processing_status?: 'pending' | 'completed' | 'no_suggestions' | 'failed' | string
  processing_error?: string
  processed_at?: string
  tags?: string[]
  client_idempotency_key?: string
  corrected_record_id?: string | null
  correction_reason?: string
  record_status?: 'active' | 'voided' | string
  void_reason?: string
  voided_at?: string
  voided_by?: string
  modification_history?: RecordModification[]
  created_at: string
}

export interface RecordModification {
  record_id: string
  kind: 'correction' | string
  reason: string
  actor_name: string
  created_at: string
  record_status?: 'active' | 'voided' | string
}

export interface Suggestion {
  id: string
  target_table: number
  target_task_id?: string | null
  field_key?: string
  category: string
  title: string
  proposed_text: string
  source: string
  subject: string
  subject_validation_status?: 'valid' | 'unverified' | 'not_provided' | 'historical_unverified' | string
  subject_display_code?: string
  confidence?: number
  value_type?: string
  assertion_type?: string
  source_type?: string
  evidence_text?: string
  evidence_start?: number
  evidence_end?: number
  entity_type?: string
  entity_id?: string
  pending_reason?: string
  ai_execution_id?: string
  status: 'pending' | 'accepted' | 'edited' | 'rejected'
  created_at: string
  final_text?: string
}

export interface ConfirmedItem {
  id: string
  target_table: number
  field_key?: string
  category: string
  subject: string
  subject_code?: string
  text: string
  value?: string
  confirmed_at: string
  source_record_id?: string
  suggestion_id?: string
  report_text?: string
  language_suggestion_id?: string
  language_status?: string
  decision?: 'accepted' | 'edited' | 'rejected' | string
  decision_reason?: string
  assertion_type?: string
  source_type?: string
  subject_validation_status?: string
  subject_display_code?: string
}

export interface ReviewComment {
  id: string
  action: 'comment' | 'returned' | 'approved'
  comment_type?: 'pm_lm_review' | 'specialist_comment' | 'specialist_concurrence'
  message: string
  reviewer_name: string
  created_at: string
  target_key?: string
  status?: 'open' | 'resolved'
  resolution?: 'accepted' | 'declined'
  resolution_note?: string
  resolved_by?: string
  resolved_at?: string
  version_number?: string
}

export interface LanguageSuggestion {
  id: string
  visit_id: string
  confirmed_field_id: string
  rule_pack_id: string
  target_table: number
  field_key: string
  category: string
  subject_code: string
  original_text: string
  proposed_text: string
  change_summary: string
  status: 'pending' | 'accepted' | 'edited' | 'rejected' | 'revoked'
  final_text: string
  created_at: string
  decided_at: string
  decided_by: string
  revoked_at: string
  revoked_by: string
  revoke_reason: string
  source_record_id?: string
  suggestion_id?: string
}

export interface RulePack {
  id: string
  project_id: string
  name: string
  version: string
  effective_from: string
  effective_to: string
  content: Record<string, unknown>
  status: ConfigurationStatus
  submitted_at: string
  submitted_by: string
  reviewed_at: string
  reviewed_by: string
  review_note: string
  created_at: string
  updated_at: string
  eligibility?: RulePackEligibility
}

export type RuleEligibilityStatus = 'eligible' | 'not_yet_effective' | 'expired' | 'visit_date_required' | 'invalid_visit_date' | 'invalid_rule_dates' | 'not_active'

export interface RulePackEligibility {
  status: RuleEligibilityStatus
  selectable: boolean
  message: string
  assessment_date: string
  days_until_expiry: number | null
  expires_soon: boolean
}

export interface AdapterConfig {
  provider: 'deterministic' | 'openai_compatible'
  base_url: string
  model: string
  enabled: boolean
  network_calls: boolean
  status_note: string
}

export interface EvidenceChain {
  visit: { id: string; code: string; template_name: string; template_version: string }
  rule_pack: RulePack
  fields: Array<{
    confirmed_field_id: string
    target_table: number
    field_key: string
    category: string
    subject_code: string
    confirmed_text: string
    report_text: string
    report_included?: boolean
    decision: string
    decision_reason: string
    confirmed_by: string
    confirmed_at: string
    source_record: { id: string; text: string; record_kind: string; created_by: string; created_at: string; text_hash: string; client_created_at: string; client_timezone: string; server_received_at: string }
    source_suggestion: { id: string; title: string; proposed_text: string; status: string; value_type: string; assertion_type: string; source_type: string; evidence_text: string; evidence_start: number; evidence_end: number; entity_type: string; entity_id: string; pending_reason: string; ai_execution_id: string; subject_validation_status: string; subject_display_code: string }
    ai_execution: AiExecution
    language: Partial<LanguageSuggestion> & { status: string; final_text: string; change_summary: string }
  }>
  language_history: LanguageSuggestion[]
  ai_executions: AiExecution[]
  clarifications?: ClarificationItem[]
}

export interface AiExecution {
  id: string
  provider: string
  model_version: string
  prompt_version: string
  schema_version: string
  rule_pack_version: string
  executed_at: string
  input_record_hash: string
  output_hash: string
  validation_status: string
  retry_count: number
  error_code: string
}

export interface Finding {
  id: string
  visit_id: string
  subject_code: string
  category: string
  description: string
  severity: string
  status: string
  created_at: string
  action_item_count: number
}

export interface ActionItem {
  id: string
  visit_id: string
  finding_id: string | null
  finding_ids: string[]
  linked_findings: Finding[]
  source_action_item_id: string | null
  source_visit_code?: string | null
  source_visit_date?: string | null
  title: string
  description: string
  owner: string
  due_date: string
  status: 'open' | 'in_progress' | 'closed'
  closure_note: string
  closed_at: string
  created_at: string
  updated_at: string
  attachment_count: number
}

export interface HistoricalOpenAction {
  id: string
  visit_id: string
  source_action_item_id: string | null
  source_visit_id: string
  source_visit_code: string
  source_visit_date: string
  title: string
  description: string
  owner: string
  due_date: string
  status: 'open' | 'in_progress'
  closure_note: string
  created_at: string
  updated_at: string
  attachment_count: number
}

export interface Attachment {
  id: string
  visit_id: string
  action_item_id: string | null
  file_name: string
  stored_path: string
  description: string
  created_by: string
  created_at: string
}

export interface ReportRevision {
  id: string
  visit_id: string
  parent_revision_id?: string | null
  version_number: string
  revision_type: 'working' | 'formal'
  status: ReportStatus
  file_name: string
  file_path: string
  generated_at: string
  submitted_at: string
  submitted_by: string
  review_started_at?: string
  review_started_by?: string
  withdrawn_at?: string
  withdrawn_by?: string
  withdrawn_reason?: string
  voided_at?: string
  voided_by?: string
  void_reason?: string
  created_at: string
}

export interface HistoryReportItem {
  id: string
  visit_id: string
  version_number: string
  revision_type: 'working' | 'formal'
  revision_status: ReportStatus
  file_name: string
  generated_at: string
  submitted_at: string
  created_at: string
  visit_code: string
  visit_type: string
  visit_date: string
  visit_status: string
  site_id: string
  site_code: string
  site_name: string
}

export interface HistoryFindingSource {
  finding_id: string
  visit_id: string
  visit_code: string
  visit_date: string
  site_id: string
  site_code: string
  site_name: string
  description: string
  severity: string
  status: string
  created_at: string
}

export interface RepeatedHistoryFinding {
  key: string
  category: string
  description: string
  count: number
  site_count: number
  latest_found_at: string
  source_visits: HistoryFindingSource[]
}

export interface HistoryOpenAction {
  id: string
  visit_id: string
  source_action_item_id: string | null
  title: string
  description: string
  owner: string
  due_date: string
  status: 'open' | 'in_progress'
  created_at: string
  updated_at: string
  closed_at: string
  visit_code: string
  visit_date: string
  site_id: string
  site_code: string
  site_name: string
  is_overdue: boolean
}

export interface ProjectHistoryInsights {
  scope: {
    project_id: string
    site_id: string
    site_name: string
    as_of: string
    visit_count: number
    formal_report_count: number
    repeated_finding_count: number
    open_action_count: number
    overdue_action_count: number
  }
  reports: HistoryReportItem[]
  repeated_findings: RepeatedHistoryFinding[]
  open_actions: HistoryOpenAction[]
}

export interface ProjectInfo {
  study_name: string
  study_id: string
  site_name: string
  pi_name: string
  sponsor: string
  approval_number: string
  protocol_version: string
  icf_version: string
  ethics_date: string
  sop_version: string
  blinding_mode?: 'open_label' | 'blinded_with_separation'
  subject_code_display_mode?: 'masked' | 'full' | string
  trial_control?: { blinding_mode: string; system_unblinds: boolean; note: string }
  project_eligibility?: FrozenProjectEligibilityAssessment
}

export interface ProjectEligibilityBoundary {
  matches_local_mvp_boundary: boolean
  boundary_notes: string[]
}

export interface ProjectEligibilityAssessment {
  id: string
  project_id: string
  assessment_version: number
  assessment_scope: string
  blinding_mode: 'open_label' | 'blinded_with_separation'
  processes_nonblind_data: boolean
  contains_direct_identifiers: boolean
  requires_full_blind_separation: boolean
  uses_editable_docx_only: boolean
  requires_ctms_etmf_integration: boolean
  assessment_note: string
  effective_from: string
  effective_to: string
  status: ProjectEligibilityAssessmentStatus
  submitted_at: string
  submitted_by: string
  reviewed_at: string
  reviewed_by: string
  review_note: string
  withdrawn_at: string
  withdrawn_by: string
  withdrawal_note: string
  created_at: string
  updated_at: string
  boundary: ProjectEligibilityBoundary
}

export interface FrozenProjectEligibilityAssessment extends ProjectEligibilityAssessment {
  assessment_as_of?: string
  frozen_at?: string
}

export interface ProjectEligibilityAssessmentInput {
  assessment_scope: string
  blinding_mode: 'open_label' | 'blinded_with_separation'
  processes_nonblind_data: boolean
  contains_direct_identifiers: boolean
  requires_full_blind_separation: boolean
  uses_editable_docx_only: boolean
  requires_ctms_etmf_integration: boolean
  assessment_note: string
  effective_from: string
  effective_to: string
  actor_name: string
}

export interface VisitInfo {
  id?: string
  project_id?: string
  site_id?: string
  visit_type: string
  visit_date: string
  activity_start_date: string
  activity_end_date?: string
  visit_method: string
  visit_location: string
  contact_persons: string
  report_date: string
  site_team: string
  monitoring_team: string
  next_visit: string
  cra_name: string
  status?: string
  updated_at?: string
  sync_token?: string
  snapshot?: Record<string, unknown>
}

export interface ProjectMember {
  id: string
  project_id: string
  display_name: string
  role: UserRole
  status: 'active' | 'inactive'
  created_at: string
}

export interface OfflineDraft {
  id: string
  visit_id: string
  client_id: string
  payload: { text: string }
  base_updated_at: string
  status: 'pending' | 'conflict' | 'synced' | 'discarded'
  created_at: string
  updated_at: string
}

export interface SyncConflict {
  id: string
  visit_id: string
  draft_id: string
  field_key: string
  local_value: string
  server_value: string
  status: 'open' | 'resolved'
  created_at: string
  resolved_at: string
}

export interface OperationEscalation {
  id: string
  project_id: string
  visit_id: string
  action_item_id: string | null
  action_title?: string | null
  title: string
  description: string
  severity: 'high' | 'urgent'
  target_role: 'PM_LM' | 'PROJECT_ADMIN'
  sla_snapshot: EscalationSlaSnapshot
  sla_due_at: string
  overdue_escalated_at: string
  overdue_escalated_to: 'PM_LM' | 'PROJECT_ADMIN' | ''
  sla: EscalationSlaStatus
  status: 'open' | 'acknowledged' | 'closed'
  created_by: string
  created_at: string
  acknowledged_at: string
  acknowledged_by: string
  acknowledgement_note: string
  closed_at: string
  closed_by: string
  resolution_note: string
}

export interface EscalationSlaSnapshot {
  configured: boolean
  acknowledge_within_hours: number | null
  initial_target_role: 'PM_LM' | 'PROJECT_ADMIN' | ''
  overdue_target_role: 'PM_LM' | 'PROJECT_ADMIN' | ''
  source: 'frozen_rule_pack' | 'not_configured'
  severity: 'high' | 'urgent'
  rule_pack_id: string
  rule_pack_name: string
  rule_pack_version: string
}

export interface EscalationSlaStatus {
  configured: boolean
  state: 'not_configured' | 'pending' | 'overdue_escalated' | 'acknowledged_within_sla' | 'acknowledged_late' | 'closed'
  receipt_state: 'not_configured' | 'pending' | 'overdue_escalated' | 'acknowledged_within_sla' | 'acknowledged_late'
  due_at: string
  remaining_minutes: number | null
  overdue_target_role: 'PM_LM' | 'PROJECT_ADMIN' | ''
  acknowledged_within_sla: boolean | null
}

export interface VisitHandover {
  id: string
  project_id: string
  visit_id: string
  from_member_id: string | null
  to_member_id: string
  from_member_name?: string | null
  to_member_name: string
  note: string
  handover_mode: 'cra_initiated' | 'administrator_authorized'
  authorization_basis: string
  reason: string
  status: 'completed' | 'pending_recipient_confirmation'
  created_by: string
  created_at: string
  acknowledged_at: string
  acknowledged_by: string
  acknowledgement_note: string
}

export interface VisitOperations {
  visit_id: string
  project_id: string
  as_of: string
  overdue_actions: ActionItem[]
  due_soon_actions: ActionItem[]
  missing_tasks: Array<TableTask & { table_index: number }>
  escalations: OperationEscalation[]
  handovers: VisitHandover[]
}

export interface Recruitment {
  screened: number
  screen_failed: number
  treated: number
  ae_dropout: number
  other_dropout: number
  completed_treatment: number
  follow_up: number
  follow_up_dropout: number
  completed_follow_up: number
}

export interface DemoState {
  project: ProjectInfo
  visit: VisitInfo
  template?: {
    id: string
    name: string
    version: string
    table_count: number
  }
  template_switches?: TemplateSwitchRecord[]
  visit_date_reassessments?: VisitDateReassessmentRecord[]
  rule_pack?: RulePack
  recruitment: Recruitment
  table_tasks: TableTask[]
  system_check_tasks?: TableTask[]
  records: RecordItem[]
  suggestions: Suggestion[]
  confirmed_items: ConfirmedItem[]
  center_explanations?: ConfirmedItem[]
  clarification_items?: ClarificationItem[]
  language_suggestions?: LanguageSuggestion[]
  findings: Finding[]
  ae_records: Array<{ id: string; subject: string; description: string; is_sae: boolean }>
  deviations: Array<{ id: string; subject: string; description: string }>
  action_items: ActionItem[]
  historical_open_actions?: HistoricalOpenAction[]
  attachments: Attachment[]
  revisions: ReportRevision[]
  review_comments: ReviewComment[]
  report_status: ReportStatus
  workflow_stage?: WorkflowStage
  workflow_stage_summary?: {
    readiness_block_count: number
    pending_suggestion_count: number
    pending_language_count: number
    open_clarification_count?: number
  }
  last_generated_at: string | null
  last_generated_file: string | null
  last_submitted_at: string | null
  project_members: ProjectMember[]
  master_data?: FrozenMasterData
  current_role: UserRole
  audit_events: Array<{
    id: string
    entity_type: string
    entity_id: string
    action: string
    actor_name: string
    detail: Record<string, unknown>
    created_at: string
  }>
}

export interface ProjectSummary {
  id: string
  code: string
  name: string
  sponsor: string
  status: string
  site_count: number
  visit_count: number
  last_visit_updated_at: string | null
  metadata: Record<string, string>
}

export interface SiteSummary {
  id: string
  project_id: string
  code: string
  name: string
  pi_name: string
  ethics_date: string
  protocol_version: string
  icf_version: string
  status: string
  visit_count: number
  subject_count: number
}

export type ControlledDocumentType = 'protocol' | 'icf' | 'ethics' | 'other'

export interface SiteMasterVersion {
  id: string
  site_id: string
  version_label: string
  pi_name: string
  site_address: string
  site_team: string
  key_roles: Record<string, string>
  effective_from: string
  effective_to: string
  status: 'active' | 'superseded' | 'inactive'
  created_by: string
  created_at: string
  updated_at: string
}

export interface ControlledDocument {
  id: string
  project_id: string
  site_id: string | null
  document_type: ControlledDocumentType
  title: string
  version: string
  version_date: string
  effective_from: string
  effective_to: string
  status: 'active' | 'superseded' | 'inactive'
  source_file_name: string
  stored_path: string
  content_hash: string
  source_reference: string
  notes: string
  created_by: string
  created_at: string
  updated_at: string
}

export interface FrozenMasterData {
  visit_date: string
  site_profile: Pick<SiteMasterVersion, 'id' | 'version_label' | 'pi_name' | 'site_address' | 'site_team' | 'key_roles' | 'effective_from' | 'effective_to'> & { source: string }
  documents: Record<string, { id?: string; document_type: ControlledDocumentType; title: string; version?: string; version_date?: string; effective_from?: string; effective_to?: string; source_file_name?: string; content_hash?: string; source_reference?: string; display: string; source?: string }>
  document_list: Array<{ id?: string; document_type: ControlledDocumentType; title: string; display: string; effective_from?: string; effective_to?: string }>
}

export interface ImportBatchRow {
  id: string
  row_number: number
  action: 'create' | 'update' | 'skip'
  entity_type: string
  operation: Record<string, unknown>
  source_row: Record<string, string>
  error_message: string
}

export interface ImportBatch {
  id: string
  scope: 'projects' | 'sites' | 'subjects'
  file_name: string
  content_hash: string
  source_system?: string
  source_reference?: string
  source_exported_at?: string
  import_profile_id?: string
  import_profile_name?: string
  default_project_id: string
  default_site_id: string
  actor_name: string
  status: 'previewed' | 'committed'
  preview_summary: { total: number; created: number; updated: number; valid: number; skipped: number }
  committed_summary: { total?: number; created?: number; updated?: number; skipped?: number; errors?: Array<{ row: number; message: string }> }
  created_at: string
  committed_at: string
  rows: ImportBatchRow[]
}

export interface ImportQualityScopeSummary {
  scope: 'projects' | 'sites' | 'subjects'
  batch_count: number
  total_rows: number
  valid_rows: number
  skipped_rows: number
  quality_rate: number
}

export interface ImportQualityBatch {
  id: string
  scope: 'projects' | 'sites' | 'subjects'
  file_name: string
  status: 'previewed' | 'committed'
  created_at: string
  committed_at: string
  total_rows: number
  valid_rows: number
  skipped_rows: number
  quality_rate: number
  source_system: string
  source_reference: string
  import_profile_id: string
  import_profile_name: string
}

export interface ImportQualitySummary {
  project_id: string
  last_imported_at: string
  summary: {
    total_batches: number
    committed_batches: number
    previewed_batches: number
    total_rows: number
    valid_rows: number
    skipped_rows: number
    source_traced_batches: number
    quality_rate: number
  }
  scope_summary: ImportQualityScopeSummary[]
  batches: ImportQualityBatch[]
}

export interface VisitSummary {
  id: string
  project_id: string
  site_id: string
  code: string
  visit_type: string
  visit_date: string
  activity_start_date: string
  visit_method: string
  visit_location: string
  contact_persons: string
  report_date: string
  site_name: string
  template_name: string
  template_version: string
  revision_count: number
  formal_revision_count: number
  cancellation_eligible: boolean
  latest_revision_status: ReportStatus | null
}

export interface TemplateSummary {
  id: string
  name: string
  version: string
  docx_path: string
  table_count: number
  metadata: Record<string, unknown>
  status: string
  submitted_at: string
  submitted_by: string
  reviewed_at: string
  reviewed_by: string
  review_note: string
  created_at: string
  updated_at: string
}

export interface TemplateMapping {
  id: string
  template_id: string
  table_index: number
  field_key: string
  target_description: string
  required: number
  created_at: string
}

export interface TemplateFieldSlot {
  id: string
  template_id: string
  table_index: number
  target_kind: TemplateFieldSlotTargetKind
  label: string
  field_key: string
  target_locator: string
  value_source: string
  required: number
  created_at: string
}

export type TemplateFieldSlotTargetKind = 'table_cell' | 'body_paragraph' | 'header_paragraph' | 'footer_paragraph' | 'inline_token' | 'content_control' | 'bookmark' | 'merge_field'

export interface DetectedTextTarget {
  target_kind: TemplateFieldSlotTargetKind
  target_locator: string
  label: string
  preview: string
}

export interface DetectedTable {
  table_index: number
  detected_label: string
  row_count: number
  column_count: number
  suggested_target_locator?: string
}

export interface TemplateMappingSuggestion {
  table_index: number
  field_key: string
  target_description: string
  confidence: 'high' | 'medium' | 'low'
  matched_terms: string[]
  reason: string
  algorithm: string
}

export interface TemplateFieldSlotSuggestion {
  table_index: number
  target_kind: TemplateFieldSlotTargetKind
  target_locator: string
  label: string
  field_key: string
  value_source: string
  confidence: 'high' | 'medium' | 'low'
  matched_terms: string[]
  reason: string
  algorithm: string
}

export interface TemplateFieldSlotSuggestionImportResult {
  detail: TemplateDetail
  candidate_count: number
  created_count: number
  adopted_default_count: number
  skipped_existing_count: number
  created_labels: string[]
  adopted_default_labels: string[]
  skipped_existing_labels: string[]
}

export interface TemplateMappingSuggestionImportResult {
  detail: TemplateDetail
  candidate_count: number
  adopted_count: number
  skipped_existing_count: number
  missing_mapping_count: number
  adopted_labels: string[]
  skipped_existing_labels: string[]
  missing_mapping_labels: string[]
}

export interface TemplateConfigurationPackageImportResult {
  detail: TemplateDetail
  source_template: {
    name: string
    version: string
  }
  source_mapping_count: number
  applied_mapping_count: number
  skipped_mapping_count: number
  source_field_slot_count: number
  applied_field_slot_count: number
  skipped_field_slot_count: number
  skipped_field_slot_labels: string[]
}

export type TemplateMatchConfidence = 'high' | 'medium' | 'low'

export interface TemplateVisitTypeHint {
  code: string
  label: string
  matched_terms: string[]
}

export interface TemplateMatchingProfile {
  algorithm: string
  inferred_visit_types: TemplateVisitTypeHint[]
  matched_terms: string[]
  administrator_keywords: string[]
}

export interface TemplateConfigurationReadiness {
  mapping: {
    detected_table_count: number
    mapping_count: number
    configured_count: number
    pending_count: number
    high_confidence_suggestion_count: number
    high_confidence_pending_count: number
  }
  field_slots: {
    configured_count: number
    fixed_data_count: number
    confirmed_text_count: number
    high_confidence_suggestion_count: number
    high_confidence_pending_count: number
    inline_token_suggestion_count: number
    inline_token_configured_count: number
  }
  outstanding_count: number
}

export interface TemplateRecommendation {
  template: TemplateSummary
  matching_profile: TemplateMatchingProfile
  score: number
  confidence: TemplateMatchConfidence
  matched_terms: string[]
  reasons: string[]
}

export interface TemplateRecommendationResponse {
  visit_type: string
  recommended_template_id: string
  auto_selectable: boolean
  items: TemplateRecommendation[]
}

export interface TemplateDetail {
  template: TemplateSummary
  mappings: TemplateMapping[]
  field_slots: TemplateFieldSlot[]
  detected_tables: DetectedTable[]
  mapping_suggestions: TemplateMappingSuggestion[]
  field_slot_suggestions: TemplateFieldSlotSuggestion[]
  detected_text_targets: DetectedTextTarget[]
  matching_profile: TemplateMatchingProfile
  configuration_readiness: TemplateConfigurationReadiness
}

export interface TemplateSwitchSummary {
  preserved_tasks: number
  hidden_tasks: number
  new_tasks: number
  migratable_confirmed_fields: number
  hidden_confirmed_fields: number
  migratable_suggestions: number
  hidden_suggestions: number
}

export interface TemplateSwitchPreview {
  can_switch: boolean
  reason: string
  visit: { id: string; code: string; status: string }
  from_template: Pick<TemplateSummary, 'id' | 'name' | 'version' | 'table_count' | 'status'>
  to_template: Pick<TemplateSummary, 'id' | 'name' | 'version' | 'table_count' | 'status'>
  summary: TemplateSwitchSummary
  task_changes: Array<{
    action: 'preserve' | 'hide' | 'new'
    task_id: string
    source_table_index: number | null
    target_table_index: number | null
    title: string
    target_title: string
    matched_by: string
  }>
  field_changes: Array<{
    id: string
    action: 'preserve' | 'hide'
    source_table_index: number
    target_table_index: number | null
    label: string
    matched_by: string
  }>
  suggestion_changes: Array<{
    id: string
    action: 'preserve' | 'hide'
    source_table_index: number
    target_table_index: number | null
    label: string
    matched_by: string
  }>
  source_mapping_count: number
  target_mapping_count: number
}

export interface TemplateSwitchRecord {
  id: string
  visit_id: string
  from_template_id: string
  to_template_id: string
  from_template_name: string
  from_template_version: string
  to_template_name: string
  to_template_version: string
  preview: TemplateSwitchPreview
  actor_name: string
  created_at: string
  rolled_back_at: string
  rolled_back_by: string
}

export interface VisitDateReassessmentSummary {
  changed_master_items: number
  preserved_system_tasks: number
  new_system_tasks: number
  archived_system_tasks: number
  site_team_action: 'refresh' | 'preserve_manual' | string
}

export interface VisitDateReassessmentPreview {
  can_apply: boolean
  reason: string
  visit: { id: string; code: string; status: string; from_visit_date: string; to_visit_date: string }
  visit_context: {
    from: { activity_start_date: string; activity_end_date: string; visit_method: string; visit_location: string; contact_persons: string }
    to: { activity_start_date: string; activity_end_date: string; visit_method: string; visit_location: string; contact_persons: string }
    activity_start_date_action: 'synchronize_single_day' | 'preserve_multi_day' | string
    message: string
  }
  from_rule_pack: { id: string; name: string; version: string; status: string; eligibility?: RulePackEligibility }
  to_rule_pack: { id: string; name: string; version: string; status: string; eligibility?: RulePackEligibility }
  eligible_rule_packs: Array<{ id: string; name: string; version: string; status: string; eligibility: RulePackEligibility }>
  master_data_changes: {
    site_profile: { changed: boolean; from: { display?: string }; to: { display?: string } }
    documents: Array<{ document_type: string; changed: boolean; from: { display?: string; title?: string }; to: { display?: string; title?: string } }>
    changed_count: number
  }
  site_team: { action: string; from: string; to: string; message: string }
  system_task_changes: {
    changes: Array<{ action: 'preserve' | 'new' | 'archive'; task_id: string; field_key: string; from_title: string; to_title: string; status: string }>
    summary: { preserved: number; new: number; archived: number }
  }
  summary: VisitDateReassessmentSummary
}

export interface VisitDateReassessmentRecord {
  id: string
  visit_id: string
  from_visit_date: string
  to_visit_date: string
  from_rule_pack_id: string
  to_rule_pack_id: string
  from_rule_pack_name: string
  from_rule_pack_version: string
  to_rule_pack_name: string
  to_rule_pack_version: string
  preview: VisitDateReassessmentPreview
  actor_name: string
  created_at: string
}

export interface MasterDataRefreshPreview {
  can_apply: boolean
  has_changes: boolean
  reason: string
  visit: { id: string; code: string; status: string; visit_date: string }
  master_data_changes: {
    site_profile: { target: string; changed: boolean; from: { display?: string }; to: { display?: string } }
    documents: Array<{ document_type: string; target: string; changed: boolean; from: { display?: string; title?: string }; to: { display?: string; title?: string } }>
    changed_count: number
  }
  available_targets: string[]
  site_team: { action: 'refresh' | 'preserve_manual' | 'preserve_unselected' | string; from: string; to: string; message: string }
  summary: { changed_master_items: number; site_team_action: 'refresh' | 'preserve_manual' | 'preserve_unselected' | string }
  rollback: { can_rollback: boolean; reason: string; refresh_id: string; selected_targets: string[]; created_at: string }
}

export type PageKey = 'portfolio' | 'templates' | 'overview' | 'quick_note' | 'history_insights' | 'workbench' | 'report' | 'review' | 'collaboration' | 'governance'
