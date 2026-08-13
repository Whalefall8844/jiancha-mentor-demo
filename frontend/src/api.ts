import type { ActionItem, AdapterConfig, Attachment, ClarificationItem, ConfigurationApprovalAction, ControlledDocument, ControlledDocumentType, DemoState, EvidenceChain, FrozenMasterData, ImportBatch, ImportQualitySummary, LanguageSuggestion, MasterDataRefreshPreview, OfflineDraft, OperationEscalation, ProjectEligibilityAssessment, ProjectEligibilityAssessmentInput, ProjectHistoryInsights, ProjectInfo, ProjectMember, ProjectSummary, RecordItem, Recruitment, ReportReadiness, ReportRevision, ReportStatus, ReviewComment, RulePack, SiteMasterVersion, SiteSummary, Suggestion, SyncConflict, TaskExecutionPatch, TemplateConfigurationPackageImportResult, TemplateDetail, TemplateFieldSlot, TemplateFieldSlotSuggestionImportResult, TemplateMapping, TemplateMappingSuggestionImportResult, TemplateRecommendationResponse, TemplateSummary, TemplateSwitchPreview, UserRole, VisitDateReassessmentPreview, VisitHandover, VisitInfo, VisitOperations, VisitSummary, WorkflowStage } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(error.detail ?? '请求失败')
  }
  return response.json() as Promise<T>
}

async function upload<T>(path: string, body: FormData, method: 'POST' | 'PUT' = 'POST'): Promise<T> {
  const response = await fetch(path, { method, body })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '导入失败' }))
    throw new Error(error.detail ?? '导入失败')
  }
  return response.json() as Promise<T>
}

async function downloadDocument(path: string, fallbackName: string): Promise<string> {
  const response = await fetch(path)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '文件下载失败' }))
    throw new Error(error.detail ?? '文件下载失败')
  }
  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') ?? ''
  const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  const plainMatch = disposition.match(/filename="?([^";]+)"?/i)
  const filename = encodedMatch ? decodeURIComponent(encodedMatch[1]) : (plainMatch?.[1] ?? fallbackName)
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(href)
  return filename
}

export const api = {
  getState: (visitId?: string) => request<DemoState>(visitId ? `/api/state?visit_id=${encodeURIComponent(visitId)}` : '/api/state'),
  listProjects: () => request<{ items: ProjectSummary[] }>('/api/projects'),
  listSites: (projectId: string) => request<{ items: SiteSummary[] }>(`/api/projects/${projectId}/sites`),
  listVisits: (projectId: string, siteId?: string) => request<{ items: VisitSummary[] }>(`/api/projects/${projectId}/visits${siteId ? `?site_id=${encodeURIComponent(siteId)}` : ''}`),
  getProjectImportQuality: (projectId: string) => request<ImportQualitySummary>(`/api/projects/${projectId}/import-quality`),
  getProjectHistoryInsights: (projectId: string, siteId = '', asOf = '') => {
    const params = new URLSearchParams()
    if (siteId) params.set('site_id', siteId)
    if (asOf) params.set('as_of', asOf)
    const query = params.toString()
    return request<ProjectHistoryInsights>(`/api/projects/${projectId}/history-insights${query ? `?${query}` : ''}`)
  },
  listRulePacks: (projectId: string, includeInactive = true) => request<{ items: RulePack[] }>(`/api/projects/${projectId}/rule-packs${includeInactive ? '?include_inactive=true' : ''}`),
  listRulePackEligibility: (projectId: string, visitDate: string, includeInactive = false) => request<{ visit_date: string; items: RulePack[] }>(`/api/projects/${projectId}/rule-packs/eligibility?visit_date=${encodeURIComponent(visitDate)}${includeInactive ? '&include_inactive=true' : ''}`),
  createRulePack: (projectId: string, payload: { name: string; version: string; effective_from?: string; effective_to?: string; content: Record<string, unknown> }) =>
    request<RulePack>(`/api/projects/${projectId}/rule-packs`, { method: 'POST', body: JSON.stringify(payload) }),
  updateRulePack: (rulePackId: string, patch: Partial<Pick<RulePack, 'name' | 'version' | 'effective_from' | 'effective_to' | 'content'>>) =>
    request<RulePack>(`/api/rule-packs/${rulePackId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  rulePackApprovalAction: (rulePackId: string, payload: { action: ConfigurationApprovalAction; actor_name: string; note?: string }) =>
    request<RulePack>(`/api/rule-packs/${rulePackId}/approval-actions`, { method: 'POST', body: JSON.stringify(payload) }),
  getAdapterConfig: () => request<AdapterConfig>('/api/ai-adapter'),
  updateAdapterConfig: (patch: Partial<Pick<AdapterConfig, 'provider' | 'base_url' | 'model' | 'enabled'>>) =>
    request<AdapterConfig>('/api/ai-adapter', { method: 'PUT', body: JSON.stringify(patch) }),
  listTemplates: (includeNonActive = false) => request<{ items: TemplateSummary[] }>(`/api/templates${includeNonActive ? '?include_non_active=true' : ''}`),
  getTemplate: (templateId: string) => request<TemplateDetail>(`/api/templates/${templateId}`),
  getTemplateRecommendations: (projectId: string, visitType: string) =>
    request<TemplateRecommendationResponse>(`/api/projects/${projectId}/template-recommendations?visit_type=${encodeURIComponent(visitType)}`),
  uploadTemplate: (file: File, displayName: string, version: string) => {
    const body = new FormData()
    body.append('file', file)
    body.append('display_name', displayName)
    body.append('version', version)
    body.append('actor_name', '项目管理员')
    return upload<TemplateDetail>('/api/templates', body)
  },
  createTemplateRevisionDraft: (templateId: string, payload: { name?: string; version?: string; actor_name: string }) =>
    request<TemplateDetail>(`/api/templates/${templateId}/revision-drafts`, { method: 'POST', body: JSON.stringify(payload) }),
  replaceTemplateRevisionDocument: (templateId: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    body.append('actor_name', '项目管理员')
    return upload<TemplateDetail>(`/api/templates/${templateId}/document`, body, 'PUT')
  },
  downloadTemplateConfigurationPackage: (templateId: string, fallbackName: string) =>
    downloadDocument(`/api/templates/${templateId}/configuration-package`, fallbackName),
  importTemplateConfigurationPackage: (templateId: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    body.append('actor_name', '项目管理员')
    return upload<TemplateConfigurationPackageImportResult>(`/api/templates/${templateId}/configuration-package-imports`, body)
  },
  patchTemplateMapping: (templateId: string, mappingId: string, patch: Partial<Pick<TemplateMapping, 'field_key' | 'target_description' | 'required'>>) =>
    request<TemplateDetail>(`/api/templates/${templateId}/mappings/${mappingId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  createTemplateFieldSlot: (templateId: string, payload: Omit<TemplateFieldSlot, 'id' | 'template_id' | 'created_at'>) =>
    request<TemplateDetail>(`/api/templates/${templateId}/field-slots`, { method: 'POST', body: JSON.stringify(payload) }),
  importHighConfidenceTemplateFieldSlotSuggestions: (templateId: string) =>
    request<TemplateFieldSlotSuggestionImportResult>(`/api/templates/${templateId}/field-slot-suggestion-imports`, { method: 'POST', body: JSON.stringify({ actor_name: '项目管理员' }) }),
  importHighConfidenceTemplateMappingSuggestions: (templateId: string) =>
    request<TemplateMappingSuggestionImportResult>(`/api/templates/${templateId}/mapping-suggestion-imports`, { method: 'POST', body: JSON.stringify({ actor_name: '项目管理员' }) }),
  patchTemplateFieldSlot: (templateId: string, slotId: string, patch: Partial<Omit<TemplateFieldSlot, 'id' | 'template_id' | 'created_at'>>) =>
    request<TemplateDetail>(`/api/templates/${templateId}/field-slots/${slotId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteTemplateFieldSlot: (templateId: string, slotId: string) =>
    request<TemplateDetail>(`/api/templates/${templateId}/field-slots/${slotId}`, { method: 'DELETE' }),
  patchTemplateVisitTypeKeywords: (templateId: string, visitTypeKeywords: string[]) =>
    request<TemplateDetail>(`/api/templates/${templateId}/visit-type-keywords`, { method: 'PATCH', body: JSON.stringify({ visit_type_keywords: visitTypeKeywords }) }),
  patchTemplateCompletenessRules: (templateId: string, rules: { task_mode: 'mapping_required' | 'all_mappings' | 'none'; field_mode: 'slot_required' | 'all_confirmed_text_slots' | 'none' }) =>
    request<TemplateDetail>(`/api/templates/${templateId}/completeness-rules`, { method: 'PATCH', body: JSON.stringify(rules) }),
  templateApprovalAction: (templateId: string, payload: { action: ConfigurationApprovalAction; actor_name: string; note?: string }) =>
    request<TemplateDetail>(`/api/templates/${templateId}/approval-actions`, { method: 'POST', body: JSON.stringify(payload) }),
  createProject: (payload: { code: string; name: string; sponsor: string; metadata?: Record<string, string> }) =>
    request<ProjectSummary>('/api/projects', { method: 'POST', body: JSON.stringify(payload) }),
  patchProject: (projectId: string, patch: Partial<Pick<ProjectSummary, 'code' | 'name' | 'sponsor' | 'status' | 'metadata'>>) =>
    request<ProjectSummary>(`/api/projects/${projectId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  listProjectEligibilityAssessments: (projectId: string) =>
    request<{ items: ProjectEligibilityAssessment[]; current_approved: ProjectEligibilityAssessment | null }>(`/api/projects/${projectId}/eligibility-assessments`),
  createProjectEligibilityAssessment: (projectId: string, payload: ProjectEligibilityAssessmentInput) =>
    request<ProjectEligibilityAssessment>(`/api/projects/${projectId}/eligibility-assessments`, { method: 'POST', body: JSON.stringify(payload) }),
  updateProjectEligibilityAssessment: (projectId: string, assessmentId: string, payload: Partial<Omit<ProjectEligibilityAssessmentInput, 'actor_name'>> & { actor_name: string }) =>
    request<ProjectEligibilityAssessment>(`/api/projects/${projectId}/eligibility-assessments/${assessmentId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  projectEligibilityAssessmentApproval: (projectId: string, assessmentId: string, payload: { action: 'submit' | 'approve' | 'reject' | 'withdraw'; actor_name: string; note?: string }) =>
    request<ProjectEligibilityAssessment>(`/api/projects/${projectId}/eligibility-assessments/${assessmentId}/approval`, { method: 'POST', body: JSON.stringify(payload) }),
  createSite: (payload: { project_id: string; code: string; name: string; pi_name?: string; ethics_date?: string; protocol_version?: string; icf_version?: string }) =>
    request<SiteSummary>('/api/sites', { method: 'POST', body: JSON.stringify(payload) }),
  listSiteMasterVersions: (siteId: string, includeInactive = true) => request<{ items: SiteMasterVersion[] }>(`/api/sites/${siteId}/master-versions${includeInactive ? '?include_inactive=true' : ''}`),
  createSiteMasterVersion: (siteId: string, payload: Omit<SiteMasterVersion, 'id' | 'site_id' | 'status' | 'created_at' | 'updated_at'>) =>
    request<SiteMasterVersion>(`/api/sites/${siteId}/master-versions`, { method: 'POST', body: JSON.stringify(payload) }),
  updateSiteMasterVersion: (versionId: string, patch: Partial<Pick<SiteMasterVersion, 'version_label' | 'pi_name' | 'site_address' | 'site_team' | 'key_roles' | 'effective_from' | 'effective_to' | 'status'>>) =>
    request<SiteMasterVersion>(`/api/site-master-versions/${versionId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  listControlledDocuments: (projectId: string, siteId = '', includeInactive = true) => request<{ items: ControlledDocument[] }>(`/api/projects/${projectId}/controlled-documents?site_id=${encodeURIComponent(siteId)}&include_inactive=${includeInactive}`),
  previewFrozenMasterData: (projectId: string, siteId: string, visitDate: string) => request<{ master_data: FrozenMasterData }>(`/api/projects/${projectId}/sites/${siteId}/master-data-preview?visit_date=${encodeURIComponent(visitDate)}`),
  createControlledDocument: (projectId: string, payload: { document_type: ControlledDocumentType; title: string; site_id?: string; version?: string; version_date?: string; effective_from?: string; effective_to?: string; source_reference?: string; notes?: string; actor_name?: string; file?: File | null }) => {
    const body = new FormData()
    body.append('document_type', payload.document_type)
    body.append('title', payload.title)
    body.append('site_id', payload.site_id ?? '')
    body.append('version', payload.version ?? '')
    body.append('version_date', payload.version_date ?? '')
    body.append('effective_from', payload.effective_from ?? '')
    body.append('effective_to', payload.effective_to ?? '')
    body.append('source_reference', payload.source_reference ?? '')
    body.append('notes', payload.notes ?? '')
    body.append('actor_name', payload.actor_name ?? '项目管理员')
    if (payload.file) body.append('file', payload.file)
    return upload<ControlledDocument>(`/api/projects/${projectId}/controlled-documents`, body)
  },
  updateControlledDocument: (documentId: string, patch: Partial<Pick<ControlledDocument, 'title' | 'version' | 'version_date' | 'effective_from' | 'effective_to' | 'status' | 'source_reference' | 'notes'>>) =>
    request<ControlledDocument>(`/api/controlled-documents/${documentId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  downloadControlledDocument: (documentId: string, fallbackName = '受控文件') => downloadDocument(`/api/controlled-documents/${documentId}/download`, fallbackName),
  createVisit: (payload: { project_id: string; site_id: string; code: string; visit_type: string; visit_date: string; activity_start_date?: string; visit_method?: string; visit_location?: string; contact_persons?: string; report_date?: string; cra_name?: string; template_id?: string; rule_pack_id?: string }) =>
    request<{ visit: { id: string } }>('/api/visits', { method: 'POST', body: JSON.stringify(payload) }),
  cancelVisit: (visitId: string, payload: { reason: string; actor_name: string }) =>
    request<{ visit: { id: string; status: ReportStatus } }>(`/api/visits/${visitId}/cancel`, { method: 'POST', body: JSON.stringify(payload) }),
  getTemplateSwitchPreview: (visitId: string, templateId: string) =>
    request<TemplateSwitchPreview>(`/api/visits/${visitId}/template-switch-preview?template_id=${encodeURIComponent(templateId)}`),
  switchVisitTemplate: (visitId: string, targetTemplateId: string, actorName: string) =>
    request<{ switch_id: string; preview: TemplateSwitchPreview; workspace: DemoState }>(`/api/visits/${visitId}/template-switch`, { method: 'POST', body: JSON.stringify({ target_template_id: targetTemplateId, actor_name: actorName }) }),
  rollbackVisitTemplateSwitch: (visitId: string, switchId: string, actorName: string) =>
    request<{ switch_id: string; preview: TemplateSwitchPreview; workspace: DemoState }>(`/api/visits/${visitId}/template-switches/${switchId}/rollback`, { method: 'POST', body: JSON.stringify({ actor_name: actorName }) }),
  getVisitDateReassessmentPreview: (visitId: string, visitDate: string, rulePackId = '') =>
    request<VisitDateReassessmentPreview>(`/api/visits/${visitId}/date-reassessment-preview?visit_date=${encodeURIComponent(visitDate)}&rule_pack_id=${encodeURIComponent(rulePackId)}`),
  applyVisitDateReassessment: (visitId: string, payload: { visit_date: string; rule_pack_id: string; actor_name: string }) =>
    request<{ reassessment_id: string; preview: VisitDateReassessmentPreview; workspace: DemoState }>(`/api/visits/${visitId}/date-reassess`, { method: 'POST', body: JSON.stringify(payload) }),
  getMasterDataRefreshPreview: (visitId: string) =>
    request<MasterDataRefreshPreview>(`/api/visits/${visitId}/master-data-refresh-preview`),
  applyMasterDataRefresh: (visitId: string, payload: { actor_name: string; selected_targets: string[]; reason: string }) =>
    request<{ refresh_id: string; preview: MasterDataRefreshPreview; workspace: DemoState }>(`/api/visits/${visitId}/master-data-refresh`, { method: 'POST', body: JSON.stringify(payload) }),
  rollbackMasterDataRefresh: (visitId: string, payload: { actor_name: string; reason: string }) =>
    request<{ refresh_id: string; rollback_reason: string; workspace: DemoState }>(`/api/visits/${visitId}/master-data-refresh/rollback`, { method: 'POST', body: JSON.stringify(payload) }),
  listClarifications: (visitId: string) => request<{ items: ClarificationItem[] }>(`/api/visits/${visitId}/clarifications`),
  refreshClarifications: (visitId: string, actorName: string) =>
    request<{ items: ClarificationItem[]; workspace: DemoState }>(`/api/visits/${visitId}/clarifications/refresh`, { method: 'POST', body: JSON.stringify({ actor_name: actorName }) }),
  respondToClarification: (visitId: string, itemId: string, payload: { action: 'answer' | 'select_candidate' | 'supplement' | 'manual_escalation'; answer_text?: string; selected_candidate_id?: string; actor_name: string }) =>
    request<{ item: ClarificationItem; workspace: DemoState }>(`/api/visits/${visitId}/clarifications/${itemId}/response`, { method: 'POST', body: JSON.stringify(payload) }),
  getCurrentRole: () => request<{ role: UserRole }>('/api/settings/current-role'),
  updateCurrentRole: (role: UserRole) => request<{ role: UserRole }>('/api/settings/current-role', { method: 'PUT', body: JSON.stringify({ role }) }),
  listProjectMembers: (projectId: string, includeInactive = false) => request<{ items: ProjectMember[] }>(`/api/projects/${projectId}/members${includeInactive ? '?include_inactive=true' : ''}`),
  createProjectMember: (projectId: string, payload: { display_name: string; role: UserRole }) =>
    request<ProjectMember>(`/api/projects/${projectId}/members`, { method: 'POST', body: JSON.stringify(payload) }),
  updateProjectMember: (projectId: string, memberId: string, patch: Partial<Pick<ProjectMember, 'display_name' | 'role' | 'status'>>) =>
    request<ProjectMember>(`/api/projects/${projectId}/members/${memberId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  importMasterData: (scope: 'projects' | 'sites' | 'subjects', file: File, projectId = '', siteId = '') => {
    const body = new FormData()
    body.append('file', file)
    body.append('project_id', projectId)
    body.append('site_id', siteId)
    body.append('actor_name', '项目管理员')
    return upload<{ summary: { total: number; created: number; updated: number; skipped: number }; errors: Array<{ row: number; message: string }> }>(`/api/imports/${scope}`, body)
  },
  previewMasterDataImport: (
    scope: 'projects' | 'sites' | 'subjects',
    file: File,
    projectId = '',
    siteId = '',
    source?: { system: string; reference: string; exported_at: string },
    importProfile?: { id: string; name: string; column_mapping: Record<string, string> },
  ) => {
    const body = new FormData()
    body.append('file', file)
    body.append('project_id', projectId)
    body.append('site_id', siteId)
    body.append('actor_name', '项目管理员')
    if (source) {
      body.append('source_system', source.system)
      body.append('source_reference', source.reference)
      body.append('source_exported_at', source.exported_at)
    }
    if (importProfile) {
      body.append('import_profile_id', importProfile.id)
      body.append('import_profile_name', importProfile.name)
      body.append('column_mapping_json', JSON.stringify(importProfile.column_mapping))
    }
    return upload<ImportBatch>(`/api/imports/${scope}/preview`, body)
  },
  getImportBatch: (batchId: string) => request<ImportBatch>(`/api/import-batches/${batchId}`),
  commitMasterDataImport: (batchId: string, actorName = '项目管理员') =>
    request<ImportBatch>(`/api/import-batches/${batchId}/commit`, { method: 'POST', body: JSON.stringify({ actor_name: actorName }) }),
  downloadImportErrorReport: (batchId: string) => downloadDocument(`/api/import-batches/${batchId}/error-report`, '导入错误行报告.csv'),
  updateProject: (project: ProjectInfo, visit: VisitInfo, recruitment: Recruitment) =>
    request<DemoState>('/api/project', {
      method: 'PUT',
      body: JSON.stringify({
        project: {
          study_name: project.study_name,
          study_id: project.study_id,
          site_name: project.site_name,
          pi_name: project.pi_name,
          sponsor: project.sponsor,
          approval_number: project.approval_number,
          protocol_version: project.protocol_version,
          icf_version: project.icf_version,
          ethics_date: project.ethics_date,
          sop_version: project.sop_version,
        },
        visit: {
          visit_type: visit.visit_type,
          visit_date: visit.visit_date,
          activity_start_date: visit.activity_start_date,
          visit_method: visit.visit_method,
          visit_location: visit.visit_location,
          contact_persons: visit.contact_persons,
          report_date: visit.report_date,
          site_team: visit.site_team,
          monitoring_team: visit.monitoring_team,
          next_visit: visit.next_visit,
          cra_name: visit.cra_name,
        },
        recruitment,
      }),
    }),
  addRecord: (text: string) =>
    request<{ state: DemoState }>('/api/records', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  createVisitRecord: (visitId: string, payload: { text: string; created_by?: string; record_kind?: 'monitoring_note' | 'center_explanation'; linked_task_id?: string; recorded_at?: string; client_created_at?: string; client_timezone?: string; tags?: string[]; client_idempotency_key?: string }) =>
    request<{ record: RecordItem; suggestions: Suggestion[]; workspace: DemoState; idempotent_reuse?: boolean; processing_deferred?: boolean }>(`/api/visits/${visitId}/records`, { method: 'POST', body: JSON.stringify(payload) }),
  previewVisitRecordDuplicates: (visitId: string, text: string) =>
    request<{ items: RecordItem[] }>(`/api/visits/${visitId}/records/duplicate-preview`, { method: 'POST', body: JSON.stringify({ text }) }),
  correctVisitRecord: (visitId: string, recordId: string, payload: { text: string; correction_reason: string; created_by?: string }) =>
    request<{ record: RecordItem; suggestions: Suggestion[]; workspace: DemoState }>(`/api/visits/${visitId}/records/${recordId}/corrections`, { method: 'POST', body: JSON.stringify(payload) }),
  voidVisitRecord: (visitId: string, recordId: string, payload: { reason: string; actor_name: string }) =>
    request<{ record: Pick<RecordItem, 'id' | 'record_status' | 'void_reason' | 'voided_at' | 'voided_by'>; affected: { suggestions: number; confirmed_fields: number; working_revisions: number }; workspace: DemoState }>(`/api/visits/${visitId}/records/${recordId}/void`, { method: 'POST', body: JSON.stringify(payload) }),
  getOfflineDrafts: (visitId: string) => request<{ items: OfflineDraft[]; conflicts: SyncConflict[]; sync_token: string }>(`/api/visits/${visitId}/offline-drafts`),
  syncOfflineDraft: (visitId: string, payload: { client_id: string; payload: { text: string }; base_updated_at: string; actor_name: string }) =>
    request<{ status: 'synced' | 'conflict'; draft: OfflineDraft; conflict?: SyncConflict }>(`/api/visits/${visitId}/offline-drafts/sync`, { method: 'POST', body: JSON.stringify(payload) }),
  resolveSyncConflict: (visitId: string, conflictId: string, resolution: 'local' | 'server', actorName: string) =>
    request<{ status: 'resolved'; resolution: 'local' | 'server'; conflict: SyncConflict; record: { id: string; text: string } | null }>(`/api/visits/${visitId}/sync-conflicts/${conflictId}/resolve`, { method: 'POST', body: JSON.stringify({ resolution, actor_name: actorName }) }),
  getVisitOperations: (visitId: string) => request<VisitOperations>(`/api/visits/${visitId}/operations`),
  createEscalation: (visitId: string, payload: { action_item_id?: string; title?: string; description?: string; severity: 'high' | 'urgent'; target_role: 'PM_LM' | 'PROJECT_ADMIN'; actor_name: string }) =>
    request<OperationEscalation>(`/api/visits/${visitId}/escalations`, { method: 'POST', body: JSON.stringify(payload) }),
  disposeEscalation: (visitId: string, escalationId: string, payload: { action: 'acknowledge' | 'close'; note?: string; actor_name: string }) =>
    request<OperationEscalation>(`/api/visits/${visitId}/escalations/${escalationId}/disposition`, { method: 'POST', body: JSON.stringify(payload) }),
  createHandover: (visitId: string, payload: { from_member_id?: string; to_member_id: string; note: string; actor_name: string }) =>
    request<VisitHandover>(`/api/visits/${visitId}/handovers`, { method: 'POST', body: JSON.stringify(payload) }),
  createAdministratorHandover: (visitId: string, payload: { from_member_id: string; to_member_id: string; reason: string; authorization_basis: string; note: string; actor_name: string }) =>
    request<VisitHandover>(`/api/visits/${visitId}/administrator-handovers`, { method: 'POST', body: JSON.stringify(payload) }),
  acknowledgeAdministratorHandover: (visitId: string, handoverId: string, payload: { acknowledgement_note: string; actor_name: string }) =>
    request<VisitHandover>(`/api/visits/${visitId}/handovers/${handoverId}/recipient-confirmation`, { method: 'POST', body: JSON.stringify(payload) }),
  bulkUpdateTasks: (visitId: string, payload: { task_ids: string[]; status: string; evidence: string; actor_name: string }) =>
    request<{ items: Array<{ id: string }>; workspace: DemoState }>(`/api/visits/${visitId}/tasks/bulk-update`, { method: 'POST', body: JSON.stringify(payload) }),
  updateVisitTask: (visitId: string, taskId: string, payload: TaskExecutionPatch) =>
    request<unknown>(`/api/visits/${visitId}/tasks/${taskId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  decideSuggestion: (id: string, decision: 'accepted' | 'edited' | 'rejected', editedText?: string, decisionReason?: string) =>
    request<DemoState>(`/api/suggestions/${id}/decision`, {
      method: 'POST',
      body: JSON.stringify({ decision, edited_text: editedText, decision_reason: decisionReason }),
    }),
  assignVisitSuggestionTarget: (visitId: string, suggestionId: string, payload: { target_task_id: string; actor_name: string }) =>
    request<{ item: { id: string; target_task_id: string; target_table: number; field_key: string; target_title: string }; workspace: DemoState }>(`/api/visits/${visitId}/suggestions/${suggestionId}/target-assignment`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  decideVisitSuggestionsBatch: (visitId: string, payload: { suggestion_ids: string[]; decision: 'accepted' | 'rejected'; actor_name: string }) =>
    request<{ items: Array<{ suggestion_id: string; decision: string; confirmed_field_id?: string; action_item_id?: string }>; workspace: DemoState }>(`/api/visits/${visitId}/suggestions/batch-decision`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  createActionItem: (visitId: string, payload: { title: string; description: string; owner: string; due_date?: string; finding_ids?: string[]; actor_name?: string }) =>
    request<ActionItem>(`/api/visits/${visitId}/action-items`, { method: 'POST', body: JSON.stringify(payload) }),
  updateActionItem: (visitId: string, actionItemId: string, patch: Partial<Pick<ActionItem, 'title' | 'description' | 'owner' | 'due_date' | 'status' | 'closure_note'>> & { status_change_note?: string; actor_name?: string }) =>
    request<ActionItem>(`/api/visits/${visitId}/action-items/${actionItemId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  replaceActionItemFindings: (visitId: string, actionItemId: string, findingIds: string[], actorName: string) =>
    request<ActionItem>(`/api/visits/${visitId}/action-items/${actionItemId}/findings`, { method: 'PUT', body: JSON.stringify({ finding_ids: findingIds, actor_name: actorName }) }),
  createHistoricalActionFollowUp: (visitId: string, sourceActionItemId: string, actorName: string) =>
    request<ActionItem>(`/api/visits/${visitId}/historical-actions/${sourceActionItemId}/follow-up`, { method: 'POST', body: JSON.stringify({ actor_name: actorName }) }),
  listActionItems: (visitId: string) => request<{ items: ActionItem[] }>(`/api/visits/${visitId}/action-items`),
  uploadAttachment: (visitId: string, file: File, actionItemId = '', description = '') => {
    const body = new FormData()
    body.append('file', file)
    body.append('action_item_id', actionItemId)
    body.append('description', description)
    body.append('actor_name', '演示 CRA')
    return upload<Attachment>(`/api/visits/${visitId}/attachments`, body)
  },
  generateVisitRevision: (visitId: string, createdBy: string) =>
    request<ReportRevision>(`/api/visits/${visitId}/revisions/generate`, { method: 'POST', body: JSON.stringify({ created_by: createdBy }) }),
  getReportReadiness: (visitId: string) => request<ReportReadiness>(`/api/visits/${visitId}/report-readiness`),
  submitRevision: (revisionId: string, craName: string, confirmed: boolean) =>
    request<ReportRevision>(`/api/revisions/${revisionId}/submit`, { method: 'POST', body: JSON.stringify({ cra_name: craName, confirmed }) }),
  withdrawRevision: (revisionId: string, payload: { cra_name: string; reason: string }) =>
    request<{ withdrawn_revision: ReportRevision; working_revision: ReportRevision; workspace: DemoState }>(`/api/revisions/${revisionId}/withdraw`, { method: 'POST', body: JSON.stringify(payload) }),
  voidRevision: (revisionId: string, payload: { actor_name: string; reason: string }) =>
    request<{ voided_revision: ReportRevision; working_revision: ReportRevision; workspace: DemoState }>(`/api/revisions/${revisionId}/void`, { method: 'POST', body: JSON.stringify(payload) }),
  startRevisionReview: (revisionId: string, reviewerName: string) =>
    request<{ revision: ReportRevision; workspace: DemoState }>(`/api/revisions/${revisionId}/review-start`, { method: 'POST', body: JSON.stringify({ reviewer_name: reviewerName }) }),
  downloadRevision: (revisionId: string) => downloadDocument(`/api/revisions/${revisionId}/download`, '监查报告.docx'),
  downloadAuditExport: (visitId: string) => downloadDocument(`/api/visits/${visitId}/audit-export`, 'audit_trail.csv'),
  downloadHandoverPackage: (revisionId: string) => downloadDocument(`/api/revisions/${revisionId}/handover-package`, 'signature_handover.zip'),
  getEvidenceChain: (visitId: string) => request<EvidenceChain>(`/api/visits/${visitId}/evidence-chain`),
  generateLanguageSuggestions: (visitId: string, actorName: string) =>
    request<{ items: LanguageSuggestion[] }>(`/api/visits/${visitId}/language-suggestions/generate`, { method: 'POST', body: JSON.stringify({ created_by: actorName }) }),
  decideLanguageSuggestion: (visitId: string, suggestionId: string, payload: { decision: 'accepted' | 'edited' | 'rejected'; actor_name: string; edited_text?: string }) =>
    request<{ item: LanguageSuggestion }>(`/api/visits/${visitId}/language-suggestions/${suggestionId}/decision`, { method: 'POST', body: JSON.stringify(payload) }),
  revokeLanguageSuggestion: (visitId: string, suggestionId: string, payload: { actor_name: string; reason: string }) =>
    request<{ item: LanguageSuggestion }>(`/api/visits/${visitId}/language-suggestions/${suggestionId}/revoke`, { method: 'POST', body: JSON.stringify(payload) }),
  reviewRevision: (revisionId: string, payload: { action: 'comment' | 'returned' | 'approved'; message: string; reviewer_name: string; target_key?: string }) =>
    request<ReviewComment>(`/api/revisions/${revisionId}/reviews`, { method: 'POST', body: JSON.stringify(payload) }),
  createSpecialistReviewComment: (revisionId: string, payload: { action: 'specialist_comment' | 'specialist_concurrence'; message: string; reviewer_name: string; target_key?: string }) =>
    request<ReviewComment>(`/api/revisions/${revisionId}/specialist-comments`, { method: 'POST', body: JSON.stringify(payload) }),
  resolveReviewComment: (visitId: string, commentId: string, payload: { resolution: 'accepted' | 'declined'; note: string; actor_name: string }) =>
    request<{ item: ReviewComment }>(`/api/visits/${visitId}/review-comments/${commentId}/resolve`, { method: 'POST', body: JSON.stringify(payload) }),
  submit: (craName: string) =>
    request<DemoState>('/api/report/submit', {
      method: 'POST',
      body: JSON.stringify({ cra_name: craName }),
    }),
  review: (action: 'comment' | 'returned' | 'approved', message: string, reviewerName: string) =>
    request<DemoState>('/api/reviews', {
      method: 'POST',
      body: JSON.stringify({ action, message, reviewer_name: reviewerName }),
    }),
  reset: () => request<DemoState>('/api/reset', { method: 'POST' }),
  generateReport: () => downloadDocument('/api/report/generate', '监查报告_Demo.docx'),
}

export const reportStatusLabel: Record<ReportStatus, string> = {
  draft: '草稿',
  submitted: '待审核',
  returned: '已退回',
  withdrawn: 'CRA 已撤回',
  approved: '已批准',
  voided: '已作废',
  cancelled: '已取消',
}

export const workflowStageLabel: Record<WorkflowStage, string> = {
  draft: '草稿',
  pending_cra_confirmation: '待 CRA 确认',
  ready_to_submit: '可提交',
  under_review: '待审核',
  returned: '已退回',
  approved: '已批准',
  cancelled: '已取消',
}
