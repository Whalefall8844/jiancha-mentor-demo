import { useEffect, useState } from 'react'
import { api, reportStatusLabel } from '../api'
import type { DemoState, EvidenceChain, LanguageSuggestion, ReportReadiness, ReviewComment, RulePack, TemplateSummary, TemplateSwitchPreview, VisitDateReassessmentPreview } from '../types'
import { buildReportPreviewParagraphs, reviewCommentLabel, reviewTargetLabel } from '../reportPreview'
import { readTemplateCompletenessRules, templateFieldCompletenessLabels, templateTaskCompletenessLabels } from '../templateCompletenessRules'

interface ReportPageProps {
  state: DemoState
  onStateChange: (state: DemoState) => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

const decisionLabels: Record<string, string> = {
  accepted: '接受建议',
  edited: 'CRA 修改后确认',
  rejected: '已拒绝',
}

const languageStatusLabels: Record<string, string> = {
  pending: '待 CRA 决定',
  accepted: '已采用',
  edited: '已修改采用',
  rejected: '未采用',
  revoked: '已撤销采用',
}

const assertionTypeLabels: Record<string, string> = {
  reported_observation: '现场记录事实',
  monitoring_summary: '监查小结建议',
  action_request: '后续跟进建议',
  center_explanation: '中心解释（独立留存）',
}

const subjectValidationLabels: Record<string, string> = {
  valid: '编号已校验',
  unverified: '编号未在本中心清单中',
  not_provided: '未识别受试者编号',
  historical_unverified: '历史记录未校验',
}

const subjectCodeCandidatePattern = /(?<![A-Za-z0-9])(?:[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+|[A-Za-z]{1,4}[-_]?\d{3,6}|\d{3}[-_]\d{3})(?![A-Za-z0-9]|[-_]\*{3})/g

const maskSubjectCode = (value: string) => {
  if (value.includes('-') || value.includes('_')) {
    const normalized = value.replaceAll('_', '-')
    const prefix = normalized.slice(0, normalized.lastIndexOf('-'))
    return prefix ? `${prefix}-***` : '***'
  }
  return value.length <= 2 ? '**' : `${value.slice(0, 2)}${'*'.repeat(Math.max(2, value.length - 2))}`
}

const shortTraceId = (value?: string) => value ? `${value.slice(0, 8)}…` : '—'

export function ReportPage({ state, onStateChange, onNotice }: ReportPageProps) {
  const mappedCount = state.table_tasks.filter((item) => item.status !== '待补录').length
  const tableCount = state.table_tasks.length
  const revisions = state.revisions ?? []
  const latestRevision = revisions[0]
  const isCRA = state.current_role === 'CRA'
  const isQaClinicalOps = state.current_role === 'QA_CLINICAL_OPS'
  const frozenCompletenessRules = readTemplateCompletenessRules(state.visit.snapshot?.template_completeness_rules as Record<string, unknown> | undefined)
  const [evidence, setEvidence] = useState<EvidenceChain | null>(null)
  const [readiness, setReadiness] = useState<ReportReadiness | null>(null)
  const [editTexts, setEditTexts] = useState<Record<string, string>>({})
  const [languageRevokeReasons, setLanguageRevokeReasons] = useState<Record<string, string>>({})
  const [revokingLanguageId, setRevokingLanguageId] = useState<string | null>(null)
  const [languageRevoking, setLanguageRevoking] = useState(false)
  const [commentNotes, setCommentNotes] = useState<Record<string, string>>({})
  const [submitConfirmed, setSubmitConfirmed] = useState(false)
  const [availableTemplates, setAvailableTemplates] = useState<TemplateSummary[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [templatePreview, setTemplatePreview] = useState<TemplateSwitchPreview | null>(null)
  const [templateBusy, setTemplateBusy] = useState(false)
  const [reassessmentDate, setReassessmentDate] = useState(state.visit.visit_date)
  const [reassessmentRules, setReassessmentRules] = useState<RulePack[]>([])
  const [selectedReassessmentRuleId, setSelectedReassessmentRuleId] = useState(state.rule_pack?.id ?? '')
  const [reassessmentPreview, setReassessmentPreview] = useState<VisitDateReassessmentPreview | null>(null)
  const [reassessmentBusy, setReassessmentBusy] = useState(false)
  const [withdrawReason, setWithdrawReason] = useState('')
  const [withdrawing, setWithdrawing] = useState(false)
  const [voidReason, setVoidReason] = useState('')
  const [voiding, setVoiding] = useState(false)
  const displayEvidenceText = (value: string) => state.project.subject_code_display_mode === 'full'
    ? value
    : value.replace(subjectCodeCandidatePattern, (candidate) => maskSubjectCode(candidate))

  const loadEvidence = async (quiet = false) => {
    if (!state.visit.id) return
    try {
      setEvidence(await api.getEvidenceChain(state.visit.id))
    } catch (error) {
      if (!quiet) onNotice(error instanceof Error ? error.message : '证据链加载失败', 'error')
    }
  }

  const loadReadiness = async (quiet = false) => {
    if (!state.visit.id) return
    try {
      setReadiness(await api.getReportReadiness(state.visit.id))
    } catch (error) {
      if (!quiet) onNotice(error instanceof Error ? error.message : '报告预检加载失败', 'error')
    }
  }

  useEffect(() => {
    void loadEvidence(true)
    void loadReadiness(true)
  }, [state.visit.id])

  useEffect(() => {
    let cancelled = false
    const loadTemplates = async () => {
      try {
        const response = await api.listTemplates()
        if (!cancelled) setAvailableTemplates(response.items.filter((item) => item.id !== state.template?.id))
      } catch (error) {
        if (!cancelled) onNotice(error instanceof Error ? error.message : '可切换模板加载失败', 'error')
      }
    }
    void loadTemplates()
    return () => { cancelled = true }
  }, [state.visit.id, state.template?.id])

  useEffect(() => {
    setReassessmentDate(state.visit.visit_date)
    setSelectedReassessmentRuleId(state.rule_pack?.id ?? '')
    setReassessmentPreview(null)
  }, [state.visit.id, state.visit.visit_date, state.rule_pack?.id])

  useEffect(() => {
    let cancelled = false
    const loadApplicableRules = async () => {
      if (!state.visit.project_id || !reassessmentDate.trim()) {
        setReassessmentRules([])
        return
      }
      try {
        const response = await api.listRulePackEligibility(state.visit.project_id, reassessmentDate)
        if (cancelled) return
        setReassessmentRules(response.items)
        setSelectedReassessmentRuleId((current) => {
          if (response.items.some((item) => item.id === current && item.eligibility?.selectable)) return current
          const currentRule = response.items.find((item) => item.id === state.rule_pack?.id && item.eligibility?.selectable)
          return currentRule?.id ?? response.items.find((item) => item.eligibility?.selectable)?.id ?? ''
        })
      } catch (error) {
        if (!cancelled) onNotice(error instanceof Error ? error.message : '适用规则包加载失败', 'error')
      }
    }
    void loadApplicableRules()
    return () => { cancelled = true }
  }, [state.visit.id, state.visit.project_id, state.rule_pack?.id, reassessmentDate])

  const refresh = async () => {
    if (!state.visit.id) return
    onStateChange(await api.getState(state.visit.id))
    await loadEvidence(true)
    await loadReadiness(true)
  }

  const previewTemplateSwitch = async (templateId: string) => {
    setSelectedTemplateId(templateId)
    setTemplatePreview(null)
    if (!state.visit.id || !templateId) return
    try {
      setTemplateBusy(true)
      setTemplatePreview(await api.getTemplateSwitchPreview(state.visit.id, templateId))
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '模板迁移预览加载失败', 'error')
    } finally {
      setTemplateBusy(false)
    }
  }

  const applyTemplateSwitch = async () => {
    if (!state.visit.id || !selectedTemplateId || !templatePreview?.can_switch || !isCRA) return
    try {
      setTemplateBusy(true)
      const result = await api.switchVisitTemplate(state.visit.id, selectedTemplateId, state.visit.cra_name)
      onStateChange(result.workspace)
      setSelectedTemplateId('')
      setTemplatePreview(null)
      onNotice(`已切换至 ${result.preview.to_template.name}；可迁移内容已带入，新增区域请补录。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '切换报告模板失败', 'error')
    } finally {
      setTemplateBusy(false)
    }
  }

  const rollbackTemplateSwitch = async (switchId: string) => {
    if (!state.visit.id || !isCRA) return
    try {
      setTemplateBusy(true)
      const result = await api.rollbackVisitTemplateSwitch(state.visit.id, switchId, state.visit.cra_name)
      onStateChange(result.workspace)
      setSelectedTemplateId('')
      setTemplatePreview(null)
      onNotice(`已恢复至 ${result.preview.to_template.name}；原模板可匹配内容已重新带回。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '恢复上一模板失败', 'error')
    } finally {
      setTemplateBusy(false)
    }
  }

  const previewDateReassessment = async () => {
    if (!state.visit.id || !reassessmentDate.trim() || !isCRA) return
    try {
      setReassessmentBusy(true)
      const preview = await api.getVisitDateReassessmentPreview(state.visit.id, reassessmentDate, selectedReassessmentRuleId)
      setReassessmentPreview(preview)
      if (preview.to_rule_pack.id) setSelectedReassessmentRuleId(preview.to_rule_pack.id)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '访视日期重评估预览加载失败', 'error')
    } finally {
      setReassessmentBusy(false)
    }
  }

  const applyDateReassessment = async () => {
    if (!state.visit.id || !reassessmentPreview?.can_apply || !isCRA) return
    try {
      setReassessmentBusy(true)
      const result = await api.applyVisitDateReassessment(state.visit.id, {
        visit_date: reassessmentDate,
        rule_pack_id: reassessmentPreview.to_rule_pack.id || selectedReassessmentRuleId,
        actor_name: state.visit.cra_name,
      })
      onStateChange(result.workspace)
      setReassessmentDate(result.workspace.visit.visit_date)
      setReassessmentPreview(null)
      await loadEvidence(true)
      await loadReadiness(true)
      onNotice(`已将监查日期调整为 ${result.workspace.visit.visit_date}，并重新冻结适用规则与受控资料。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '访视日期重新冻结失败', 'error')
    } finally {
      setReassessmentBusy(false)
    }
  }

  const generate = async () => {
    if (!state.visit.id || !isCRA) return
    if (!readiness?.ready) {
      onNotice('请先处理报告预检中的阻断项，再生成 Word。', 'error')
      return
    }
    try {
      const revision = await api.generateVisitRevision(state.visit.id, state.visit.cra_name)
      const filename = await api.downloadRevision(revision.id)
      await refresh()
      onNotice(`已生成 ${revision.version_number} 并下载真实 Word 文件：${filename}`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : 'Word 生成失败', 'error')
    }
  }

  const submit = async () => {
    if (!state.visit.id || !latestRevision || !isCRA) return
    if (!submitConfirmed) {
      onNotice('请先勾选 CRA 报告确认声明。', 'error')
      return
    }
    try {
      await api.submitRevision(latestRevision.id, state.visit.cra_name, true)
      await refresh()
      setSubmitConfirmed(false)
      onNotice('CRA 已确认并提交报告，PM/LM 现可进行审核。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '报告提交失败', 'error')
    }
  }

  const withdraw = async () => {
    if (!state.visit.id || !latestRevision || !isCRA) return
    if (!withdrawReason.trim()) {
      onNotice('请填写主动撤回原因，原提交版本会保留在版本链中。', 'error')
      return
    }
    try {
      setWithdrawing(true)
      const result = await api.withdrawRevision(latestRevision.id, {
        cra_name: state.visit.cra_name,
        reason: withdrawReason,
      })
      onStateChange(result.workspace)
      setWithdrawReason('')
      await loadEvidence(true)
      await loadReadiness(true)
      onNotice(`已撤回 ${result.withdrawn_revision.version_number}，并创建关联工作修订 ${result.working_revision.version_number}。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '报告撤回失败', 'error')
    } finally {
      setWithdrawing(false)
    }
  }

  const voidApprovedReport = async () => {
    if (!state.visit.id || !latestRevision || !isQaClinicalOps) return
    if (!voidReason.trim()) {
      onNotice('请填写作废原因；原批准版本会保留在版本链中。', 'error')
      return
    }
    const actorName = state.project_members.find((member) => member.role === 'QA_CLINICAL_OPS' && member.status === 'active')?.display_name || 'QA/临床运营审批人'
    try {
      setVoiding(true)
      const result = await api.voidRevision(latestRevision.id, {
        actor_name: actorName,
        reason: voidReason,
      })
      onStateChange(result.workspace)
      setVoidReason('')
      await loadEvidence(true)
      await loadReadiness(true)
      onNotice(`已作废 ${result.voided_revision.version_number}，并创建关联工作修订 ${result.working_revision.version_number} 供 CRA 重新核对。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '报告作废失败', 'error')
    } finally {
      setVoiding(false)
    }
  }

  const generateLanguage = async () => {
    if (!state.visit.id || !isCRA) return
    try {
      const result = await api.generateLanguageSuggestions(state.visit.id, state.visit.cra_name)
      await refresh()
      onNotice(result.items.length ? `已生成 ${result.items.length} 条受控语言候选稿。` : '没有发现需要优化的已确认文字。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '语言优化建议生成失败', 'error')
    }
  }

  const decideLanguage = async (item: LanguageSuggestion, decision: 'accepted' | 'edited' | 'rejected') => {
    if (!state.visit.id || !isCRA) return
    try {
      await api.decideLanguageSuggestion(state.visit.id, item.id, {
        decision,
        actor_name: state.visit.cra_name,
        edited_text: decision === 'edited' ? editTexts[item.id] : undefined,
      })
      await refresh()
      onNotice(decision === 'rejected' ? '该语言候选稿已保留为不采用记录。' : '展示文本已由 CRA 确认；原始确认事实未被改写。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '语言建议处理失败', 'error')
    }
  }

  const revokeLanguage = async (item: LanguageSuggestion) => {
    if (!state.visit.id || !isCRA) return
    const reason = (languageRevokeReasons[item.id] ?? '').trim()
    if (!reason) {
      onNotice('请填写撤销语言采用的原因。', 'error')
      return
    }
    try {
      setLanguageRevoking(true)
      await api.revokeLanguageSuggestion(state.visit.id, item.id, {
        actor_name: state.visit.cra_name,
        reason,
      })
      setLanguageRevokeReasons((current) => {
        const next = { ...current }
        delete next[item.id]
        return next
      })
      setRevokingLanguageId(null)
      await refresh()
      onNotice('已撤销该语言采用，报告展示已恢复为原始确认文字。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '撤销语言采用失败', 'error')
    } finally {
      setLanguageRevoking(false)
    }
  }

  const resolveComment = async (comment: ReviewComment, resolution: 'accepted' | 'declined') => {
    if (!state.visit.id || !isCRA) return
    try {
      await api.resolveReviewComment(state.visit.id, comment.id, {
        resolution,
        note: commentNotes[comment.id] ?? '',
        actor_name: state.visit.cra_name,
      })
      await refresh()
      onNotice(resolution === 'accepted' ? '已记录 CRA 接受该审核建议。' : '已记录 CRA 不采用该审核建议。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '审核意见处置失败', 'error')
    }
  }

  const download = async (run: () => Promise<string>, errorMessage: string) => {
    try {
      const filename = await run()
      onNotice(`已下载：${filename}`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : errorMessage, 'error')
    }
  }

  const languageSuggestions = state.language_suggestions ?? []
  const openComments = state.review_comments.filter((item) => item.status !== 'resolved')
  const previewParagraphs = buildReportPreviewParagraphs(state)
  const openCommentsByTarget = new Map<string, ReviewComment[]>()
  for (const comment of openComments) {
    const key = comment.target_key ?? ''
    openCommentsByTarget.set(key, [...(openCommentsByTarget.get(key) ?? []), comment])
  }
  const canSubmit = isCRA && !!latestRevision && ['draft', 'returned'].includes(latestRevision.status)
  const canWithdraw = isCRA && latestRevision?.status === 'submitted' && !latestRevision.review_started_at
  const canSwitchTemplate = isCRA && ['draft', 'returned'].includes(state.report_status)
  const canReassessDate = isCRA && ['draft', 'returned'].includes(state.report_status)
  const templateSwitches = state.template_switches ?? []
  const dateReassessments = state.visit_date_reassessments ?? []
  const revertibleSwitch = templateSwitches.find((item) => !item.rolled_back_at && item.to_template_id === state.template?.id)

  return (
    <div className="page-stack">
      <section className="report-hero">
        <div>
          <p className="eyebrow">{state.template ? `${state.template.name} · ${state.template.version}` : '当前冻结 Word 模板'} · {tableCount} 张表</p>
          <h2>报告输出与 CRA 确认</h2>
          <p>Word 始终基于当前访视冻结的模板、规则包和 CRA 已确认信息生成。语言优化仅改变 CRA 选择采用的展示文本。</p>
        </div>
        <div className="report-hero-stats">
          <div><span>工作底稿</span><strong>{mappedCount}<small>/{tableCount}</small></strong></div>
          <div><span>规则版本</span><strong className="status-word">{state.rule_pack?.version ?? '—'}</strong></div>
        </div>
      </section>

      <section className="section-block template-switch-card">
        <div className="section-header compact-header">
          <div>
            <p className="eyebrow">TEMPLATE MIGRATION</p>
            <h2>更换报告模板</h2>
            <p>先预览任务和已确认事实的迁移差异，再由 CRA 确认。未匹配内容保留在工作底稿历史中，不会被删除。</p>
          </div>
          <span className={`template-switch-status ${canSwitchTemplate ? 'is-editable' : ''}`}>{canSwitchTemplate ? '可在提交前切换' : '当前报告已锁定模板'}</span>
        </div>
        <div className="template-switch-controls">
          <label>目标 Word 模板
            <select aria-label="目标报告模板" value={selectedTemplateId} disabled={!canSwitchTemplate || templateBusy} onChange={(event) => void previewTemplateSwitch(event.target.value)}>
              <option value="">请选择已启用模板</option>
              {availableTemplates.map((template) => <option key={template.id} value={template.id}>{template.name} · {template.version} · {template.table_count} 表</option>)}
            </select>
          </label>
          <small>{availableTemplates.length ? '系统按稳定字段键优先匹配；历史默认映射可按相同表号回退匹配。' : '当前没有其他已启用模板可供切换。'}</small>
        </div>
        {templatePreview && <div className={`template-migration-preview ${templatePreview.can_switch ? 'is-ready' : 'has-issues'}`}>
          <div className="template-migration-heading"><strong>{templatePreview.from_template.name} · {templatePreview.from_template.version}</strong><span>→</span><strong>{templatePreview.to_template.name} · {templatePreview.to_template.version}</strong></div>
          {!templatePreview.can_switch ? <p className="template-migration-warning">{templatePreview.reason || '当前模板组合不可切换。'}</p> : <>
            <dl className="template-migration-summary">
              <div><dt>保留任务</dt><dd>{templatePreview.summary.preserved_tasks}</dd></div>
              <div><dt>新增待补录</dt><dd>{templatePreview.summary.new_tasks}</dd></div>
              <div><dt>暂不写入</dt><dd>{templatePreview.summary.hidden_tasks + templatePreview.summary.hidden_confirmed_fields}</dd></div>
              <div><dt>确认字段带入</dt><dd>{templatePreview.summary.migratable_confirmed_fields}</dd></div>
            </dl>
            <div className="template-migration-notes">
              <span>建议：带入 {templatePreview.summary.migratable_suggestions}</span>
              <span>建议暂存：{templatePreview.summary.hidden_suggestions}</span>
              <span>字段暂存：{templatePreview.summary.hidden_confirmed_fields}</span>
            </div>
            <button type="button" className="button primary" disabled={!canSwitchTemplate || templateBusy} onClick={() => void applyTemplateSwitch()}>确认切换并保留可迁移内容</button>
          </>}
        </div>}
        {templateSwitches.length > 0 && <div className="template-switch-history">
          <strong>模板切换记录</strong>
          {templateSwitches.map((item) => <div className="template-switch-history-row" key={item.id}>
            <span>{item.from_template_name} · {item.from_template_version} → {item.to_template_name} · {item.to_template_version}</span>
            <small>{item.actor_name} · {item.created_at}{item.rolled_back_at ? ` · 已于 ${item.rolled_back_at} 恢复` : ''}</small>
            {revertibleSwitch?.id === item.id && canSwitchTemplate && <button type="button" className="button small quiet" disabled={templateBusy} onClick={() => void rollbackTemplateSwitch(item.id)}>恢复上一模板</button>}
          </div>)}
        </div>}
      </section>

      <section className="section-block date-reassessment-card">
        <div className="section-header compact-header">
          <div>
            <p className="eyebrow">DATE REASSESSMENT</p>
            <h2>调整监查日期并重新冻结</h2>
            <p>草稿期调整日期前，先核对适用规则包、PI／方案／ICF／伦理等受控资料，以及系统／设备核查任务的延续范围。已有工作记录、15 张 Word 表任务和已确认事实不会被改写。</p>
          </div>
          <span className={`template-switch-status ${canReassessDate ? 'is-editable' : ''}`}>{canReassessDate ? '可在提交前调整' : '当前报告已锁定日期'}</span>
        </div>
        <div className="date-reassessment-controls">
          <label>新的监查日期
            <input aria-label="新的监查日期" value={reassessmentDate} disabled={!canReassessDate || reassessmentBusy} onChange={(event) => { setReassessmentDate(event.target.value); setReassessmentPreview(null) }} placeholder="YYYY-MM-DD" />
          </label>
          <label>重新冻结的规则包
            <select aria-label="重新冻结的规则包" value={selectedReassessmentRuleId} disabled={!canReassessDate || reassessmentBusy || !reassessmentDate.trim()} onChange={(event) => { setSelectedReassessmentRuleId(event.target.value); setReassessmentPreview(null) }}>
              <option value="">由系统推荐适用规则包</option>
              {reassessmentRules.map((rulePack) => <option key={rulePack.id} value={rulePack.id} disabled={!rulePack.eligibility?.selectable}>{rulePack.name} · {rulePack.version} · {rulePack.eligibility?.selectable ? '适用' : rulePack.eligibility?.message ?? '不适用'}</option>)}
            </select>
          </label>
          <div className="date-reassessment-action">
            <button type="button" className="button quiet" disabled={!canReassessDate || reassessmentBusy || !reassessmentDate.trim()} onClick={() => void previewDateReassessment()}>预览重新冻结</button>
            <small>不会在预览时修改访视或工作底稿。</small>
          </div>
        </div>
        {reassessmentPreview && <div className={`date-reassessment-preview ${reassessmentPreview.can_apply ? 'is-ready' : 'has-issues'}`}>
          <div className="template-migration-heading"><strong>{reassessmentPreview.visit.from_visit_date}</strong><span>→</span><strong>{reassessmentPreview.visit.to_visit_date}</strong></div>
          {!reassessmentPreview.can_apply ? <p className="template-migration-warning">{reassessmentPreview.reason || '当前日期与规则包组合不能重新冻结。'}</p> : <>
            <dl className="template-migration-summary">
              <div><dt>受控资料变化</dt><dd>{reassessmentPreview.summary.changed_master_items}</dd></div>
              <div><dt>保留系统任务</dt><dd>{reassessmentPreview.summary.preserved_system_tasks}</dd></div>
              <div><dt>新增待补录</dt><dd>{reassessmentPreview.summary.new_system_tasks}</dd></div>
              <div><dt>归入历史底稿</dt><dd>{reassessmentPreview.summary.archived_system_tasks}</dd></div>
            </dl>
            <div className="date-reassessment-detail-grid">
              <div>
                <strong>冻结资料差异</strong>
                <p>{reassessmentPreview.master_data_changes.site_profile.changed ? `中心资料：${reassessmentPreview.master_data_changes.site_profile.from.display || '未登记'} → ${reassessmentPreview.master_data_changes.site_profile.to.display || '未登记'}` : '中心资料版本不变。'}</p>
                {reassessmentPreview.master_data_changes.documents.filter((item) => item.changed).map((item) => <p key={item.document_type}>{item.document_type.toUpperCase()}：{item.from.display || item.from.title || '未登记'} → {item.to.display || item.to.title || '未登记'}</p>)}
                <small>{reassessmentPreview.site_team.message}</small>
              </div>
              <div>
                <strong>监查活动上下文</strong>
                <p>{reassessmentPreview.visit_context.from.activity_start_date} → {reassessmentPreview.visit_context.from.activity_end_date} 将调整为 {reassessmentPreview.visit_context.to.activity_start_date} → {reassessmentPreview.visit_context.to.activity_end_date}</p>
                <small>{reassessmentPreview.visit_context.message}</small>
              </div>
              <div>
                <strong>规则与系统／设备任务</strong>
                <p>{reassessmentPreview.from_rule_pack.name} · {reassessmentPreview.from_rule_pack.version} → {reassessmentPreview.to_rule_pack.name} · {reassessmentPreview.to_rule_pack.version}</p>
                {reassessmentPreview.system_task_changes.changes.length === 0 ? <small>新旧规则均未配置系统／设备核查任务。</small> : <div className="date-reassessment-task-notes">{reassessmentPreview.system_task_changes.changes.map((item) => <span key={`${item.action}-${item.field_key}`}>{item.action === 'preserve' ? '保留' : item.action === 'new' ? '新增' : '历史'}：{item.to_title || item.from_title}</span>)}</div>}
              </div>
            </div>
            <button type="button" className="button primary" disabled={!canReassessDate || reassessmentBusy} onClick={() => void applyDateReassessment()}>确认调整日期并重新冻结</button>
          </>}
        </div>}
        {dateReassessments.length > 0 && <div className="template-switch-history">
          <strong>日期调整台账</strong>
          {dateReassessments.map((item) => <div className="template-switch-history-row" key={item.id}>
            <span>{item.from_visit_date} → {item.to_visit_date} · {item.from_rule_pack_name} → {item.to_rule_pack_name}</span>
            <small>{item.actor_name} · {item.created_at}</small>
          </div>)}
        </div>}
      </section>

      <section className={`section-block readiness-card ${readiness?.ready ? 'is-ready' : 'has-blocks'}`}>
        <div className="section-header compact-header">
          <div>
            <h2>报告完整性预检</h2>
            <p>生成和提交使用同一套服务端门禁。必填任务必须有明确结论；预检同时覆盖 Word 表任务和规则包配置的系统／设备核查。选择“已执行且未发现”时，必须具备日期、范围/样本量和核查说明。</p>
          </div>
          <div className="section-header-actions"><span className={`readiness-status ${readiness?.ready ? 'ready' : 'blocked'}`}>{readiness ? (readiness.ready ? '已通过' : `${readiness.summary.block_count} 项阻断`) : '正在检查'}</span><button type="button" className="button quiet" onClick={() => void loadReadiness()} disabled={!state.visit.id}>刷新预检</button></div>
        </div>
        {!readiness ? <div className="empty-state inline"><span>正在读取当前访视的任务和行动项状态…</span></div> : <>
          <div className="frozen-completeness-policy"><strong>本访视冻结的模板规则</strong><span>任务：{templateTaskCompletenessLabels[frozenCompletenessRules.task_mode]}</span><span>填写位：{templateFieldCompletenessLabels[frozenCompletenessRules.field_mode]}</span></div>
          <div className="readiness-summary"><div><span>访视任务</span><strong>{readiness.summary.task_count}</strong></div><div><span>报告必填项</span><strong>{readiness.summary.terminal_required_tasks}<small>/{readiness.summary.required_tasks}</small></strong></div><div><span>待处理阻断</span><strong>{readiness.summary.block_count}</strong></div></div>
          {readiness.blocks.length > 0 && <div className="readiness-list blocks" role="alert"><strong>需先由 CRA 完成</strong>{readiness.blocks.map((item) => <p key={`${item.code}-${item.task_id}`}>{item.message}</p>)}</div>}
          {readiness.warnings.length > 0 && <div className="readiness-list warnings"><strong>请关注但不阻止报告生成</strong>{readiness.warnings.map((item) => <p key={`${item.code}-${item.escalation_id ?? item.message}`}>{item.message}</p>)}</div>}
          {readiness.ready && readiness.warnings.length === 0 && <div className="readiness-pass"><strong>本次访视已满足当前任务清单的完整性要求。</strong><span>仍请由 CRA 对照来源、语言优化和报告预览进行最终核对。</span></div>}
        </>}
      </section>

      <section className="section-block action-strip">
        <div>
          <h2>生成与提交</h2>
          <p>{isCRA ? (latestRevision ? `最新版本：${latestRevision.version_number} · ${latestRevision.generated_at}` : '尚未生成本次访视的 Word 报告。') : '当前为只读版本视图；报告生成和提交由负责 CRA 完成。'}</p>
        </div>
        <div className="action-strip-buttons">
          <button type="button" className="button secondary" onClick={() => void generate()} disabled={!isCRA || !readiness?.ready || latestRevision?.status === 'submitted' || latestRevision?.status === 'approved'}>生成并下载 Word</button>
          <button type="button" className="button primary" onClick={() => void submit()} disabled={!canSubmit || !readiness?.ready || !submitConfirmed}>{latestRevision?.status === 'returned' ? '修订后重新提交' : latestRevision?.status === 'submitted' ? '已提交，待审核' : 'CRA 确认并提交'}</button>
        </div>
        {canSubmit && <label className="cra-confirmation"><input type="checkbox" checked={submitConfirmed} onChange={(event) => setSubmitConfirmed(event.target.checked)} /><span>本人已核对本次报告内容、字段来源与适用的监查结论，并以 CRA 身份提交审核。</span></label>}
      </section>

      {isCRA && latestRevision?.status === 'submitted' && <section className="section-block cra-withdrawal">
        <div className="section-header compact-header">
          <div><h2>提交后撤回窗口</h2><p>{canWithdraw ? 'PM/LM 尚未领取或开始审核。CRA 可说明原因撤回，系统会保留原提交版本，并创建关联的新工作修订。' : `PM/LM 已于 ${latestRevision.review_started_at || '当前'} 开始审核${latestRevision.review_started_by ? `（${latestRevision.review_started_by}）` : ''}；此版本只能由 PM/LM 退回。`}</p></div>
          <span className="section-code">CRA RESPONSIBILITY</span>
        </div>
        {canWithdraw && <div className="cra-withdrawal-form"><label>撤回原因<input value={withdrawReason} onChange={(event) => setWithdrawReason(event.target.value)} disabled={withdrawing} placeholder="例如：发现需补充核对的受控文件版本" /></label><div><span>撤回不会删除已提交的 Word、CRA 确认或审计记录。</span><button type="button" className="button danger-outline" disabled={withdrawing} onClick={() => void withdraw()}>{withdrawing ? '正在撤回…' : '撤回并新建工作修订'}</button></div></div>}
      </section>}

      {isQaClinicalOps && latestRevision?.status === 'approved' && <section className="section-block approved-void">
        <div className="section-header compact-header">
          <div><h2>已批准报告作废</h2><p>仅用于需要撤销内部工作流结论的情形。原批准 Word 与审核记录继续保留；系统会创建关联工作修订，由 CRA 重新核对、生成并提交。</p></div>
          <span className="section-code">QA / CLINICAL OPS</span>
        </div>
        <div className="approved-void-form"><label>作废原因<input value={voidReason} onChange={(event) => setVoidReason(event.target.value)} disabled={voiding} placeholder="例如：经 QA 复核发现批准后适用规则包需重新确认" /></label><div><span>作废不会删除既有 Word 或系统外归档记录，也不会由 QA/临床运营代替 CRA 完成后续提交。</span><button type="button" className="button danger-outline" disabled={voiding} onClick={() => void voidApprovedReport()}>{voiding ? '正在作废…' : '作废并创建工作修订'}</button></div></div>
      </section>}

      <section className="section-block language-control">
        <div className="section-header">
          <div><h2>受控语言优化</h2><p>仅对 CRA 已确认文字生成候选稿，提供原文、拟用表述和规则包依据；不会补充新的临床事实。</p></div>
          <div className="section-header-actions"><span className="section-code">CONTROLLED LANGUAGE</span><button type="button" className="button quiet" onClick={() => void generateLanguage()} disabled={!isCRA || state.confirmed_items.length === 0}>生成候选稿</button></div>
        </div>
        {languageSuggestions.length === 0 ? <div className="empty-state"><strong>尚未生成语言候选稿</strong><span>先在监查工作台确认事实记录，再由 CRA 在此生成专业化展示建议。</span></div> : (
          <div className="language-list">
            {languageSuggestions.map((item) => {
              const canRevokeLanguage = isCRA && ['accepted', 'edited'].includes(item.status)
              const isRevokingLanguage = revokingLanguageId === item.id
              const isRevoked = item.status === 'revoked'
              return <article className={`language-row status-${item.status}`} key={item.id}>
                <div className="language-meta"><span>表 {item.target_table}</span><small>{languageStatusLabels[item.status] ?? item.status}</small></div>
                <div className="language-copy"><p><strong>原始确认文字</strong>{item.original_text}</p><p><strong>建议展示文字</strong>{item.proposed_text}</p><small>{item.change_summary}</small></div>
                {item.status === 'pending' && <div className="language-actions">
                  <textarea aria-label={`修改表 ${item.target_table} 的展示文字`} value={editTexts[item.id] ?? item.proposed_text} onChange={(event) => setEditTexts({ ...editTexts, [item.id]: event.target.value })} disabled={!isCRA} />
                  <div><button type="button" className="button small" onClick={() => void decideLanguage(item, 'accepted')} disabled={!isCRA}>采用建议</button><button type="button" className="button small quiet" onClick={() => void decideLanguage(item, 'edited')} disabled={!isCRA}>按修改稿采用</button><button type="button" className="button-link danger" onClick={() => void decideLanguage(item, 'rejected')} disabled={!isCRA}>不采用</button></div>
                </div>}
                {item.status !== 'pending' && <div className="language-decision">
                  <div className={`language-final${isRevoked ? ' is-revoked' : ''}`}><span>报告展示</span><strong>{isRevoked ? item.original_text : item.final_text || item.original_text}</strong>{isRevoked && <><small>已撤销采用：{item.revoked_by || '—'} · {item.revoked_at || '—'}</small><small>撤销前采用文字：{item.final_text || '—'}</small><small>撤销原因：{item.revoke_reason || '—'}</small></>}</div>
                  {canRevokeLanguage && !isRevokingLanguage && <button type="button" className="button-link danger language-revoke-trigger" onClick={() => setRevokingLanguageId(item.id)}>撤销采用</button>}
                  {canRevokeLanguage && isRevokingLanguage && <div className="language-revoke"><label>撤销原因<input aria-label={`撤销表 ${item.target_table} 语言采用的原因`} value={languageRevokeReasons[item.id] ?? ''} onChange={(event) => setLanguageRevokeReasons({ ...languageRevokeReasons, [item.id]: event.target.value })} disabled={languageRevoking} placeholder="例如：需保留中心原始表述" /></label><div><button type="button" className="button small quiet" onClick={() => setRevokingLanguageId(null)} disabled={languageRevoking}>取消</button><button type="button" className="button small danger-outline" onClick={() => void revokeLanguage(item)} disabled={languageRevoking}>{languageRevoking ? '正在撤销…' : '确认撤销'}</button></div></div>}
                </div>}
              </article>
            })}
          </div>
        )}
      </section>

      <section className="section-block review-disposition">
        <div className="section-header compact-header"><div><h2>待处置审核与专项意见</h2><p>PM/LM 审核建议与医学监察／数据管理专项意见均可按段落、字段或表格定位；是否采用由 CRA 明确处置，系统不会自动更改事实。</p></div><span className="section-code">CRA DISPOSITION</span></div>
        {openComments.length === 0 ? <div className="empty-state"><strong>当前没有待处置意见</strong><span>PM/LM 审核建议和医学监察／数据管理专项意见会显示在这里。</span></div> : <div className="comment-disposition-list">{openComments.map((comment) => <article key={comment.id} className={`comment-disposition-row comment-type-${comment.comment_type ?? 'pm_lm_review'}`}><div><span className={`review-comment-kind kind-${comment.comment_type ?? 'pm_lm_review'}`}>{comment.comment_type === 'pm_lm_review' || !comment.comment_type ? 'PM / LM 审核' : '医学监察 / 数据管理'}</span><span className="review-target">{reviewTargetLabel(comment, state)}</span><strong>{reviewCommentLabel(comment)}：{comment.message}</strong><small>{comment.reviewer_name} · {comment.created_at}</small></div>{isCRA && <div className="comment-disposition-actions"><textarea aria-label={`意见处置说明 ${comment.id}`} placeholder="可填写 CRA 处置说明" value={commentNotes[comment.id] ?? ''} onChange={(event) => setCommentNotes({ ...commentNotes, [comment.id]: event.target.value })} /><div><button type="button" className="button small" onClick={() => void resolveComment(comment, 'accepted')}>接受意见</button><button type="button" className="button-link danger" onClick={() => void resolveComment(comment, 'declined')}>不采用</button></div></div>}</article>)}</div>}
      </section>

      <section className="section-block cra-paragraph-preview">
        <div className="section-header compact-header"><div><h2>报告预览段落与审核上下文</h2><p>与审核中心使用同一组段落锚点。审核建议仅作为待处置事项显示，CRA 接受或不采用建议均不会由系统自动改写报告事实。</p></div><span className="section-code">PARAGRAPH CONTEXT</span></div>
        {previewParagraphs.length === 0 ? <div className="empty-state inline"><span>尚无可进入报告预览的确认文字。</span></div> : <div className="cra-paragraph-list">{previewParagraphs.map((paragraph) => {
          const relatedComments = openCommentsByTarget.get(paragraph.targetKey) ?? []
          return <article key={paragraph.targetKey} className={`cra-paragraph-row ${relatedComments.length ? 'has-open-comments' : ''}`}><div><span>段落 {paragraph.sequence} · 表 {paragraph.targetTable} · {paragraph.taskTitle}</span><p>{displayEvidenceText(paragraph.text)}</p></div>{relatedComments.length > 0 && <aside><strong>{relatedComments.length} 条待处置意见</strong>{relatedComments.map((comment) => <span key={comment.id}>{reviewCommentLabel(comment)} · {comment.reviewer_name}：{comment.message}</span>)}</aside>}</article>
        })}</div>}
      </section>

      <section className="section-block evidence-section">
        <div className="section-header"><div><h2>字段证据链</h2><p>每一个展示字段均可回溯至确认文字、来源工作记录、AI 整理执行、CRA 决策、规则包版本与语言决定。</p></div><div className="section-header-actions"><span className="section-code">TRACE</span><button type="button" className="button quiet" onClick={() => void loadEvidence()}>刷新证据链</button></div></div>
        {!evidence || evidence.fields.length === 0 ? <div className="empty-state"><strong>尚无可展示的确认字段</strong><span>CRA 确认记录后，这里会建立字段到来源的可追溯关系。</span></div> : <div className="data-table-wrap"><table className="data-table evidence-table"><thead><tr><th>报告位置</th><th>原始确认文字</th><th>报告展示文字</th><th>来源与证据</th><th>CRA 决策</th><th>AI 整理执行</th><th>语言决定</th><th>规则包</th></tr></thead><tbody>{evidence.fields.map((field) => <tr key={field.confirmed_field_id}><td className="tabular">表 {field.target_table}</td><td>{displayEvidenceText(field.confirmed_text)}</td><td>{field.report_included === false ? <span className="not-in-report">中心解释独立留存，不进入报告</span> : displayEvidenceText(field.report_text)}</td><td><strong>{field.source_record.record_kind === 'center_explanation' ? '中心解释' : field.source_record.id ? '工作记录' : '—'}</strong><small>{field.source_record.text ? displayEvidenceText(field.source_record.text) : '未关联来源记录'}</small><small>证据范围：{field.source_suggestion.evidence_start}–{field.source_suggestion.evidence_end} · {field.source_suggestion.source_type || 'work_record'}</small><small>编号：{field.source_suggestion.subject_display_code || '—'} · {subjectValidationLabels[field.source_suggestion.subject_validation_status] ?? (field.source_suggestion.subject_validation_status || '未标注')}</small></td><td>{decisionLabels[field.decision] ?? field.decision}<small>{field.decision_reason || '未填写修改原因'}</small></td><td><strong>{field.ai_execution.provider || '—'}</strong><small>{field.ai_execution.model_version || '未留存模型版本'} · {field.ai_execution.validation_status || '状态未知'}</small><small title={field.ai_execution.id}>执行 {shortTraceId(field.ai_execution.id)} · {assertionTypeLabels[field.source_suggestion.assertion_type] ?? (field.source_suggestion.assertion_type || '未标注')}</small></td><td>{field.language.status}<small>{field.language.change_summary}</small></td><td>{evidence.rule_pack.name} · {evidence.rule_pack.version}</td></tr>)}</tbody></table></div>}
        {evidence && (evidence.clarifications?.length ?? 0) > 0 && <div className="clarification-evidence">
          <div className="clarification-evidence-heading"><strong>缺失与冲突处理留痕</strong><span>保留问题、候选、CRA 决定和无效补录记录；未解决问题仍会在完整性预检中阻断提交。</span></div>
          <div className="data-table-wrap"><table className="data-table"><thead><tr><th>类型</th><th>问题</th><th>状态</th><th>CRA 处理 / 最近响应</th></tr></thead><tbody>{evidence.clarifications?.map((item) => {
            const latest = item.responses?.[0]
            const finalText = String(item.resolution?.final_text ?? '')
            return <tr key={item.id}><td>{item.issue_type === 'conflict' ? '版本冲突' : '信息缺失'}</td><td><strong>{item.title}</strong><small>{item.reason}</small></td><td>{item.status === 'resolved' ? '已处理' : item.status === 'manual_required' ? '人工待办' : '待 CRA 处理'}</td><td>{finalText || latest?.answer_text || '—'}<small>{latest?.response_status === 'invalid' ? `未采纳：${latest.invalid_reason}` : item.resolved_by ? `处理人：${item.resolved_by} · ${item.resolved_at}` : ''}</small></td></tr>
          })}</tbody></table></div>
        </div>}
      </section>

      <section className="section-block revision-ledger">
        <div className="section-header"><div><h2>报告版本与归档交接</h2><p>Word 保持原始 15 张表结构。可导出审计 CSV，并将选定 Word、审计轨迹和签署提示交接至客户既有 SOP/eTMF 流程。</p></div><div className="section-header-actions"><button type="button" className="button quiet" onClick={() => state.visit.id && void download(() => api.downloadAuditExport(state.visit.id!), '审计 CSV 下载失败')}>下载审计 CSV</button><span className="section-code">ARCHIVE</span></div></div>
        {revisions.length === 0 ? <div className="empty-state"><strong>尚无报告版本</strong><span>生成 Word 后，可为每个修订版下载系统外交接 ZIP。</span></div> : <div className="data-table-wrap"><table className="data-table"><thead><tr><th>版本</th><th>生成时间</th><th>状态</th><th>提交人</th><th>操作</th></tr></thead><tbody>{revisions.map((revision) => <tr key={revision.id}><td className="tabular">{revision.version_number}<small>{revision.parent_revision_id ? `关联上版 ${shortTraceId(revision.parent_revision_id)}` : '初始工作修订'}</small></td><td>{revision.generated_at || '待生成'}</td><td><span className={`report-status status-${revision.status}`}>{reportStatusLabel[revision.status]}</span>{revision.status === 'voided' && <small className="revision-void-detail">作废：{revision.voided_by || 'QA/临床运营'} · {revision.voided_at || '时间未记录'}<br />原因：{revision.void_reason || '未填写'}</small>}</td><td>{revision.submitted_by || '—'}</td><td className="revision-actions">{revision.file_path ? <><button type="button" className="button small" onClick={() => void download(() => api.downloadRevision(revision.id), 'Word 下载失败')}>Word</button><button type="button" className="button small quiet" onClick={() => void download(() => api.downloadHandoverPackage(revision.id), '交接包下载失败')}>签署交接 ZIP</button></> : <span className="muted-cell">待 CRA 生成 Word</span>}</td></tr>)}</tbody></table></div>}
      </section>

      <section className="section-block">
        <div className="section-header compact-header"><div><h2>{tableCount} 张表覆盖清单</h2><p>导出 Word 保留固定表格结构，不会因为某一项暂未填写而丢失表格。</p></div><span className="section-code">OUTPUT CONTROL</span></div>
        <div className="data-table-wrap"><table className="data-table report-table"><thead><tr><th>表号</th><th>报告区域</th><th>工作底稿状态</th><th>导出行为</th></tr></thead><tbody>{state.table_tasks.map((task) => <tr key={task.id}><td className="tabular">{task.index}</td><td>{task.title}</td><td>{task.status}</td><td className="muted-cell">{task.status === '待补录' ? '保留表格，并提示待 CRA 确认' : '写入已确认或已映射内容'}</td></tr>)}</tbody></table></div>
      </section>
    </div>
  )
}
