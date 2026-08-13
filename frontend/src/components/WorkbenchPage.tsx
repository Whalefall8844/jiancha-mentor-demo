import { useEffect, useState } from 'react'
import { api } from '../api'
import { ActionItemsPanel } from './ActionItemsPanel'
import { ClarificationPanel } from './ClarificationPanel'
import { OfflineDraftsPanel } from './OfflineDraftsPanel'
import type { DemoState, RecordItem, Suggestion, TableTask, TaskExecutionPatch, TaskExecutionStatus } from '../types'

interface WorkbenchPageProps {
  state: DemoState
  onStateChange: (state: DemoState) => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

const categoryLabels: Record<string, string> = {
  summary: '访视小结',
  recruitment: '受试者进展',
  icf: '知情同意',
  icf_list: '签署 ICF 列表',
  ae: 'AE',
  sae: 'SAE',
  deviation: '方案偏离',
  crf: 'CRF / 原始病历',
  regulatory: '法规文件',
  investigational_product: '试验用药品/药房',
  document_archive: '文件/资质/实验室',
  system_device: '系统/设备',
  action: '行动项',
}

const assertionTypeLabels: Record<string, string> = {
  reported_observation: '现场记录事实',
  monitoring_summary: '监查小结建议',
  action_request: '后续跟进建议',
  center_explanation: '中心解释（未作为 CRA 事实）',
}

const entityTypeLabels: Record<string, string> = {
  subject: '受试者',
  visit: '本次访视',
}

const subjectValidationLabels: Record<string, string> = {
  valid: '编号已校验',
  unverified: '编号未在本中心清单中',
  not_provided: '未识别受试者编号',
  historical_unverified: '历史记录未校验',
}

const recordKindLabels: Record<string, string> = {
  monitoring_note: 'CRA 监查记录',
  center_explanation: '中心解释',
  correction: '更正记录',
  clarification_response: '缺失/冲突处理记录',
}

const criticalEditCategories = new Set(['icf', 'icf_list', 'ae', 'sae', 'deviation', 'regulatory'])
const subjectCodeCandidatePattern = /(?<![A-Za-z0-9])(?:[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+|[A-Za-z]{1,4}[-_]?\d{3,6}|\d{3}[-_]\d{3})(?![A-Za-z0-9]|[-_]\*{3})/g

const maskSubjectCode = (value: string) => {
  if (value.includes('-') || value.includes('_')) {
    const normalized = value.replaceAll('_', '-')
    const prefix = normalized.slice(0, normalized.lastIndexOf('-'))
    return prefix ? `${prefix}-***` : '***'
  }
  return value.length <= 2 ? '**' : `${value.slice(0, 2)}${'*'.repeat(Math.max(2, value.length - 2))}`
}

const shortTraceId = (value?: string) => value ? `${value.slice(0, 8)}…` : '未关联执行记录'

const displaySubjectText = (value: string, subject = '', displayCode = '') => {
  const resolvedDisplayCode = displayCode || subject
  return subject && resolvedDisplayCode ? value.split(subject).join(resolvedDisplayCode) : value
}

const displaySuggestionText = (value: string, suggestion: Suggestion) =>
  displaySubjectText(value, suggestion.subject || '', suggestion.subject_display_code || '')

const restoreSuggestionDisplayText = (value: string, suggestion: Suggestion) => {
  const subject = suggestion.subject || ''
  const displayCode = suggestion.subject_display_code || subject
  return subject && displayCode ? value.split(displayCode).join(subject) : value
}

const taskStatusOptions: Array<{ value: TaskExecutionStatus; label: string }> = [
  { value: '待补录', label: '待补录（尚未形成结论）' },
  { value: '未开始', label: '未开始' },
  { value: '进行中', label: '进行中' },
  { value: '待 CRA 确认', label: '待 CRA 确认' },
  { value: '已确认', label: '已确认（待补充监查结论）' },
  { value: '已执行且未发现', label: '已执行且未发现' },
  { value: '已执行且有发现', label: '已执行且有发现' },
  { value: '未检查', label: '未检查' },
  { value: '暂无法检查', label: '暂无法检查' },
  { value: '不适用', label: '不适用' },
  { value: '已完成', label: '已完成' },
]

const terminalTaskStatuses = new Set<TaskExecutionStatus>(['已执行且未发现', '已执行且有发现', '未检查', '暂无法检查', '不适用', '已完成'])
const executionTaskStatuses = new Set<TaskExecutionStatus>(['已执行且未发现', '已执行且有发现', '已完成'])

const taskReasonTemplates: Partial<Record<TaskExecutionStatus, Array<{ label: string; text: string }>>> = {
  未检查: [
    { label: '现场时间限制', text: '本次监查期间因现场时间安排限制，未能对本项完成核查。实际原因／后续安排：' },
    { label: '本次范围未覆盖', text: '本次监查范围未覆盖本项，故未执行核查。实际原因／后续安排：' },
    { label: '资料未安排查阅', text: '本次监查期间未安排查阅与本项相关的资料，故未执行核查。实际原因／后续安排：' },
  ],
  暂无法检查: [
    { label: '资料暂未提供', text: '本次监查期间，相关资料暂未提供，暂无法完成核查。请补充实际情况及后续安排：' },
    { label: '相关人员未能配合', text: '本次监查期间，相关人员暂无法配合提供核查条件，暂无法完成核查。请补充实际情况及后续安排：' },
    { label: '系统／设备暂不可用', text: '本次监查期间，相关系统／设备暂不可访问或使用，暂无法完成核查。请补充实际情况及后续安排：' },
  ],
  不适用: [
    { label: '中心未启用相关流程', text: '本中心未启用与本项相关的流程／系统；适用依据：[请补充实际依据]。' },
    { label: '本阶段未涉及', text: '本次访视／项目阶段尚未涉及本项；适用依据：[请补充实际依据]。' },
    { label: '按项目配置不适用', text: '按项目配置／方案要求，本项不适用；适用依据：[请补充实际依据]。' },
  ],
}

const isSystemCheckTask = (task: TableTask) => task.task_type === 'system_device_check'
const taskPositionLabel = (task: TableTask) => isSystemCheckTask(task) ? '系统／设备' : `表 ${String(task.index).padStart(2, '0')}`

const createClientRecordKey = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `record-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const recordProcessingLabels: Record<string, string> = {
  pending: '待整理',
  completed: '已整理',
  no_suggestions: '无需建议',
  failed: '整理失败',
}

const displayRecordTime = (value?: string) => (value || '').replace('T', ' ').replace('Z', ' UTC')
const recordProcessingLabel = (value?: string) => recordProcessingLabels[value || 'completed'] || '处理状态未知'
const currentClientTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'unknown'

function toTaskDraft(task: TableTask, craName: string): TaskExecutionPatch {
  const status = taskStatusOptions.some((item) => item.value === task.status) ? task.status as TaskExecutionStatus : '待补录'
  return {
    status,
    evidence: task.evidence ?? '',
    execution_date: task.execution_date ?? '',
    checked_scope: task.checked_scope ?? '',
    rationale: task.rationale ?? '',
    completed_by: task.completed_by || craName || '演示 CRA',
  }
}

export function WorkbenchPage({ state, onStateChange, onNotice }: WorkbenchPageProps) {
  const [recordText, setRecordText] = useState('')
  const [recordKind, setRecordKind] = useState<'monitoring_note' | 'center_explanation'>('monitoring_note')
  const [recordTaskId, setRecordTaskId] = useState('')
  const [recordedAt, setRecordedAt] = useState('')
  const [recordTags, setRecordTags] = useState('')
  const [recordClientKey, setRecordClientKey] = useState('')
  const [duplicateCandidates, setDuplicateCandidates] = useState<RecordItem[]>([])
  const [saving, setSaving] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editedText, setEditedText] = useState('')
  const [editDecisionReason, setEditDecisionReason] = useState('')
  const [selectedSuggestionIds, setSelectedSuggestionIds] = useState<string[]>([])
  const [batchDeciding, setBatchDeciding] = useState(false)
  const [routingSuggestionId, setRoutingSuggestionId] = useState<string | null>(null)
  const [correctingRecordId, setCorrectingRecordId] = useState<string | null>(null)
  const [correctionText, setCorrectionText] = useState('')
  const [correctionReason, setCorrectionReason] = useState('')
  const [correctionSaving, setCorrectionSaving] = useState(false)
  const [voidingRecordId, setVoidingRecordId] = useState<string | null>(null)
  const [voidReason, setVoidReason] = useState('')
  const [voidSaving, setVoidSaving] = useState(false)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [taskDraft, setTaskDraft] = useState<TaskExecutionPatch | null>(null)
  const [taskSaving, setTaskSaving] = useState(false)
  const [selectedActionId, setSelectedActionId] = useState<string | null>(null)
  const reportLocked = ['submitted', 'approved'].includes(state.report_status)
  const canEdit = state.current_role === 'CRA' && !reportLocked

  const pending = state.suggestions.filter((item) => item.status === 'pending')
  const centerExplanations = state.center_explanations ?? []
  const selectedPendingIds = selectedSuggestionIds.filter((id) => pending.some((item) => item.id === id))
  const recentRecords = state.records.slice(0, 6)
  const correctingRecord = state.records.find((record) => record.id === correctingRecordId) ?? null
  const voidingRecord = state.records.find((record) => record.id === voidingRecordId) ?? null
  const systemCheckTasks = state.system_check_tasks ?? []
  const allTasks = [...state.table_tasks, ...systemCheckTasks]
  const selectedTask = allTasks.find((task) => task.id === selectedTaskId) ?? null
  const recordLinkedTask = allTasks.find((task) => task.id === recordTaskId) ?? null
  const isTerminalTask = taskDraft ? terminalTaskStatuses.has(taskDraft.status) : false
  const needsExecutionEvidence = taskDraft ? executionTaskStatuses.has(taskDraft.status) : false
  const needsReason = taskDraft ? ['未检查', '暂无法检查', '不适用'].includes(taskDraft.status) : false
  const taskReasonTemplateOptions = taskDraft ? taskReasonTemplates[taskDraft.status] ?? [] : []
  const isCenterExplanation = recordKind === 'center_explanation'
  const processingRecordCount = state.records.filter((record) => record.processing_status === 'pending').length
  const displayRecordText = (value: string) => state.project.subject_code_display_mode === 'full'
    ? value
    : value.replace(subjectCodeCandidatePattern, (candidate) => maskSubjectCode(candidate))

  useEffect(() => {
    if (!state.visit.id || processingRecordCount === 0) return undefined
    const refreshProcessing = async () => {
      try {
        onStateChange(await api.getState(state.visit.id))
      } catch {
        // The raw record is already durable; leave the current workbench visible until the next refresh succeeds.
      }
    }
    const intervalId = window.setInterval(() => { void refreshProcessing() }, 900)
    return () => window.clearInterval(intervalId)
  }, [onStateChange, processingRecordCount, state.visit.id])

  const addRecord = async (forceNew = false) => {
    if (!canEdit) {
      onNotice('当前角色仅可查看工作底稿；现场记录由 CRA 保存。', 'error')
      return
    }
    if (!recordText.trim()) {
      onNotice('请先写下一条现场监查记录。', 'error')
      return
    }
    try {
      setSaving(true)
      if (!state.visit.id) {
        onNotice('尚未选择访视，无法保存现场记录。', 'error')
        return
      }
      if (!forceNew && !recordClientKey) {
        const duplicates = await api.previewVisitRecordDuplicates(state.visit.id, recordText)
        if (duplicates.items.length > 0) {
          setDuplicateCandidates(duplicates.items)
          return
        }
      }
      const clientKey = recordClientKey || createClientRecordKey()
      setRecordClientKey(clientKey)
      const clientCreatedAt = new Date().toISOString()
      const response = await api.createVisitRecord(state.visit.id, {
        text: recordText,
        created_by: state.visit.cra_name || '演示 CRA',
        record_kind: recordKind,
        linked_task_id: recordTaskId,
        recorded_at: recordedAt,
        client_created_at: clientCreatedAt,
        client_timezone: currentClientTimezone(),
        tags: recordTags.split(/[,，;；\n\r]+/).map((item) => item.trim()).filter(Boolean),
        client_idempotency_key: clientKey,
      })
      onStateChange(response.workspace)
      setRecordText('')
      setRecordKind('monitoring_note')
      setRecordedAt('')
      setRecordTags('')
      setRecordClientKey('')
      setDuplicateCandidates([])
      if (response.idempotent_reuse) {
        onNotice('已恢复此前保存的现场记录，未重复生成工作底稿。', 'success')
      } else if (response.processing_deferred) {
        onNotice('原始记录已保存，正在后台整理；可继续录入其他现场记录。', 'success')
      } else if (response.record.processing_status === 'failed') {
        onNotice('原始记录已保存，但本地整理未完成；记录会保留在工作底稿中。', 'error')
      } else {
        onNotice(`已生成 ${response.workspace.suggestions.filter((item) => item.status === 'pending').length} 条待确认建议。`, 'success')
      }
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '记录保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  const beginCorrection = (record: RecordItem) => {
    setVoidingRecordId(null)
    setVoidReason('')
    setCorrectingRecordId(record.id)
    setCorrectionText(record.text)
    setCorrectionReason('')
  }

  const beginVoid = (record: RecordItem) => {
    setCorrectingRecordId(null)
    setCorrectionText('')
    setCorrectionReason('')
    setVoidingRecordId(record.id)
    setVoidReason('')
  }

  const voidRecord = async () => {
    if (!canEdit || !state.visit.id || !voidingRecord) return
    if (!voidReason.trim()) {
      onNotice('请填写撤销原因，原始记录会继续保留在历史中。', 'error')
      return
    }
    try {
      setVoidSaving(true)
      const response = await api.voidVisitRecord(state.visit.id, voidingRecord.id, {
        reason: voidReason,
        actor_name: state.visit.cra_name || '演示 CRA',
      })
      onStateChange(response.workspace)
      setVoidingRecordId(null)
      setVoidReason('')
      onNotice(`已撤销该工作记录；已退出 ${response.affected.suggestions} 条建议和 ${response.affected.confirmed_fields} 条确认字段。`, 'success')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '撤销监查记录失败', 'error')
    } finally {
      setVoidSaving(false)
    }
  }

  const saveCorrection = async () => {
    if (!canEdit || !state.visit.id || !correctingRecord) return
    if (!correctionText.trim()) {
      onNotice('请填写更正后的现场记录。', 'error')
      return
    }
    if (!correctionReason.trim()) {
      onNotice('请填写更正原因，原始记录不会被覆盖。', 'error')
      return
    }
    try {
      setCorrectionSaving(true)
      const response = await api.correctVisitRecord(state.visit.id, correctingRecord.id, {
        text: correctionText,
        correction_reason: correctionReason,
        created_by: state.visit.cra_name || '演示 CRA',
      })
      onStateChange(response.workspace)
      setCorrectingRecordId(null)
      setCorrectionText('')
      setCorrectionReason('')
      onNotice(`已追加更正记录，并生成 ${response.suggestions.length} 条待 CRA 确认建议。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '更正记录保存失败', 'error')
    } finally {
      setCorrectionSaving(false)
    }
  }

  const decide = async (suggestion: Suggestion, decision: 'accepted' | 'edited' | 'rejected') => {
    try {
      const updated = await api.decideSuggestion(suggestion.id, decision, decision === 'edited' ? editedText : undefined, decision === 'edited' ? editDecisionReason : undefined)
      onStateChange(updated)
      setEditingId(null)
      setEditedText('')
      setEditDecisionReason('')
      onNotice(decision === 'rejected' ? '建议已拒绝。' : '建议已写入 CRA 已确认工作底稿。', 'success')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '处理建议失败', 'error')
    }
  }

  const toggleSuggestionSelection = (suggestionId: string) => {
    setSelectedSuggestionIds((current) => current.includes(suggestionId)
      ? current.filter((id) => id !== suggestionId)
      : [...current, suggestionId])
  }

  const decideSelectedSuggestions = async (decision: 'accepted' | 'rejected') => {
    if (!canEdit || !state.visit.id || selectedPendingIds.length === 0) return
    try {
      setBatchDeciding(true)
      const response = await api.decideVisitSuggestionsBatch(state.visit.id, {
        suggestion_ids: selectedPendingIds,
        decision,
        actor_name: state.visit.cra_name || '演示 CRA',
      })
      onStateChange(response.workspace)
      setSelectedSuggestionIds([])
      onNotice(`已批量${decision === 'accepted' ? '接受' : '拒绝'} ${response.items.length} 条建议。`, 'success')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '批量处理建议失败', 'error')
    } finally {
      setBatchDeciding(false)
    }
  }

  const assignSuggestionTarget = async (suggestion: Suggestion, targetTaskId: string) => {
    if (!canEdit || !state.visit.id || !targetTaskId || suggestion.target_task_id === targetTaskId) return
    try {
      setRoutingSuggestionId(suggestion.id)
      const response = await api.assignVisitSuggestionTarget(state.visit.id, suggestion.id, {
        target_task_id: targetTaskId,
        actor_name: state.visit.cra_name || '演示 CRA',
      })
      onStateChange(response.workspace)
      onNotice(`已将“${suggestion.title}”归类至“${response.item.target_title}”。`, 'success')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '重新归类建议失败', 'error')
    } finally {
      setRoutingSuggestionId(null)
    }
  }

  const selectTask = (task: TableTask) => {
    setSelectedTaskId(task.id)
    setRecordTaskId(task.id)
    setTaskDraft(toTaskDraft(task, state.visit.cra_name))
  }

  const selectAction = (actionItemId: string) => {
    setSelectedActionId(actionItemId)
  }

  const appendTaskReasonTemplate = (template: string) => {
    if (!taskDraft) return
    const current = taskDraft.rationale.trim()
    setTaskDraft({
      ...taskDraft,
      rationale: current ? `${current}\n${template}` : template,
    })
  }

  const saveTaskExecution = async () => {
    if (!canEdit || !state.visit.id || !selectedTask || !taskDraft) return
    try {
      setTaskSaving(true)
      await api.updateVisitTask(state.visit.id, selectedTask.id, taskDraft)
      const next = await api.getState(state.visit.id)
      onStateChange(next)
      const refreshedTask = [...next.table_tasks, ...(next.system_check_tasks ?? [])].find((task) => task.id === selectedTask.id)
      if (refreshedTask) setTaskDraft(toTaskDraft(refreshedTask, next.visit.cra_name))
      onNotice(`已保存${taskPositionLabel(selectedTask)}“${selectedTask.title}”的监查结论与执行依据。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '任务执行信息保存失败', 'error')
    } finally {
      setTaskSaving(false)
    }
  }

  return (
    <div className="workbench-layout">
      <section className="task-panel section-block">
        <div className="section-header compact-header">
          <div>
            <h2>{state.table_tasks.length} 张表任务清单</h2>
            <p>选择一项，定位本条记录将进入的模板区域。</p>
          </div>
        </div>
        <div className="task-list" role="list">
          {state.table_tasks.map((task) => (
            <button
              type="button"
              role="listitem"
              key={task.id}
              className={`task-row ${selectedTaskId === task.id ? 'is-selected' : ''}`}
              onClick={() => selectTask(task)}
            >
              <span className="task-number">{String(task.index).padStart(2, '0')}</span>
              <span className="task-copy"><strong>{task.title}</strong><small>{task.status}{task.requires_evidence ? ' · 必填' : ''}</small></span>
            </button>
          ))}
        </div>
        {systemCheckTasks.length > 0 && <div className="system-task-group">
          <div className="task-list-divider"><strong>系统／设备核查</strong><small>独立工作底稿，不增加 Word 表格</small></div>
          <div className="task-list" role="list">
            {systemCheckTasks.map((task) => (
              <button
                type="button"
                role="listitem"
                key={task.id}
                className={`task-row ${selectedTaskId === task.id ? 'is-selected' : ''}`}
                onClick={() => selectTask(task)}
              >
                <span className="task-number is-system">SYS</span>
                <span className="task-copy"><strong>{task.title}</strong><small>{task.status}{task.requires_evidence ? ' · 必填' : ''}{task.description ? ` · ${task.description}` : ''}</small></span>
              </button>
            ))}
          </div>
        </div>}
      </section>

      <div className="workbench-main">
        <section className="section-block task-execution-panel">
          <div className="section-header compact-header">
            <div>
              <h2>任务结论与执行依据</h2>
              <p>记录“已执行且未发现”时，必须同步填写日期、范围/样本量和核查说明；系统不会把未检查转换为未发现。</p>
            </div>
            <span className="section-code">TASK EVIDENCE</span>
          </div>
          {!selectedTask || !taskDraft ? <div className="empty-state inline"><span>从左侧任务清单选择一个监查区域，补充其结论和执行依据。</span></div> : (
            <form className="task-execution-form" onSubmit={(event) => { event.preventDefault(); void saveTaskExecution() }}>
              <div className="task-execution-context"><span>{taskPositionLabel(selectedTask)}</span><strong>{selectedTask.title}</strong><small>{selectedTask.description || (selectedTask.requires_evidence ? '此项已配置为报告必填项' : '此项为可选工作项；如录入终态仍需符合证据语义')}</small></div>
              <div className="task-execution-fields">
                <label>监查结论<select value={taskDraft.status} disabled={!canEdit} onChange={(event) => setTaskDraft({ ...taskDraft, status: event.target.value as TaskExecutionStatus })}>{taskStatusOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                {isTerminalTask && <label>执行日期<input value={taskDraft.execution_date} inputMode="numeric" placeholder="YYYY-MM-DD" disabled={!canEdit} onChange={(event) => setTaskDraft({ ...taskDraft, execution_date: event.target.value })} /></label>}
                {needsExecutionEvidence && <label>检查范围 / 样本量<input value={taskDraft.checked_scope} disabled={!canEdit} onChange={(event) => setTaskDraft({ ...taskDraft, checked_scope: event.target.value })} placeholder="例如：抽查 8 例；覆盖 2026-08-01 至 2026-08-10" /></label>}
                {isTerminalTask && <label>执行 CRA<input value={taskDraft.completed_by} disabled={!canEdit} onChange={(event) => setTaskDraft({ ...taskDraft, completed_by: event.target.value })} /></label>}
                <label className="task-execution-wide">{needsExecutionEvidence ? '证据或核查说明' : '补充说明 / 证据（可选）'}<textarea value={taskDraft.evidence} disabled={!canEdit} onChange={(event) => setTaskDraft({ ...taskDraft, evidence: event.target.value })} placeholder={needsExecutionEvidence ? '说明核查对象、来源与结果；若有发现，请如实描述。' : '可补充与本任务相关的监查说明。'} /></label>
                {needsReason && <div className="task-execution-wide task-reason-field">
                  <span className="task-field-label">原因或适用依据</span>
                  <div className="task-reason-templates">
                    <div className="task-reason-template-header"><span>常用草稿</span><small>点击后追加到下方，可按实际情况修改</small></div>
                    <div className="task-reason-template-list">
                      {taskReasonTemplateOptions.map((template) => <button type="button" key={template.label} className="task-reason-template" disabled={!canEdit} onClick={() => appendTaskReasonTemplate(template.text)}>{template.label}</button>)}
                    </div>
                  </div>
                  <textarea value={taskDraft.rationale} disabled={!canEdit} aria-label="原因或适用依据" onChange={(event) => setTaskDraft({ ...taskDraft, rationale: event.target.value })} placeholder="说明未检查、暂无法检查或不适用的业务原因及依据。" />
                </div>}
              </div>
              <div className="task-execution-actions"><span>{canEdit ? '保存后，报告预检会按此结论重新计算。' : '当前角色仅可查看任务执行依据。'}</span><button type="submit" className="button secondary" disabled={!canEdit || taskSaving}>{taskSaving ? '正在保存…' : '保存任务结论'}</button></div>
            </form>
          )}
        </section>

        <ClarificationPanel
          state={state}
          canEdit={canEdit}
          onStateChange={onStateChange}
          onNotice={onNotice}
          onSelectTask={selectTask}
          onSelectAction={selectAction}
        />

        <section className="section-block record-composer">
          <div className="section-header">
            <div>
              <h2>现场记录</h2>
              <p>{isCenterExplanation ? '中心解释会单独留存在工作底稿中，不会被系统当作 CRA 已核实事实或自动生成发现。' : '原始记录保存后会在后台完成本地整理；整理期间仍可继续补充下一条自然语言记录。'}</p>
            </div>
            <span className="section-code">CRA NOTE</span>
          </div>
          <textarea
            value={recordText}
            onChange={(event) => { setRecordText(event.target.value); setDuplicateCandidates([]) }}
            disabled={!canEdit}
            placeholder={isCenterExplanation ? '例如：中心解释本次文件缺失系 CRC 交接期间暂未归档，预计于 2026-08-15 补齐。' : '例如：S-DEMO-001 已于筛选前完成 ICF V1.1 签署；原始病历中已记录知情过程，未见异常。'}
            aria-label="新增现场监查记录"
          />
          <div className="record-context-fields">
            <label>记录来源
              <select value={recordKind} disabled={!canEdit} onChange={(event) => setRecordKind(event.target.value as 'monitoring_note' | 'center_explanation')}>
                <option value="monitoring_note">CRA 监查记录</option>
                <option value="center_explanation">中心解释（独立留存）</option>
              </select>
            </label>
            <label>关联任务（可选）
              <select value={recordTaskId} disabled={!canEdit} onChange={(event) => setRecordTaskId(event.target.value)}>
                <option value="">不关联，由系统建议归类</option>
                {allTasks.map((task) => <option key={task.id} value={task.id}>{taskPositionLabel(task)} · {task.title}</option>)}
              </select>
            </label>
            <label>实际记录时间（可选）<input type="datetime-local" value={recordedAt} disabled={!canEdit} onChange={(event) => setRecordedAt(event.target.value)} /></label>
            <label>标签（可选）<input value={recordTags} disabled={!canEdit} onChange={(event) => setRecordTags(event.target.value)} placeholder="例如：现场、ICF、待跟进" /></label>
          </div>
          <div className="composer-footer">
            <span>{processingRecordCount > 0 ? `已有 ${processingRecordCount} 条记录正在后台整理，可继续输入。` : (recordLinkedTask ? `本条记录关联：${taskPositionLabel(recordLinkedTask)} · ${recordLinkedTask.title}` : '可直接输入，系统会自动建议目标表格')}</span>
            <button type="button" className="button primary" onClick={() => void addRecord()} disabled={saving || !canEdit}>{saving ? '正在保存…' : '保存并整理记录'}</button>
          </div>
        </section>

        {duplicateCandidates.length > 0 && <section className="section-block duplicate-record-review">
          <div className="section-header compact-header">
            <div><h2>发现疑似重复的现场记录</h2><p>系统仅按当前访视的规范化文本精确匹配，不会自动合并或删除。请由 CRA 决定是否仍保留为一条新的工作记录。</p></div>
            <span className="section-code">CRA DECISION</span>
          </div>
          <div className="duplicate-record-list">
            {duplicateCandidates.map((record) => {
              const linkedTask = allTasks.find((task) => task.id === record.linked_task_id)
              return <article key={record.id}><div><strong>{record.created_at} · {record.created_by || 'CRA'}</strong><p>{displayRecordText(record.text)}</p><small>{record.recorded_at && `现场时间：${record.recorded_at.replace('T', ' ')} `}{linkedTask && `关联：${taskPositionLabel(linkedTask)} · ${linkedTask.title} `}{(record.tags ?? []).length > 0 && `标签：${record.tags?.join(' · ')}`}</small></div></article>
            })}
          </div>
          <div className="duplicate-record-actions"><span>返回编辑不会写入任何新记录。</span><div><button type="button" className="button quiet" disabled={saving} onClick={() => setDuplicateCandidates([])}>返回修改</button><button type="button" className="button secondary" disabled={saving || !canEdit} onClick={() => void addRecord(true)}>仍保存为新记录</button></div></div>
        </section>}

        {canEdit ? <OfflineDraftsPanel
          state={state}
          draftText={recordText}
          onDraftStored={() => setRecordText('')}
          onStateChange={onStateChange}
          onNotice={onNotice}
        /> : <section className="section-block role-readonly-card"><strong>当前为只读工作台</strong><span>{reportLocked ? '本报告已进入审核/批准状态，CRA 工作底稿与任务结论已冻结。' : '离线草稿、现场记录和 CRA 建议确认仅由 CRA 在其工作区处理。'}</span></section>}

        <section className="section-block">
          <div className="section-header">
            <div>
              <h2>待 CRA 确认的建议</h2>
              <p>模拟引擎只做归类和专业化表达建议，不会自动写入最终报告。</p>
            </div>
            <div className="suggestion-header-actions">
              <span className="pending-count">{pending.length} 条待处理</span>
              {canEdit && pending.length > 0 && <div className="suggestion-batch-actions">
                <button type="button" className="button small quiet" disabled={batchDeciding || selectedPendingIds.length === 0} onClick={() => void decideSelectedSuggestions('accepted')}>批量接受{selectedPendingIds.length ? ` (${selectedPendingIds.length})` : ''}</button>
                <button type="button" className="button small danger-text" disabled={batchDeciding || selectedPendingIds.length === 0} onClick={() => void decideSelectedSuggestions('rejected')}>批量拒绝</button>
                {selectedPendingIds.length > 0 && <button type="button" className="button-link subtle" disabled={batchDeciding} onClick={() => setSelectedSuggestionIds([])}>清除选择</button>}
              </div>}
            </div>
          </div>

          <datalist id="suggestion-decision-reasons"><option value="补充原始记录已载明信息" /><option value="更正原文提取错误" /><option value="仅规范术语，未改变事实" /><option value="CRA 对照原始记录后调整表述" /></datalist>
          {pending.length === 0 ? (
            <div className="empty-state"><strong>当前没有待确认建议</strong><span>新增一条现场记录后，建议会出现在这里。</span></div>
          ) : (
            <div className="suggestion-list">
              {pending.map((suggestion) => (
                <article className="suggestion-row" key={suggestion.id}>
                  <div className="suggestion-meta">
                    {canEdit && <label className="suggestion-select"><input type="checkbox" checked={selectedPendingIds.includes(suggestion.id)} disabled={batchDeciding} onChange={() => toggleSuggestionSelection(suggestion.id)} /><span>选择</span></label>}
                    <span>表 {suggestion.target_table}</span>
                    <span>{categoryLabels[suggestion.category] ?? suggestion.category}</span>
                  </div>
                  <div className="suggestion-copy">
                    <h3>{suggestion.title}</h3>
                    {canEdit && <label className="suggestion-routing">建议归类到
                      <select value={suggestion.target_task_id || allTasks.find((task) => task.index === suggestion.target_table)?.id || ''} disabled={routingSuggestionId === suggestion.id || batchDeciding} onChange={(event) => void assignSuggestionTarget(suggestion, event.target.value)}>
                        <option value="">请选择监查任务</option>
                        {allTasks.map((task) => <option key={task.id} value={task.id}>{taskPositionLabel(task)} · {task.title}</option>)}
                      </select>
                    </label>}
                    {editingId === suggestion.id ? (
                      <><textarea value={displaySuggestionText(editedText, suggestion)} onChange={(event) => setEditedText(restoreSuggestionDisplayText(event.target.value, suggestion))} aria-label={`修改 ${suggestion.title}`} /><label className="suggestion-edit-reason">{criticalEditCategories.has(suggestion.category) ? '修改原因（必填）' : '修改原因（可选）'}<input required={criticalEditCategories.has(suggestion.category)} list="suggestion-decision-reasons" value={editDecisionReason} onChange={(event) => setEditDecisionReason(event.target.value)} placeholder={criticalEditCategories.has(suggestion.category) ? '请说明与原建议不一致的依据' : '可选标准原因或自定义说明'} aria-label={`修改 ${suggestion.title} 的原因`} /></label></>
                    ) : (
                      <p>{displayRecordText(displaySuggestionText(suggestion.proposed_text, suggestion))}</p>
                    )}
                    <small>来源记录：{displayRecordText(displaySuggestionText(suggestion.source, suggestion))}</small>
                    <div className="suggestion-trace" aria-label={`${suggestion.title} 的来源与整理留痕`}>
                      <span>{assertionTypeLabels[suggestion.assertion_type ?? ''] ?? '待确认建议'}</span>
                      <span>{entityTypeLabels[suggestion.entity_type ?? ''] ?? '关联对象'}：{suggestion.subject_display_code || displaySuggestionText(suggestion.entity_id || suggestion.subject || '本次访视', suggestion)}</span>
                      <span className={`subject-validation is-${suggestion.subject_validation_status ?? 'not_provided'}`}>{subjectValidationLabels[suggestion.subject_validation_status ?? 'not_provided'] ?? '编号状态未知'}</span>
                      <span>证据范围：{suggestion.evidence_start ?? 0}–{suggestion.evidence_end ?? suggestion.source.length}</span>
                      <span title={suggestion.ai_execution_id || ''}>执行：{shortTraceId(suggestion.ai_execution_id)}</span>
                      <small>{suggestion.pending_reason || '需 CRA 对照原始记录确认'}</small>
                    </div>
                    {suggestion.source_type === 'center_explanation' && <div className="center-explanation-note">中心解释将独立随工作底稿留存；请另行记录 CRA 核实事实或评价，不会自动生成发现或行动项。</div>}
                  </div>
                  {canEdit ? <div className="suggestion-actions">
                    {editingId === suggestion.id ? (
                      <>
                        <button type="button" className="button primary small" onClick={() => decide(suggestion, 'edited')}>确认修改</button>
                        <button type="button" className="button quiet small" onClick={() => { setEditingId(null); setEditDecisionReason('') }}>取消</button>
                      </>
                    ) : (
                      <>
                        <button type="button" className="button primary small" onClick={() => decide(suggestion, 'accepted')}>接受</button>
                        <button type="button" className="button quiet small" onClick={() => { setEditingId(suggestion.id); setEditedText(suggestion.proposed_text); setEditDecisionReason('') }}>修改</button>
                        <button type="button" className="button danger-text small" onClick={() => decide(suggestion, 'rejected')}>拒绝</button>
                      </>
                    )}
                  </div> : <div className="suggestion-actions readonly-suggestion"><span>等待 CRA 确认</span></div>}
                </article>
              ))}
            </div>
          )}
        </section>

        {centerExplanations.length > 0 && <section className="section-block center-explanation-ledger">
          <div className="section-header compact-header">
            <div><h2>已独立留存的中心解释</h2><p>以下内容仅作为中心陈述和工作底稿证据保存；不会写入报告，也不会替代 CRA 的核实事实或监查评价。</p></div>
            <span className="section-code">CENTER NOTE</span>
          </div>
          <div className="center-explanation-list">
            {centerExplanations.map((item) => {
              const subject = item.subject || item.subject_code || ''
              return <article key={item.id}>
                <div className="center-explanation-meta">
                  <span>表 {item.target_table}</span>
                  <span>{categoryLabels[item.category] ?? item.category}</span>
                  <span className={`subject-validation is-${item.subject_validation_status ?? 'not_provided'}`}>{subjectValidationLabels[item.subject_validation_status ?? 'not_provided'] ?? '编号状态未标注'}</span>
                </div>
                <p>{displayRecordText(displaySubjectText(item.text || item.value || item.report_text || '', subject, item.subject_display_code || ''))}</p>
                <small>由 {item.confirmed_at || 'CRA'} 确认独立留存{item.decision_reason ? ` · 修改说明：${item.decision_reason}` : ''}</small>
              </article>
            })}
          </div>
        </section>}

        {correctingRecord && <section className="section-block record-correction-panel">
          <div className="section-header compact-header">
            <div><h2>追加更正记录</h2><p>原始记录将完整保留；请新增更正后的描述并说明原因。系统不会自动改写已确认事实。</p></div>
            <span className="section-code">CORRECTION</span>
          </div>
          <div className="correction-origin"><span>原始记录</span><p>{displayRecordText(correctingRecord.text)}</p><small>{correctingRecord.created_at} · {correctingRecord.created_by || 'CRA'}</small></div>
          <div className="correction-fields">
            <label>更正后内容<textarea value={correctionText} disabled={!canEdit || correctionSaving} onChange={(event) => setCorrectionText(event.target.value)} aria-label="更正后内容" /></label>
            <label>更正原因<input value={correctionReason} disabled={!canEdit || correctionSaving} onChange={(event) => setCorrectionReason(event.target.value)} placeholder="例如：补充核对原始病历后更正受试者编号" aria-label="更正原因" /></label>
          </div>
          <div className="correction-actions"><span>保存后会新增一条“更正记录”，并进入现有 CRA 建议确认流程。</span><div><button type="button" className="button quiet" disabled={correctionSaving} onClick={() => { setCorrectingRecordId(null); setCorrectionText(''); setCorrectionReason('') }}>取消</button><button type="button" className="button secondary" disabled={!canEdit || correctionSaving} onClick={() => void saveCorrection()}>{correctionSaving ? '正在保存…' : '保存更正记录'}</button></div></div>
        </section>}

        {voidingRecord && <section className="section-block record-void-panel">
          <div className="section-header compact-header">
            <div><h2>撤销受控监查记录</h2><p>撤销不会删除原始文本。该记录来源的待确认建议和已确认字段将退出当前报告上下文，已生成或已提交的历史版本不会被改写。</p></div>
            <span className="section-code">VOID RECORD</span>
          </div>
          <div className="void-origin"><span>待撤销记录</span><p>{displayRecordText(voidingRecord.text)}</p><small>{voidingRecord.created_at} · {voidingRecord.created_by || 'CRA'}</small></div>
          <div className="void-fields"><label>撤销原因<input value={voidReason} disabled={!canEdit || voidSaving} onChange={(event) => setVoidReason(event.target.value)} placeholder="例如：该条为重复现场记录，已由后续记录完整覆盖" aria-label="撤销原因" /></label></div>
          <div className="void-actions"><span>确认后记录会显示为“已撤销”，并保留原因与时间。</span><div><button type="button" className="button quiet" disabled={voidSaving} onClick={() => { setVoidingRecordId(null); setVoidReason('') }}>取消</button><button type="button" className="button danger-text" disabled={!canEdit || voidSaving} onClick={() => void voidRecord()}>{voidSaving ? '正在撤销…' : '确认撤销记录'}</button></div></div>
        </section>}

        <section className="section-block recent-records">
          <div className="section-header compact-header">
            <div><h2>最近记录</h2><p>保留 CRA 的碎片化输入，便于回看。</p></div>
          </div>
          {recentRecords.length === 0 ? <div className="empty-state inline"><span>尚未新增现场记录。</span></div> : (
            <div className="record-list">
              {recentRecords.map((record) => {
                const linkedTask = allTasks.find((task) => task.id === record.linked_task_id)
                const isVoided = record.record_status === 'voided'
                const processingStatus = record.processing_status || 'completed'
                const modificationHistory = record.modification_history ?? []
                return <div className={`record-line ${record.record_kind === 'correction' ? 'is-correction' : ''} ${record.record_kind === 'center_explanation' ? 'is-center-explanation' : ''} ${isVoided ? 'is-voided' : ''}`} key={record.id}>
                  <time>{record.created_at}</time>
                  <div>
                    <div className="record-copy-heading">
                      {record.record_kind !== 'monitoring_note' && <span>{recordKindLabels[record.record_kind ?? ''] ?? record.record_kind}</span>}
                      {isVoided && <span className="record-void-badge">已撤销</span>}
                      <small>{record.created_by || 'CRA'}</small>
                    </div>
                    <p>{displayRecordText(record.text)}</p>
                    {(record.recorded_at || linkedTask || (record.tags ?? []).length > 0) && <small className="record-context-summary">{record.recorded_at && <span>现场时间：{record.recorded_at.replace('T', ' ')}</span>}{linkedTask && <span>关联：{taskPositionLabel(linkedTask)} · {linkedTask.title}</span>}{(record.tags ?? []).length > 0 && <span>标签：{record.tags?.join(' · ')}</span>}</small>}
                    {(record.client_created_at || record.server_received_at || record.text_hash || record.processing_status) && <small className="record-provenance"><span className={`record-processing-status is-${processingStatus}`}>{recordProcessingLabel(processingStatus)}</span>{record.client_created_at && <span>客户端：{displayRecordTime(record.client_created_at)}{record.client_timezone ? ` · ${record.client_timezone}` : ''}</span>}{record.server_received_at && <span>服务端：{displayRecordTime(record.server_received_at)}</span>}{record.text_hash && <span>指纹：<code title={record.text_hash}>{record.text_hash.slice(0, 12)}…</code></span>}{processingStatus === 'failed' && record.processing_error && <span className="record-processing-error">整理说明：{record.processing_error}</span>}</small>}
                    {record.corrected_record_id && <small className="record-correction-link">更正原始记录 · 原因：{record.correction_reason || '未填写'}</small>}
                    {modificationHistory.length > 0 && <small className="record-modification-history">后续更正：{modificationHistory.length} 条 · 最近一次 {modificationHistory[0].created_at || '未记录时间'} · {modificationHistory[0].actor_name || 'CRA'}{modificationHistory[0].reason ? ` · ${modificationHistory[0].reason}` : ''}{modificationHistory[0].record_status === 'voided' ? ' · 该更正已撤销' : ''}</small>}
                    {isVoided && <small className="record-void-reason">撤销原因：{record.void_reason || '未填写'}{record.voided_at ? ` · ${record.voided_at}` : ''}{record.voided_by ? ` · ${record.voided_by}` : ''}</small>}
                  </div>
                  {canEdit && !isVoided && <div className="record-line-actions">
                    {record.record_kind !== 'correction' && <button type="button" className="button-link" onClick={() => beginCorrection(record)}>更正</button>}
                    <button type="button" className="button-link danger" onClick={() => beginVoid(record)}>撤销</button>
                  </div>}
                </div>
              })}
            </div>
          )}
        </section>

        <ActionItemsPanel state={state} onStateChange={onStateChange} onNotice={onNotice} focusActionId={selectedActionId} />
      </div>
    </div>
  )
}
