import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../api'
import type { ConfigurationApprovalAction, TemplateDetail, TemplateFieldSlot, TemplateFieldSlotSuggestion, TemplateFieldSlotTargetKind, TemplateMapping, TemplateMappingSuggestion, TemplateSummary, UserRole } from '../types'
import { buildTemplateMappingReferenceRows, templateMappingReferenceLabel } from '../templateMappingReference'
import { readTemplateCompletenessRules, templateFieldCompletenessLabels, templateTaskCompletenessLabels, type TemplateCompletenessRules } from '../templateCompletenessRules'

interface TemplatesPageProps {
  currentRole: UserRole
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

type MappingPatch = Partial<Pick<TemplateMapping, 'field_key' | 'target_description' | 'required'>>
type FieldSlotPatch = Partial<Pick<TemplateFieldSlot, 'table_index' | 'target_kind' | 'label' | 'field_key' | 'target_locator' | 'value_source' | 'required'>>
type FieldSlotDraft = Omit<TemplateFieldSlot, 'id' | 'template_id' | 'created_at'>
type FieldSlotTargetPatch = Pick<TemplateFieldSlot, 'table_index' | 'target_kind' | 'target_locator'>
type FieldSlotTargetCandidate = {
  target_kind: TemplateFieldSlotTargetKind
  target_locator: string
  label: string
  preview: string
  table_index: number
}

const fieldSlotSourceOptions = [
  { value: 'confirmed_text', label: 'CRA 已确认文本（按字段键）' },
  { value: 'summary', label: '本次监查总体评价' },
  { value: 'project.study_name', label: '项目：研究名称' },
  { value: 'project.study_id', label: '项目：方案编号' },
  { value: 'project.sponsor', label: '项目：申办方' },
  { value: 'project.approval_number', label: '项目：立项/批件号' },
  { value: 'project.sop_version', label: '项目：SOP 版本' },
  { value: 'site.site_name', label: '中心：名称' },
  { value: 'site.pi_name', label: '中心：PI' },
  { value: 'site.protocol_version', label: '中心：方案版本' },
  { value: 'site.icf_version', label: '中心：知情同意书版本' },
  { value: 'site.ethics_date', label: '中心：伦理日期' },
  { value: 'visit.activity_period', label: '访视：监查活动周期' },
  { value: 'visit.visit_method', label: '访视：监查方式' },
  { value: 'visit.report_date', label: '访视：报告日期' },
  { value: 'visit.site_team', label: '访视：中心团队' },
  { value: 'visit.monitoring_team', label: '访视：监查团队' },
  { value: 'visit.next_visit', label: '访视：下次访视计划' },
]

const fieldSlotTargetKindOptions: Array<{ value: TemplateFieldSlotTargetKind; label: string }> = [
  { value: 'table_cell', label: '表格单元格' },
  { value: 'body_paragraph', label: '正文段落' },
  { value: 'header_paragraph', label: '页眉段落' },
  { value: 'footer_paragraph', label: '页脚段落' },
  { value: 'inline_token', label: '内联标记 {{…}}' },
  { value: 'content_control', label: 'Word 内容控件' },
  { value: 'bookmark', label: 'Word 书签' },
  { value: 'merge_field', label: 'Word 合并字段' },
]

const fieldSlotTargetLocatorPlaceholder = (targetKind: TemplateFieldSlotTargetKind) => {
  if (targetKind === 'table_cell') return 'T2:R1:C3'
  if (targetKind === 'inline_token') return 'P1:{{字段}}'
  if (targetKind === 'content_control') return 'SDT:<标记> / SDT_ALIAS:<别名>'
  if (targetKind === 'bookmark') return 'BM:<书签名称>'
  if (targetKind === 'merge_field') return 'FIELD:<字段名称>'
  return 'P1 / H1:P1 / F1:P1'
}

const configurationStatusLabel: Record<string, string> = {
  draft: '草稿配置中',
  pending_approval: '待 QA/临床运营审批',
  active: '已启用',
  rejected: '已退回',
  inactive: '已停用',
}

export function TemplatesPage({ currentRole, onNotice }: TemplatesPageProps) {
  const [templates, setTemplates] = useState<TemplateSummary[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [detail, setDetail] = useState<TemplateDetail | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [revisionDocumentFile, setRevisionDocumentFile] = useState<File | null>(null)
  const [configurationPackageFile, setConfigurationPackageFile] = useState<File | null>(null)
  const [displayName, setDisplayName] = useState('')
  const [version, setVersion] = useState('V1.0')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [reviewNote, setReviewNote] = useState('')
  const [revisionDraftName, setRevisionDraftName] = useState('')
  const [revisionDraftVersion, setRevisionDraftVersion] = useState('')
  const [visitTypeKeywords, setVisitTypeKeywords] = useState('')
  const [newFieldSlot, setNewFieldSlot] = useState<FieldSlotDraft>({ table_index: 1, target_kind: 'table_cell', label: '', field_key: 'table_1', target_locator: '', value_source: 'confirmed_text', required: 0 })
  const [mappingReferenceTemplateId, setMappingReferenceTemplateId] = useState('')
  const [mappingReferenceDetail, setMappingReferenceDetail] = useState<TemplateDetail | null>(null)
  const [mappingReferenceLoading, setMappingReferenceLoading] = useState(false)
  const [completenessRules, setCompletenessRules] = useState<TemplateCompletenessRules>({ task_mode: 'mapping_required', field_mode: 'slot_required' })
  const matchingProfile = detail?.matching_profile
  const administratorKeywords = matchingProfile?.administrator_keywords ?? []
  const configurationReadiness = detail?.configuration_readiness
  const fieldSlotTargetCandidates = (targetKind: TemplateFieldSlotTargetKind): FieldSlotTargetCandidate[] => {
    if (!detail) return []
    if (targetKind === 'table_cell') {
      return detail.detected_tables.map((table) => ({
        target_kind: 'table_cell',
        target_locator: table.suggested_target_locator ?? '',
        label: `第 ${table.table_index} 表：${table.detected_label}`,
        preview: `${table.row_count} 行 × ${table.column_count} 列`,
        table_index: table.table_index,
      }))
    }
    return detail.detected_text_targets
      .filter((target) => target.target_kind === targetKind)
      .map((target) => ({ ...target, table_index: 0 }))
  }

  const loadTemplates = async (preferredId = '') => {
    try {
      setLoading(true)
      const response = await api.listTemplates(true)
      setTemplates(response.items)
      const targetId = preferredId || response.items.find((item) => item.id === selectedTemplateId)?.id || response.items[0]?.id || ''
      setSelectedTemplateId(targetId)
      setDetail(targetId ? await api.getTemplate(targetId) : null)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '载入模板库失败', 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadTemplates() }, [])

  useEffect(() => {
    setVisitTypeKeywords(administratorKeywords.join(', '))
  }, [detail?.template.id, administratorKeywords.join('|')])

  useEffect(() => {
    const firstTable = detail?.detected_tables[0]
    setNewFieldSlot({
      table_index: firstTable?.table_index ?? 1,
      target_kind: 'table_cell',
      label: '',
      field_key: `table_${firstTable?.table_index ?? 1}`,
      target_locator: firstTable?.suggested_target_locator ?? '',
      value_source: 'confirmed_text',
      required: 0,
    })
    setMappingReferenceTemplateId('')
    setMappingReferenceDetail(null)
    setConfigurationPackageFile(null)
    setCompletenessRules(readTemplateCompletenessRules(detail?.template.metadata))
  }, [detail?.template.id])

  const selectTemplate = async (templateId: string) => {
    try {
      setSelectedTemplateId(templateId)
      setDetail(await api.getTemplate(templateId))
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '读取模板详情失败', 'error')
    }
  }

  const selectMappingReference = async (templateId: string) => {
    setMappingReferenceTemplateId(templateId)
    if (!templateId) {
      setMappingReferenceDetail(null)
      return
    }
    try {
      setMappingReferenceLoading(true)
      setMappingReferenceDetail(await api.getTemplate(templateId))
    } catch (error) {
      setMappingReferenceDetail(null)
      onNotice(error instanceof Error ? error.message : '读取历史模板映射失败', 'error')
    } finally {
      setMappingReferenceLoading(false)
    }
  }

  const uploadTemplate = async (event: FormEvent) => {
    event.preventDefault()
    if (!file) {
      onNotice('请选择一个 .docx 监查报告模板。', 'error')
      return
    }
    try {
      setBusy(true)
      const uploaded = await api.uploadTemplate(file, displayName, version)
      setFile(null)
      setDisplayName('')
      setVersion('V1.0')
      await loadTemplates(uploaded.template.id)
      const highConfidenceSuggestions = uploaded.mapping_suggestions.filter((item) => item.confidence === 'high').length
      onNotice(`已识别并登记 ${uploaded.detected_tables.length} 张表，生成 ${uploaded.mapping_suggestions.length} 项映射建议（高置信度 ${highConfidenceSuggestions} 项）和 ${uploaded.field_slot_suggestions.length} 项固定资料填写位建议，请管理员确认。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '模板上传失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const downloadConfigurationPackage = async () => {
    if (!detail) return
    try {
      setBusy(true)
      const fileName = await api.downloadTemplateConfigurationPackage(
        detail.template.id,
        `${detail.template.name || 'monitoring-template'}-${detail.template.version || 'V1.0'}-configuration.json`,
      )
      onNotice(`已下载模板配置包：${fileName}。配置包不包含原始 Word 文件。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '下载模板配置包失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const importConfigurationPackage = async () => {
    if (!detail || !configurationPackageFile) return
    try {
      setBusy(true)
      const result = await api.importTemplateConfigurationPackage(detail.template.id, configurationPackageFile)
      setDetail(result.detail)
      setTemplates((current) => current.map((item) => item.id === result.detail.template.id ? result.detail.template : item))
      setConfigurationPackageFile(null)
      onNotice(`已带入 ${result.source_template.name}${result.source_template.version ? ` ${result.source_template.version}` : ''} 的配置包：映射 ${result.applied_mapping_count}/${result.source_mapping_count}，填写位 ${result.applied_field_slot_count}/${result.source_field_slot_count}。请复核当前草稿后保存或提交审批。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '带入模板配置包失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const updateLocalMapping = (mappingId: string, patch: MappingPatch) => {
    setDetail((current) => current ? {
      ...current,
      mappings: current.mappings.map((mapping) => mapping.id === mappingId ? { ...mapping, ...patch } : mapping),
    } : current)
  }

  const adoptMappingReference = (targetMappingId: string, sourceMapping: TemplateMapping) => {
    updateLocalMapping(targetMappingId, {
      field_key: sourceMapping.field_key,
      target_description: sourceMapping.target_description,
      required: sourceMapping.required,
    })
    onNotice('已带入参考映射到当前草稿；请核对表结构后，点击当前行“保存”生效。')
  }

  const adoptMappingSuggestion = (mapping: TemplateMapping, suggestion: TemplateMappingSuggestion) => {
    updateLocalMapping(mapping.id, {
      field_key: suggestion.field_key,
      target_description: suggestion.target_description,
    })
    onNotice(`已带入第 ${mapping.table_index} 表的识别建议；请确认是否必填，并点击“保存”生效。`)
  }

  const saveMapping = async (mapping: TemplateMapping) => {
    if (!detail) return
    try {
      setBusy(true)
      const updated = await api.patchTemplateMapping(detail.template.id, mapping.id, {
        field_key: mapping.field_key,
        target_description: mapping.target_description,
        required: mapping.required,
      })
      setDetail(updated)
      setTemplates((current) => current.map((item) => item.id === updated.template.id ? updated.template : item))
      onNotice(`已保存第 ${mapping.table_index} 张表的映射。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '保存映射失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const updateLocalFieldSlot = (slotId: string, patch: FieldSlotPatch) => {
    setDetail((current) => current ? {
      ...current,
      field_slots: current.field_slots.map((slot) => slot.id === slotId ? { ...slot, ...patch } : slot),
    } : current)
  }

  const targetPatchForKind = (targetKind: TemplateFieldSlotTargetKind): FieldSlotTargetPatch => {
    const candidate = fieldSlotTargetCandidates(targetKind)[0]
    return {
      target_kind: targetKind,
      table_index: candidate?.table_index ?? (targetKind === 'table_cell' ? 1 : 0),
      target_locator: candidate?.target_locator ?? '',
    }
  }

  const updateNewFieldSlotTargetKind = (targetKind: TemplateFieldSlotTargetKind) => {
    const patch = targetPatchForKind(targetKind)
    setNewFieldSlot((current) => ({
      ...current,
      ...patch,
      field_key: targetKind === 'table_cell' ? `table_${patch.table_index ?? 1}` : current.field_key,
    }))
  }

  const chooseNewFieldSlotTarget = (targetLocator: string) => {
    const candidate = fieldSlotTargetCandidates(newFieldSlot.target_kind).find((target) => target.target_locator === targetLocator)
    setNewFieldSlot((current) => ({ ...current, target_locator: targetLocator, table_index: candidate?.table_index ?? current.table_index }))
  }

  const chooseExistingFieldSlotTarget = (slot: TemplateFieldSlot, targetLocator: string) => {
    const targetKind = slot.target_kind ?? 'table_cell'
    const candidate = fieldSlotTargetCandidates(targetKind).find((target) => target.target_locator === targetLocator)
    updateLocalFieldSlot(slot.id, { target_locator: targetLocator, table_index: candidate?.table_index ?? slot.table_index })
  }

  const chooseExistingFieldSlotTable = (slot: TemplateFieldSlot, tableIndex: number) => {
    const candidate = fieldSlotTargetCandidates('table_cell').find((target) => target.table_index === tableIndex)
    updateLocalFieldSlot(slot.id, { table_index: tableIndex, target_locator: candidate?.target_locator ?? slot.target_locator })
  }

  const adoptFieldSlotSuggestion = (suggestion: TemplateFieldSlotSuggestion) => {
    setNewFieldSlot({
      table_index: suggestion.table_index,
      target_kind: suggestion.target_kind,
      label: suggestion.label,
      field_key: suggestion.field_key,
      target_locator: suggestion.target_locator,
      value_source: suggestion.value_source,
      required: 0,
    })
    onNotice(`已带入“${suggestion.label}”填写位草稿；请核对目标位置和必填标记，再点击“新增填写位”保存。`)
  }

  const saveFieldSlot = async (slot: TemplateFieldSlot) => {
    if (!detail) return
    try {
      setBusy(true)
      const updated = await api.patchTemplateFieldSlot(detail.template.id, slot.id, {
        table_index: slot.table_index,
        target_kind: slot.target_kind,
        label: slot.label,
        field_key: slot.field_key,
        target_locator: slot.target_locator,
        value_source: slot.value_source,
        required: slot.required,
      })
      setDetail(updated)
      setTemplates((current) => current.map((item) => item.id === updated.template.id ? updated.template : item))
      onNotice('报告填写位已保存。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '保存报告填写位失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const addFieldSlot = async (event: FormEvent) => {
    event.preventDefault()
    if (!detail) return
    try {
      setBusy(true)
      const updated = await api.createTemplateFieldSlot(detail.template.id, newFieldSlot)
      setDetail(updated)
      setTemplates((current) => current.map((item) => item.id === updated.template.id ? updated.template : item))
      onNotice('已新增报告填写位，可继续配置来源和目标位置。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '新增报告填写位失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const importHighConfidenceFieldSlotSuggestions = async () => {
    if (!detail) return
    try {
      setBusy(true)
      const result = await api.importHighConfidenceTemplateFieldSlotSuggestions(detail.template.id)
      setDetail(result.detail)
      setTemplates((current) => current.map((item) => item.id === result.detail.template.id ? result.detail.template : item))
      onNotice(`已处理 ${result.candidate_count} 项高置信度建议：新增 ${result.created_count} 项、更新默认填写位 ${result.adopted_default_count} 项、保留已有配置 ${result.skipped_existing_count} 项。请复核后提交审批。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '导入高置信度填写位建议失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const importHighConfidenceMappingSuggestions = async () => {
    if (!detail) return
    try {
      setBusy(true)
      const result = await api.importHighConfidenceTemplateMappingSuggestions(detail.template.id)
      setDetail(result.detail)
      setTemplates((current) => current.map((item) => item.id === result.detail.template.id ? result.detail.template : item))
      onNotice(`已处理 ${result.candidate_count} 项高置信度映射建议：带入 ${result.adopted_count} 项、保留已有配置 ${result.skipped_existing_count} 项、未找到对应映射 ${result.missing_mapping_count} 项。请复核后提交审批。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '导入高置信度映射建议失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const removeFieldSlot = async (slot: TemplateFieldSlot) => {
    if (!detail) return
    try {
      setBusy(true)
      const updated = await api.deleteTemplateFieldSlot(detail.template.id, slot.id)
      setDetail(updated)
      setTemplates((current) => current.map((item) => item.id === updated.template.id ? updated.template : item))
      onNotice('报告填写位已移除。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '移除报告填写位失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const saveVisitTypeKeywords = async () => {
    if (!detail) return
    const keywords = visitTypeKeywords.split(/[,，;；\n\r]+/).map((item) => item.trim()).filter(Boolean)
    try {
      setBusy(true)
      const updated = await api.patchTemplateVisitTypeKeywords(detail.template.id, keywords)
      setDetail(updated)
      setTemplates((current) => current.map((item) => item.id === updated.template.id ? updated.template : item))
      onNotice(keywords.length ? '模板适用访视关键词已保存，将优先用于后续推荐。' : '已清空管理员确认关键词，后续仅使用自动识别特征。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '保存适用访视关键词失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const saveCompletenessRules = async () => {
    if (!detail) return
    try {
      setBusy(true)
      const updated = await api.patchTemplateCompletenessRules(detail.template.id, completenessRules)
      setDetail(updated)
      setTemplates((current) => current.map((item) => item.id === updated.template.id ? updated.template : item))
      onNotice('模板完整性规则已保存；新建访视和后续模板切换会冻结该规则。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '保存模板完整性规则失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const isAdmin = currentRole === 'PROJECT_ADMIN'
  const isQaReviewer = currentRole === 'QA_CLINICAL_OPS'
  const templateStatus = detail?.template.status ?? ''
  const isEditable = isAdmin && ['draft', 'rejected'].includes(templateStatus)
  const mappingReferenceCandidates = templates.filter((template) => template.id !== detail?.template.id && template.status === 'active')
  const mappingReferenceRows = detail && mappingReferenceDetail
    ? buildTemplateMappingReferenceRows(detail.mappings, mappingReferenceDetail.mappings)
    : []

  const runApprovalAction = async (action: ConfigurationApprovalAction) => {
    if (!detail) return
    try {
      setBusy(true)
      const updated = await api.templateApprovalAction(detail.template.id, {
        action,
        actor_name: isQaReviewer ? '演示 QA/临床运营审批人' : '项目管理员',
        note: reviewNote,
      })
      setDetail(updated)
      setTemplates((current) => current.map((item) => item.id === updated.template.id ? updated.template : item))
      setReviewNote('')
      onNotice(action === 'approve' ? '模板已获批准并启用，可供新建访视选择。' : action === 'reject' ? '模板已退回配置人处理。' : action === 'submit' ? '模板已提交 QA/临床运营审批。' : action === 'withdraw' ? '模板审批已撤回，已回到草稿。' : '模板已停用，后续新访视不可再选用。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '模板审批操作失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const createRevisionDraft = async () => {
    if (!detail) return
    try {
      setBusy(true)
      const created = await api.createTemplateRevisionDraft(detail.template.id, {
        name: revisionDraftName,
        version: revisionDraftVersion,
        actor_name: '项目管理员',
      })
      setRevisionDraftName('')
      setRevisionDraftVersion('')
      await loadTemplates(created.template.id)
      onNotice(`已基于 ${detail.template.version} 创建 ${created.template.version} 修订草稿；映射、填写位和完整性规则已带入，请复核后提交审批。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '创建模板修订草稿失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const replaceRevisionDocument = async () => {
    if (!detail || !revisionDocumentFile) return
    try {
      setBusy(true)
      const updated = await api.replaceTemplateRevisionDocument(detail.template.id, revisionDocumentFile)
      setRevisionDocumentFile(null)
      setDetail(updated)
      setTemplates((current) => current.map((item) => item.id === updated.template.id ? updated.template : item))
      const replacement = updated.template.metadata.document_replacement_summary as { reused_mapping_count?: number; removed_field_slot_count?: number } | undefined
      onNotice(`新版 Word 已替换并重新识别。沿用 ${replacement?.reused_mapping_count ?? 0} 项同表号映射；${replacement?.removed_field_slot_count ?? 0} 个已无法定位的填写位未带入，请复核后再提交审批。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '替换修订草稿 Word 文件失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const sourceFileName = detail && typeof detail.template.metadata.source_file_name === 'string'
    ? detail.template.metadata.source_file_name
    : ''
  const revisionOf = detail && typeof detail.template.metadata.revision_of === 'object' && detail.template.metadata.revision_of !== null
    ? detail.template.metadata.revision_of as { name?: string; version?: string }
    : null
  const documentReplacement = detail && typeof detail.template.metadata.document_replacement_summary === 'object' && detail.template.metadata.document_replacement_summary !== null
    ? detail.template.metadata.document_replacement_summary as { reused_mapping_count?: number; source_mapping_count?: number; reused_field_slot_count?: number; source_field_slot_count?: number; removed_field_slot_count?: number; removed_field_slot_labels?: string[]; unchanged_table_count?: number; changed_table_count?: number; added_table_count?: number; removed_table_count?: number; table_changes?: Array<{ table_index: number; status: 'unchanged' | 'changed' | 'added' | 'removed'; previous_label: string; current_label: string; previous_row_count: number; previous_column_count: number; current_row_count: number; current_column_count: number }> }
    : null
  const changedReplacementTables = (documentReplacement?.table_changes ?? []).filter((item) => item.status !== 'unchanged')
  const activationCheck = detail?.template.metadata.activation_check as { passed?: boolean; test_generated_table_count?: number } | undefined

  return (
    <div className="template-stack">
      <section className="template-brief">
        <div>
          <p className="eyebrow">DOCX TEMPLATE LIBRARY</p>
          <h2>报告模板与表格映射</h2>
          <p>上传申办方 Word 模板后，系统识别其表格结构；项目管理员确认每张表对应的监查区域，CRA 创建访视时即可直接选用。</p>
        </div>
        <dl className="template-stats">
          <div><dt>可用模板</dt><dd>{templates.length}</dd></div>
          <div><dt>当前表格</dt><dd>{detail?.template.table_count ?? '—'}</dd></div>
          <div><dt>已标为必填</dt><dd>{detail?.mappings.filter((item) => Boolean(item.required)).length ?? '—'}</dd></div>
        </dl>
      </section>

      {!isAdmin && !isQaReviewer && <div className="role-readonly-card"><strong>当前为只读模板视图</strong><span>请切换为项目管理员配置模板，或切换为 QA / 临床运营审批人处理待审批版本。</span></div>}
      <div className="template-layout">
        <section className="section-block template-register">
          <div className="section-header compact-header"><div><h2>模板台账</h2><p>模板文件与映射配置独立留存。</p></div><span className="section-code">TEMPLATE</span></div>
          <div className="template-list" role="list">
            {loading ? <div className="empty-state"><span>正在载入模板…</span></div> : templates.length === 0 ? <div className="empty-state"><strong>尚无可用模板</strong><span>请在右侧上传一个 Word 模板。</span></div> : templates.map((template) => (
              <button key={template.id} type="button" role="listitem" className={`template-row ${template.id === selectedTemplateId ? 'is-selected' : ''}`} onClick={() => void selectTemplate(template.id)}>
                <span className="project-code">{template.version}</span>
                <strong>{template.name}</strong>
                <small>{configurationStatusLabel[template.status] ?? template.status} · {template.table_count} 张表 · {template.created_at}</small>
              </button>
            ))}
          </div>
        </section>

        <div className="template-detail">
          <section className="section-block template-upload">
            <div className="section-header"><div><h2>登记 Word 模板</h2><p>当前 MVP 只支持可编辑的 `.docx`；扫描件与 PDF 识别将在后续版本接入。</p></div><span className="section-code">UPLOAD</span></div>
            <form className="template-upload-form" onSubmit={uploadTemplate}>
              <label className="file-field">选择 `.docx` 文件<input type="file" disabled={!isAdmin} accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => { const selected = event.target.files?.[0] ?? null; setFile(selected); if (selected && !displayName) setDisplayName(selected.name.replace(/\.docx$/i, '')) }} /><small>{file ? file.name : '尚未选择文件'}</small></label>
              <label>模板名称<input value={displayName} disabled={!isAdmin} onChange={(event) => setDisplayName(event.target.value)} placeholder="例如：首例筛选监查访视报告" /></label>
              <label>版本号<input value={version} disabled={!isAdmin} onChange={(event) => setVersion(event.target.value)} placeholder="例如：V1.0" /></label>
              <button type="submit" className="button primary" disabled={!isAdmin || busy || !file}>{busy ? '正在识别…' : '上传并识别表格'}</button>
            </form>
          </section>

          <section className="section-block mapping-ledger">
            <div className="section-header">
              <div>
                <p className="eyebrow">MAPPING LEDGER</p>
                <h2>{detail?.template.name ?? '请选择一个模板'}</h2>
                <p>{detail ? `${detail.template.version} · ${detail.template.table_count} 张表 · 原文件：${sourceFileName || '已留存'}` : '上传或选择模板后，在此确认自动识别结果与监查任务名称。'}</p>
                {revisionOf && <p className="template-revision-lineage">修订自：{revisionOf.name || '原模板'} {revisionOf.version ? `· ${revisionOf.version}` : ''}</p>}
              </div>
              {detail && <span className={`configuration-status status-${detail.template.status}`}>{configurationStatusLabel[detail.template.status] ?? detail.template.status}</span>}
            </div>
            {!detail ? <div className="empty-state"><strong>尚未选择模板</strong><span>从左侧台账选择，或先登记一个 Word 模板。</span></div> : (
              <>
                <div className="configuration-control-card">
                  <div><strong>启用控制</strong><span>管理员完成映射后提交；QA / 临床运营审批通过后，模板才会进入新访视可选清单。</span></div>
                  <dl className="configuration-facts"><div><dt>提交</dt><dd>{detail.template.submitted_at ? `${detail.template.submitted_by || '—'} · ${detail.template.submitted_at}` : '尚未提交'}</dd></div><div><dt>审批</dt><dd>{detail.template.reviewed_at ? `${detail.template.reviewed_by || '—'} · ${detail.template.reviewed_at}` : '尚未审批'}</dd></div></dl>
                  {detail.template.review_note && <p className="configuration-note"><strong>最新意见：</strong>{detail.template.review_note}</p>}
                  {activationCheck && <p className="configuration-check">结构检查：{activationCheck.passed ? `已通过（${activationCheck.test_generated_table_count ?? '—'} 张表测试生成）` : '待重新检查'}</p>}
                  {(isAdmin || isQaReviewer) && <label className="configuration-note-input">审批意见 / 退回理由<textarea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} disabled={busy || (!isAdmin && !isQaReviewer)} placeholder="批准时可补充说明；退回时必须填写原因。" /></label>}
                  <div className="configuration-actions">
                    {isAdmin && ['draft', 'rejected'].includes(detail.template.status) && <button type="button" className="button primary" disabled={busy} onClick={() => void runApprovalAction('submit')}>提交审批</button>}
                    {isAdmin && detail.template.status === 'pending_approval' && <button type="button" className="button quiet" disabled={busy} onClick={() => void runApprovalAction('withdraw')}>撤回审批</button>}
                    {isAdmin && detail.template.status === 'active' && <button type="button" className="button quiet" disabled={busy} onClick={() => void runApprovalAction('deactivate')}>停用模板</button>}
                    {isQaReviewer && detail.template.status === 'pending_approval' && <><button type="button" className="button primary" disabled={busy} onClick={() => void runApprovalAction('approve')}>批准并启用</button><button type="button" className="button danger" disabled={busy || !reviewNote.trim()} onClick={() => void runApprovalAction('reject')}>退回配置</button></>}
                  </div>
                  {isAdmin && ['active', 'inactive'].includes(detail.template.status) && <div className="template-revision-draft">
                    <div><strong>创建修订草稿</strong><span>复用当前模板的 Word 文件、映射、填写位、匹配关键词和完整性规则；历史访视继续使用其已冻结版本。</span></div>
                    <label>名称（可选）<input value={revisionDraftName} disabled={busy} onChange={(event) => setRevisionDraftName(event.target.value)} placeholder={detail.template.name} /></label>
                    <label>新版本号（可选）<input value={revisionDraftVersion} disabled={busy} onChange={(event) => setRevisionDraftVersion(event.target.value)} placeholder={`${detail.template.version}-R1`} /></label>
                    <button type="button" className="button small" disabled={busy} onClick={() => void createRevisionDraft()}>创建修订草稿</button>
                  </div>}
                </div>
                {isEditable && <div className="template-document-replacement">
                  <div><strong>替换修订草稿的 Word 文件</strong><span>仅适用于当前修订草稿／已退回模板。系统会重新识别表格和文本目标，并仅带入能在新文件中继续定位的填写位。</span></div>
                  <label className="file-field">选择新版 `.docx`<input type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" disabled={busy} onChange={(event) => setRevisionDocumentFile(event.target.files?.[0] ?? null)} /><small>{revisionDocumentFile ? revisionDocumentFile.name : '尚未选择新版 Word 文件'}</small></label>
                  <button type="button" className="button small" disabled={busy || !revisionDocumentFile} onClick={() => void replaceRevisionDocument()}>替换并重新识别</button>
                </div>}
                {documentReplacement && <div className="template-document-replacement-summary"><strong>最近一次 Word 替换</strong><span>映射沿用 {documentReplacement.reused_mapping_count ?? 0} / {documentReplacement.source_mapping_count ?? 0}；填写位沿用 {documentReplacement.reused_field_slot_count ?? 0} / {documentReplacement.source_field_slot_count ?? 0}；表格未变 {documentReplacement.unchanged_table_count ?? 0}、变更 {documentReplacement.changed_table_count ?? 0}、新增 {documentReplacement.added_table_count ?? 0}、移除 {documentReplacement.removed_table_count ?? 0}。</span>{documentReplacement.removed_field_slot_count ? <small>未带入 {documentReplacement.removed_field_slot_count} 个无法定位的填写位：{(documentReplacement.removed_field_slot_labels ?? []).join('、')}</small> : <small>全部原填写位均可在当前 Word 中继续定位。</small>}{changedReplacementTables.length ? <div className="template-table-change-list">{changedReplacementTables.map((change) => <article key={`${change.status}:${change.table_index}`} className={`table-change-${change.status}`}><strong>第 {change.table_index} 表 · {change.status === 'added' ? '新增' : change.status === 'removed' ? '移除' : '结构或标题变更'}</strong><span>{change.status === 'added' ? `${change.current_label || '未识别标题'} · ${change.current_row_count} 行 × ${change.current_column_count} 列` : change.status === 'removed' ? `${change.previous_label || '未识别标题'} · 原 ${change.previous_row_count} 行 × ${change.previous_column_count} 列` : `${change.previous_label || '未识别标题'}（${change.previous_row_count} × ${change.previous_column_count}） → ${change.current_label || '未识别标题'}（${change.current_row_count} × ${change.current_column_count}）`}</span></article>)}</div> : null}</div>}
                {isAdmin && <section className="template-configuration-package" aria-labelledby="template-configuration-package-heading">
                  <div className="template-configuration-package-heading">
                    <div>
                      <p className="eyebrow">CONFIGURATION PACKAGE</p>
                      <h3 id="template-configuration-package-heading">配置包复用</h3>
                      <p>导出映射、报告填写位、适用访视关键词和完整性规则为本地 JSON；可带入另一份草稿模板，不包含或替换任何 Word 文件。</p>
                    </div>
                    <button type="button" className="button quiet small" disabled={busy} onClick={() => void downloadConfigurationPackage()}>导出当前配置包</button>
                  </div>
                  {isEditable ? <div className="template-configuration-package-import">
                    <label className="file-field">选择 JSON 配置包<input type="file" accept=".json,application/json" disabled={busy} onChange={(event) => setConfigurationPackageFile(event.target.files?.[0] ?? null)} /><small>{configurationPackageFile ? configurationPackageFile.name : '可从已配置的相似模板导出'}</small></label>
                    <div><strong>带入当前草稿</strong><span>按表号带入映射；仅可在当前 Word 中继续定位的填写位会被带入。当前草稿的映射、填写位、关键词和完整性规则会更新为配置包内容。</span></div>
                    <button type="button" className="button small" disabled={busy || !configurationPackageFile} onClick={() => void importConfigurationPackage()}>带入配置包</button>
                  </div> : <p className="template-configuration-package-readonly">仅草稿或已退回模板可带入配置包；已启用模板请先创建修订草稿。</p>}
                </section>}
                {configurationReadiness && <section className="template-configuration-readiness" aria-labelledby="template-readiness-heading">
                  <div className="template-readiness-heading">
                    <div>
                      <p className="eyebrow">CONFIGURATION AT A GLANCE</p>
                      <h3 id="template-readiness-heading">配置准备度</h3>
                      <p>汇总默认映射和固定资料填写位的处理状态，帮助管理员安排配置工作；这只是导航信息，不会改变审批或报告生成门禁。</p>
                    </div>
                    <span className={configurationReadiness.outstanding_count ? 'has-outstanding' : 'is-clear'}>{configurationReadiness.outstanding_count ? `${configurationReadiness.outstanding_count} 项待确认` : '暂无待确认建议'}</span>
                  </div>
                  <div className="template-readiness-grid">
                    <article>
                      <span>表格任务映射</span>
                      <strong>{configurationReadiness.mapping.configured_count} <small>/ {configurationReadiness.mapping.detected_table_count}</small></strong>
                      <p>已非默认配置；{configurationReadiness.mapping.pending_count} 张表仍沿用默认值或尚未配置。</p>
                      <small>高置信度建议待处理：{configurationReadiness.mapping.high_confidence_pending_count} / {configurationReadiness.mapping.high_confidence_suggestion_count}</small>
                    </article>
                    <article>
                      <span>报告填写位</span>
                      <strong>{configurationReadiness.field_slots.configured_count} <small>个</small></strong>
                      <p>固定资料 {configurationReadiness.field_slots.fixed_data_count} 个；CRA 确认文本 {configurationReadiness.field_slots.confirmed_text_count} 个。</p>
                      <small>高置信度建议待处理：{configurationReadiness.field_slots.high_confidence_pending_count} / {configurationReadiness.field_slots.high_confidence_suggestion_count}</small>
                    </article>
                    <article>
                      <span>正文 / 页眉页脚标记</span>
                      <strong>{configurationReadiness.field_slots.inline_token_configured_count} <small>/ {configurationReadiness.field_slots.inline_token_suggestion_count}</small></strong>
                      <p>已配置 / 识别到的 <code>{'{{…}}'}</code> 固定资料标记。</p>
                      <small>可从“报告填写位建议”逐条带入或批量导入高置信度建议。</small>
                    </article>
                  </div>
                </section>}
                <div className="template-match-profile">
                  <div className="template-match-profile-heading">
                    <div><strong>自动识别的适用访视</strong><span>根据模板名称、原始文件名与已识别表格标题进行本地特征匹配；不调用外部模型。</span></div>
                    <span className="template-match-algorithm">{matchingProfile?.algorithm ?? 'template_keyword_v1'}</span>
                  </div>
                  {matchingProfile?.inferred_visit_types.length ? <div className="template-match-chip-list">
                    {matchingProfile.inferred_visit_types.map((hint) => <span key={hint.code} className="template-match-chip"><strong>{hint.label}</strong><small>命中：{hint.matched_terms.join('、')}</small></span>)}
                  </div> : <p className="template-match-empty">尚未从该模板识别出特异访视类型；CRA 新建访视时仍可手工选择此模板。</p>}
                  {matchingProfile?.matched_terms.length ? <p className="template-match-terms">识别词：{matchingProfile.matched_terms.join('、')}</p> : null}
                  {isEditable ? <div className="template-match-editor">
                    <label>管理员确认的适用访视关键词<input value={visitTypeKeywords} onChange={(event) => setVisitTypeKeywords(event.target.value)} disabled={busy} placeholder="例如：IMV，常规监查，首例筛选监查访视" /><small>用逗号或换行分隔。保存后，该配置将优先于自动识别用于新访视模板推荐。</small></label>
                    <button type="button" className="button small" disabled={busy} onClick={() => void saveVisitTypeKeywords()}>保存关键词</button>
                  </div> : administratorKeywords.length ? <p className="template-match-confirmed">管理员确认：{administratorKeywords.join('、')}</p> : null}
                </div>
                <section className="template-completeness-rules" aria-labelledby="template-completeness-heading">
                  <div className="template-completeness-heading">
                    <div>
                      <p className="eyebrow">COMPLETENESS POLICY</p>
                      <h3 id="template-completeness-heading">模板完整性规则</h3>
                      <p>定义该模板的哪些监查任务与 CRA 确认填写位进入报告门禁。规则会随新建访视或模板切换冻结，不会回写已有报告。</p>
                    </div>
                    <span>FROZEN PER VISIT</span>
                  </div>
                  <div className="template-completeness-grid">
                    <label>监查任务门禁
                      <select disabled={!isEditable || busy} value={completenessRules.task_mode} onChange={(event) => setCompletenessRules((current) => ({ ...current, task_mode: event.target.value as TemplateCompletenessRules['task_mode'] }))}>
                        {(Object.keys(templateTaskCompletenessLabels) as TemplateCompletenessRules['task_mode'][]).map((mode) => <option key={mode} value={mode}>{templateTaskCompletenessLabels[mode]}</option>)}
                      </select>
                      <small>{completenessRules.task_mode === 'all_mappings' ? '每张已映射表都须形成明确监查结论。' : completenessRules.task_mode === 'none' ? '模板映射仍会生成工作任务，但不单独阻断报告。' : '沿用每张表的“必填”标记。'}</small>
                    </label>
                    <label>CRA 确认填写位门禁
                      <select disabled={!isEditable || busy} value={completenessRules.field_mode} onChange={(event) => setCompletenessRules((current) => ({ ...current, field_mode: event.target.value as TemplateCompletenessRules['field_mode'] }))}>
                        {(Object.keys(templateFieldCompletenessLabels) as TemplateCompletenessRules['field_mode'][]).map((mode) => <option key={mode} value={mode}>{templateFieldCompletenessLabels[mode]}</option>)}
                      </select>
                      <small>{completenessRules.field_mode === 'all_confirmed_text_slots' ? '所有“CRA 已确认文本”填写位均需有确认字段。' : completenessRules.field_mode === 'none' ? '填写位仍可填充，但不单独阻断报告。' : '沿用每个填写位的“必填标记”。'}</small>
                    </label>
                    {isEditable ? <button type="button" className="button small" disabled={busy} onClick={() => void saveCompletenessRules()}>保存完整性规则</button> : <p className="template-completeness-readonly">当前模板不可编辑，以下展示为该版本已冻结的配置。</p>}
                  </div>
                </section>
                <section className="template-mapping-reference" aria-labelledby="mapping-reference-heading">
                  <div className="template-mapping-reference-heading">
                    <div>
                      <p className="eyebrow">MAPPING REFERENCE</p>
                      <h3 id="mapping-reference-heading">历史模板映射参考</h3>
                      <p>可按表号查看当前模板库中已启用模板的表级映射，并手动带入当前草稿。系统不会自动判断两个 Word 表格语义相同。</p>
                    </div>
                    <span>MANUAL ADOPT</span>
                  </div>
                  <div className="mapping-reference-controls">
                    <label>选择已启用的参考模板
                      <select value={mappingReferenceTemplateId} disabled={!isEditable || busy} onChange={(event) => void selectMappingReference(event.target.value)}>
                        <option value="">不使用历史映射参考</option>
                        {mappingReferenceCandidates.map((template) => <option key={template.id} value={template.id}>{template.name} · {template.version} · {template.table_count} 张表</option>)}
                      </select>
                    </label>
                    <p>仅复制字段键、监查区域和必填标记到当前页面草稿；不会复制 Word 目标位置、填写位或报告事实。带入后仍需逐行核对并保存。</p>
                  </div>
                  {!isEditable ? <p className="mapping-reference-empty">当前模板不可编辑；可查看映射配置，但只有草稿或退回状态的模板可采纳参考。</p> : mappingReferenceCandidates.length === 0 ? <p className="mapping-reference-empty">尚无其他已启用模板可作为参考。请先完成并批准一个可复用的模板配置。</p> : null}
                  {mappingReferenceLoading ? <p className="mapping-reference-loading">正在读取参考模板的表级映射…</p> : null}
                  {mappingReferenceDetail && !mappingReferenceLoading ? <div className="data-table-wrap mapping-reference-table-wrap">
                    <table className="data-table mapping-reference-table">
                      <thead><tr><th>当前表</th><th>当前识别标题</th><th>参考模板映射</th><th>人工操作</th></tr></thead>
                      <tbody>{mappingReferenceRows.map(({ target, source }) => {
                        const targetDetected = detail.detected_tables.find((table) => table.table_index === target.table_index)
                        const sourceDetected = mappingReferenceDetail.detected_tables.find((table) => table.table_index === target.table_index)
                        return <tr key={target.id}>
                          <td className="tabular">{String(target.table_index).padStart(2, '0')}</td>
                          <td>{targetDetected?.detected_label ?? '未识别标题'}</td>
                          <td>{source ? <div className="mapping-reference-source"><strong>{templateMappingReferenceLabel(source)}</strong><small>{sourceDetected?.detected_label ?? ('参考模板第 ' + source.table_index + ' 张表')} · {source.required ? '必填' : '可选'}</small></div> : <span className="muted-cell">参考模板没有同表号映射</span>}</td>
                          <td>{source ? <button type="button" className="button small" disabled={!isEditable || busy} onClick={() => adoptMappingReference(target.id, source)}>带入本行草稿</button> : '—'}</td>
                        </tr>
                      })}</tbody>
                    </table>
                  </div> : null}
                </section>
                <section className="field-slot-ledger" aria-labelledby="field-slot-heading">
                  <div className="field-slot-heading">
                    <div>
                      <p className="eyebrow">REPORT FILL SLOTS</p>
                      <h3 id="field-slot-heading">报告填写位</h3>
                      <p>填写位可对应表格单元格、正文、页眉/页脚段落或 <code>{'{{…}}'}</code> 内联标记。全段落替换会覆盖段落文字；需要保留固定标签时，请选择内联标记。</p>
                    </div>
                    <span className="slot-count">{detail.field_slots.length} 个填写位</span>
                  </div>
                  <div className="field-slot-suggestions">
                    <div className="field-slot-suggestions-heading"><div><strong>自动识别的固定资料填写位</strong><span>根据表格标签旁的空白单元格及正文、页眉、页脚的 <code>{'{{…}}'}</code> 标记生成来源建议；不会自动替换模板文字或保存配置。</span></div><div className="field-slot-suggestion-actions"><span>{detail.field_slot_suggestions.length} 项建议</span>{isEditable && detail.field_slot_suggestions.some((suggestion) => suggestion.confidence === 'high') && <button type="button" className="button quiet small" disabled={busy} onClick={() => void importHighConfidenceFieldSlotSuggestions()}>导入高置信度建议</button>}</div></div>
                    {detail.field_slot_suggestions.length === 0 ? <p className="field-slot-suggestions-empty">未识别到可安全建议的固定资料标签。你仍可在下方手动新增填写位。</p> : <div className="field-slot-suggestion-list">{detail.field_slot_suggestions.map((suggestion) => <article key={`${suggestion.target_locator}:${suggestion.field_key}`} className={`confidence-${suggestion.confidence}`}><div><strong>{suggestion.label}</strong><span>{suggestion.target_locator} · {fieldSlotSourceOptions.find((source) => source.value === suggestion.value_source)?.label ?? suggestion.value_source}</span><small>{suggestion.reason}</small></div><button type="button" className="button quiet small" disabled={!isEditable || busy} onClick={() => adoptFieldSlotSuggestion(suggestion)}>带入新增草稿</button></article>)}</div>}
                  </div>
                  {detail.field_slots.length === 0 ? <p className="field-slot-empty">当前模板尚未配置填写位。仅标记为 UA007 样例的模板会继续使用专用导出；其他模板（包括新上传的 15 表模板）请在下方新增填写位后生成真实 Word。</p> : <div className="data-table-wrap">
                    <table className="data-table field-slot-table">
                      <thead><tr><th>目标类型</th><th>目标位置</th><th>填写位名称</th><th>字段键</th><th>填写来源</th><th>配置标记</th><th /></tr></thead>
                      <tbody>{detail.field_slots.map((slot) => {
                        const targetKind = slot.target_kind ?? 'table_cell'
                        const targetCandidates = fieldSlotTargetCandidates(targetKind)
                        return <tr key={slot.id}>
                          <td><select aria-label={`填写位 ${slot.label || slot.id} 的目标类型`} value={targetKind} disabled={!isEditable} onChange={(event) => updateLocalFieldSlot(slot.id, targetPatchForKind(event.target.value as TemplateFieldSlotTargetKind))}>{fieldSlotTargetKindOptions.map((targetKindOption) => <option key={targetKindOption.value} value={targetKindOption.value}>{targetKindOption.label}</option>)}</select></td>
                          <td><div className="field-slot-target">
                            {targetKind === 'table_cell' ? <select aria-label={`填写位 ${slot.label || slot.id} 的表号`} value={slot.table_index} disabled={!isEditable} onChange={(event) => chooseExistingFieldSlotTable(slot, Number(event.target.value))}>{detail.detected_tables.map((table) => <option key={table.table_index} value={table.table_index}>{`第 ${table.table_index} 表：${table.detected_label}`}</option>)}</select> : <select aria-label={`填写位 ${slot.label || slot.id} 的识别目标`} value={slot.target_locator} disabled={!isEditable} onChange={(event) => chooseExistingFieldSlotTarget(slot, event.target.value)}><option value="">选择已识别目标</option>{targetCandidates.map((target) => <option key={target.target_locator} value={target.target_locator}>{`${target.label} · ${target.preview}`}</option>)}</select>}
                            <input aria-label={`填写位 ${slot.id} 目标定位符`} value={slot.target_locator} disabled={!isEditable} onChange={(event) => updateLocalFieldSlot(slot.id, { target_locator: event.target.value })} placeholder={fieldSlotTargetLocatorPlaceholder(targetKind)} />
                          </div></td>
                          <td><input aria-label={`填写位 ${slot.id} 名称`} value={slot.label} disabled={!isEditable} onChange={(event) => updateLocalFieldSlot(slot.id, { label: event.target.value })} placeholder="例如：总体评价" /></td>
                          <td><input aria-label={`填写位 ${slot.id} 字段键`} value={slot.field_key} disabled={!isEditable || slot.value_source !== 'confirmed_text'} onChange={(event) => updateLocalFieldSlot(slot.id, { field_key: event.target.value })} placeholder="例如：table_3" /></td>
                          <td><select aria-label={`填写位 ${slot.id} 填写来源`} value={slot.value_source} disabled={!isEditable} onChange={(event) => updateLocalFieldSlot(slot.id, { value_source: event.target.value })}>{fieldSlotSourceOptions.map((source) => <option key={source.value} value={source.value}>{source.label}</option>)}</select></td>
                          <td><label className="mapping-required"><input type="checkbox" checked={Boolean(slot.required)} disabled={!isEditable} onChange={() => updateLocalFieldSlot(slot.id, { required: slot.required ? 0 : 1 })} /><span>{slot.required ? '必填标记' : '可选'}</span></label></td>
                          <td className="slot-actions"><button type="button" className="button small" disabled={busy || !isEditable} onClick={() => void saveFieldSlot(slot)}>保存</button><button type="button" className="button small danger-quiet" disabled={busy || !isEditable} onClick={() => void removeFieldSlot(slot)}>移除</button></td>
                        </tr>
                      })}</tbody>
                    </table>
                  </div>}
                  {isEditable && <form className="field-slot-add-form" onSubmit={addFieldSlot}>
                    <label>目标类型<select value={newFieldSlot.target_kind} onChange={(event) => updateNewFieldSlotTargetKind(event.target.value as TemplateFieldSlotTargetKind)}>{fieldSlotTargetKindOptions.map((targetKindOption) => <option key={targetKindOption.value} value={targetKindOption.value}>{targetKindOption.label}</option>)}</select></label>
                    <label>{newFieldSlot.target_kind === 'table_cell' ? '表号' : '识别目标'}{newFieldSlot.target_kind === 'table_cell' ? <select value={newFieldSlot.table_index} onChange={(event) => { const tableIndex = Number(event.target.value); const candidate = fieldSlotTargetCandidates('table_cell').find((target) => target.table_index === tableIndex); setNewFieldSlot((current) => ({ ...current, table_index: tableIndex, field_key: `table_${tableIndex}`, target_locator: candidate?.target_locator ?? current.target_locator })) }}>{detail.detected_tables.map((table) => <option key={table.table_index} value={table.table_index}>第 {table.table_index} 表</option>)}</select> : <select value={newFieldSlot.target_locator} onChange={(event) => chooseNewFieldSlotTarget(event.target.value)}><option value="">选择已识别目标</option>{fieldSlotTargetCandidates(newFieldSlot.target_kind).map((target) => <option key={target.target_locator} value={target.target_locator}>{`${target.label} · ${target.preview}`}</option>)}</select>}</label>
                    <label>填写位名称<input value={newFieldSlot.label} onChange={(event) => setNewFieldSlot((current) => ({ ...current, label: event.target.value }))} placeholder="例如：研究名称" /></label>
                    <label>字段键<input value={newFieldSlot.field_key} disabled={newFieldSlot.value_source !== 'confirmed_text'} onChange={(event) => setNewFieldSlot((current) => ({ ...current, field_key: event.target.value }))} placeholder="确认文本时使用" /></label>
                    <label>目标定位符<input value={newFieldSlot.target_locator} onChange={(event) => setNewFieldSlot((current) => ({ ...current, target_locator: event.target.value }))} placeholder={fieldSlotTargetLocatorPlaceholder(newFieldSlot.target_kind)} /></label>
                    <label>填写来源<select value={newFieldSlot.value_source} onChange={(event) => setNewFieldSlot((current) => ({ ...current, value_source: event.target.value }))}>{fieldSlotSourceOptions.map((source) => <option key={source.value} value={source.value}>{source.label}</option>)}</select></label>
                    <label className="mapping-required"><input type="checkbox" checked={Boolean(newFieldSlot.required)} onChange={() => setNewFieldSlot((current) => ({ ...current, required: current.required ? 0 : 1 }))} /><span>必填标记</span></label>
                    <button type="submit" className="button small" disabled={busy}>新增填写位</button>
                  </form>}
                </section>
                <div className="mapping-import-heading"><div><strong>监查任务与报告区域映射</strong><span>高置信度建议只会带入仍是系统默认值的映射；已有管理员配置不会覆盖。</span></div>{isEditable && detail.mapping_suggestions.some((suggestion) => suggestion.confidence === 'high') && <button type="button" className="button quiet small" disabled={busy} onClick={() => void importHighConfidenceMappingSuggestions()}>导入高置信度映射</button>}</div>
                <div className="data-table-wrap">
                <table className="data-table mapping-table">
                  <thead><tr><th>表</th><th>自动识别</th><th>稳定字段键</th><th>访视任务 / 报告区域</th><th>必填</th><th /></tr></thead>
                  <tbody>{detail.mappings.map((mapping) => {
                    const detected = detail.detected_tables.find((item) => item.table_index === mapping.table_index)
                    const suggestion = detail.mapping_suggestions.find((item) => item.table_index === mapping.table_index)
                    return <tr key={mapping.id}>
                      <td className="tabular">{String(mapping.table_index).padStart(2, '0')}</td>
                      <td className="muted-cell"><div className="mapping-detection"><span>{detected?.detected_label ?? '—'}</span>{suggestion && <small className={`mapping-suggestion confidence-${suggestion.confidence}`}><strong>建议：{suggestion.target_description}</strong><span>{suggestion.reason}</span></small>}</div></td>
                      <td><input aria-label={`模板字段键 ${mapping.table_index}`} value={mapping.field_key} disabled={!isEditable} onChange={(event) => updateLocalMapping(mapping.id, { field_key: event.target.value })} /></td>
                       <td><input aria-label={`第 ${mapping.table_index} 张表的任务名称`} value={mapping.target_description} disabled={!isEditable} onChange={(event) => updateLocalMapping(mapping.id, { target_description: event.target.value })} /></td>
                       <td><label className="mapping-required"><input type="checkbox" checked={Boolean(mapping.required)} disabled={!isEditable} onChange={() => updateLocalMapping(mapping.id, { required: mapping.required ? 0 : 1 })} /><span>{mapping.required ? '必填' : '可选'}</span></label></td>
                       <td><div className="mapping-actions">{suggestion && <button type="button" className="button quiet small" disabled={busy || !isEditable} onClick={() => adoptMappingSuggestion(mapping, suggestion)}>带入建议</button>}<button type="button" className="button small" disabled={busy || !isEditable} onClick={() => void saveMapping(mapping)}>保存</button></div></td>
                    </tr>
                  })}</tbody>
                </table>
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
