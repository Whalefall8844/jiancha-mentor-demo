import { useEffect, useState } from 'react'
import { api } from '../api'
import { BreakGlassPanel } from './BreakGlassPanel'
import { RulePackCitationSearch } from './RulePackCitationSearch'
import { controlledStyleReferenceLabel, readControlledStyleReferences, styleReferenceContentWith, styleReferenceFromReport, type ControlledStyleReference } from '../styleReferences'
import { controlledLanguageContentWith, readConfiguredTerminology, readPreferredPhraseReplacements, type ControlledLanguageRuleEntry } from '../controlledLanguageRules'
import type { AdapterConfig, ConfigurationApprovalAction, DemoState, HistoryReportItem, RulePack } from '../types'

type EscalationSeverity = 'high' | 'urgent'
type EscalationTargetRole = 'PM_LM' | 'PROJECT_ADMIN'

interface EscalationSlaEntryDraft {
  enabled: boolean
  acknowledge_within_hours: string
  target_role: EscalationTargetRole
  overdue_target_role: EscalationTargetRole
}

type EscalationSlaEditorDraft = Record<EscalationSeverity, EscalationSlaEntryDraft>

interface GovernancePageProps {
  state: DemoState
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

const blankDraft = () => ({
  name: '',
  version: 'V1.0',
  effective_from: '',
  effective_to: '',
  content: '{\n  "language_style": "cn_gcp",\n  "terminology": {\n    "ICF": "知情同意书（ICF）",\n    "AE": "不良事件（AE）",\n    "SAE": "严重不良事件（SAE）",\n    "CRF": "病例报告表（CRF）"\n  }\n}',
})

const blankEscalationSlaEditor = (): EscalationSlaEditorDraft => ({
  high: { enabled: false, acknowledge_within_hours: '', target_role: 'PM_LM', overdue_target_role: 'PM_LM' },
  urgent: { enabled: false, acknowledge_within_hours: '', target_role: 'PM_LM', overdue_target_role: 'PROJECT_ADMIN' },
})

const isObjectRecord = (value: unknown): value is Record<string, unknown> => Boolean(value) && !Array.isArray(value) && typeof value === 'object'

const parseRuleContent = (content: string) => {
  const parsed = JSON.parse(content)
  if (!isObjectRecord(parsed)) throw new Error('规则包内容应为 JSON 对象')
  return parsed
}

const escalationTargetRole = (value: unknown, fallback: EscalationTargetRole): EscalationTargetRole => value === 'PROJECT_ADMIN' || value === 'PM_LM' ? value : fallback

const escalationSlaEditorFromContent = (content: Record<string, unknown>): EscalationSlaEditorDraft => {
  const rawSla = isObjectRecord(content.escalation_sla) ? content.escalation_sla : {}
  const readEntry = (severity: EscalationSeverity, defaults: EscalationSlaEntryDraft): EscalationSlaEntryDraft => {
    const rawEntry = rawSla[severity]
    if (!isObjectRecord(rawEntry)) return defaults
    return {
      enabled: true,
      acknowledge_within_hours: typeof rawEntry.acknowledge_within_hours === 'number' ? String(rawEntry.acknowledge_within_hours) : '',
      target_role: escalationTargetRole(rawEntry.target_role, defaults.target_role),
      overdue_target_role: escalationTargetRole(rawEntry.overdue_target_role, defaults.overdue_target_role),
    }
  }
  const defaults = blankEscalationSlaEditor()
  return {
    high: readEntry('high', defaults.high),
    urgent: readEntry('urgent', defaults.urgent),
  }
}

const contentWithEscalationSlaEntry = (
  content: Record<string, unknown>,
  severity: EscalationSeverity,
  entry: EscalationSlaEntryDraft,
) => {
  const nextContent = { ...content }
  const nextSla = isObjectRecord(content.escalation_sla) ? { ...content.escalation_sla } : {}
  if (entry.enabled) {
    nextSla[severity] = {
      acknowledge_within_hours: Number(entry.acknowledge_within_hours),
      target_role: entry.target_role,
      overdue_target_role: entry.overdue_target_role,
    }
  } else {
    delete nextSla[severity]
  }
  if (Object.keys(nextSla).length) nextContent.escalation_sla = nextSla
  else delete nextContent.escalation_sla
  return nextContent
}

const configurationStatusLabel: Record<string, string> = {
  draft: '草稿配置中',
  pending_approval: '待 QA/临床运营审批',
  active: '已启用',
  rejected: '已退回',
  inactive: '已停用',
}

const ruleEligibilityLabel: Record<string, string> = {
  eligible: '当前适用',
  not_yet_effective: '尚未生效',
  expired: '已失效',
  invalid_rule_dates: '日期异常',
  not_active: '未启用',
}

const localToday = () => {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

export function GovernancePage({ state, onNotice }: GovernancePageProps) {
  const projectId = state.visit.project_id ?? ''
  const isAdmin = state.current_role === 'PROJECT_ADMIN'
  const isQaReviewer = state.current_role === 'QA_CLINICAL_OPS'
  const [rules, setRules] = useState<RulePack[]>([])
  const [adapter, setAdapter] = useState<AdapterConfig | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [draft, setDraft] = useState(blankDraft)
  const [escalationSlaEditor, setEscalationSlaEditor] = useState<EscalationSlaEditorDraft>(blankEscalationSlaEditor)
  const [styleReferences, setStyleReferences] = useState<ControlledStyleReference[]>([])
  const [terminologyEntries, setTerminologyEntries] = useState<ControlledLanguageRuleEntry[]>([])
  const [preferredPhraseEntries, setPreferredPhraseEntries] = useState<ControlledLanguageRuleEntry[]>([])
  const [historyReports, setHistoryReports] = useState<HistoryReportItem[]>([])
  const [reviewNote, setReviewNote] = useState('')

  const load = async () => {
    if (!projectId) return
    try {
      const today = localToday()
      const [ruleResult, adapterResult, historyResult] = await Promise.all([
        api.listRulePackEligibility(projectId, today, true),
        api.getAdapterConfig(),
        api.getProjectHistoryInsights(projectId, '', '9999-12-31'),
      ])
      setRules(ruleResult.items)
      setAdapter(adapterResult)
      setHistoryReports(historyResult.reports)
      if (!selectedId && ruleResult.items[0]) selectRule(ruleResult.items[0])
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '规则包数据加载失败', 'error')
    }
  }

  useEffect(() => { void load() }, [projectId])

  const selectRule = (rule: RulePack) => {
    const content = rule.content ?? {}
    setSelectedId(rule.id)
    setDraft({
      name: rule.name,
      version: rule.version,
      effective_from: rule.effective_from,
      effective_to: rule.effective_to,
      content: JSON.stringify(content, null, 2),
    })
    setEscalationSlaEditor(escalationSlaEditorFromContent(content))
    setStyleReferences(readControlledStyleReferences(content))
    setTerminologyEntries(readConfiguredTerminology(content))
    setPreferredPhraseEntries(readPreferredPhraseReplacements(content))
  }

  const selectedRule = rules.find((rule) => rule.id === selectedId)
  const isRuleEditable = isAdmin && (!selectedRule || ['draft', 'rejected'].includes(selectedRule.status))
  const frozenStyleReferences = readControlledStyleReferences(state.rule_pack?.content)
  const frozenTerminologyEntries = readConfiguredTerminology(state.rule_pack?.content)
  const frozenPreferredPhraseEntries = readPreferredPhraseReplacements(state.rule_pack?.content)
  const styleReferenceCandidates = historyReports.filter((report) => (
    report.revision_type === 'formal'
    && report.revision_status === 'approved'
    && report.visit_id !== state.visit.id
    && Boolean(report.file_name)
  ))

  const parseContent = () => {
    return parseRuleContent(draft.content)
  }

  const updateEscalationSla = (severity: EscalationSeverity, patch: Partial<EscalationSlaEntryDraft>) => {
    try {
      const currentContent = parseContent()
      const currentEditor = escalationSlaEditorFromContent(currentContent)
      const nextEntry = { ...currentEditor[severity], ...patch }
      const nextContent = contentWithEscalationSlaEntry(currentContent, severity, nextEntry)
      setEscalationSlaEditor({ ...currentEditor, [severity]: nextEntry })
      setDraft({ ...draft, content: JSON.stringify(nextContent, null, 2) })
    } catch (error) {
      onNotice(error instanceof Error ? `请先修正规则 JSON：${error.message}` : '请先修正规则 JSON 后再编辑 SLA。', 'error')
    }
  }

  const updateStyleReferences = (nextReferences: ControlledStyleReference[]) => {
    try {
      const nextContent = styleReferenceContentWith(parseContent(), nextReferences)
      setStyleReferences(nextReferences)
      setDraft({ ...draft, content: JSON.stringify(nextContent, null, 2) })
    } catch (error) {
      onNotice(error instanceof Error ? `请先修正规则 JSON：${error.message}` : '请先修正规则 JSON 后再维护写作样例。', 'error')
    }
  }

  const updateControlledLanguageRules = (
    nextTerminologyEntries: ControlledLanguageRuleEntry[],
    nextPreferredPhraseEntries: ControlledLanguageRuleEntry[],
  ) => {
    try {
      const nextContent = controlledLanguageContentWith(parseContent(), nextTerminologyEntries, nextPreferredPhraseEntries)
      setTerminologyEntries(nextTerminologyEntries)
      setPreferredPhraseEntries(nextPreferredPhraseEntries)
      setDraft({ ...draft, content: JSON.stringify(nextContent, null, 2) })
    } catch (error) {
      onNotice(error instanceof Error ? `请先修正规则 JSON：${error.message}` : '请先修正规则 JSON 后再维护语言规则。', 'error')
    }
  }

  const updateTerminologyEntry = (index: number, patch: Partial<ControlledLanguageRuleEntry>) => {
    updateControlledLanguageRules(terminologyEntries.map((entry, entryIndex) => entryIndex === index ? { ...entry, ...patch } : entry), preferredPhraseEntries)
  }

  const updatePreferredPhraseEntry = (index: number, patch: Partial<ControlledLanguageRuleEntry>) => {
    updateControlledLanguageRules(terminologyEntries, preferredPhraseEntries.map((entry, entryIndex) => entryIndex === index ? { ...entry, ...patch } : entry))
  }

  const addStyleReference = (report: HistoryReportItem) => {
    if (styleReferences.some((reference) => reference.revision_id === report.id)) return
    updateStyleReferences([...styleReferences, styleReferenceFromReport(report)])
  }

  const updateStyleReferenceNote = (revisionId: string, note: string) => {
    updateStyleReferences(styleReferences.map((reference) => reference.revision_id === revisionId ? { ...reference, note } : reference))
  }

  const removeStyleReference = (revisionId: string) => {
    updateStyleReferences(styleReferences.filter((reference) => reference.revision_id !== revisionId))
  }

  const saveRule = async (mode: 'create' | 'update') => {
    if (!isRuleEditable) return
    try {
      const payload = { ...draft, content: parseContent() }
      const saved = mode === 'create'
        ? await api.createRulePack(projectId, payload)
        : await api.updateRulePack(selectedId, payload)
      await load()
      selectRule(saved)
      onNotice(mode === 'create' ? '规则包已创建；后续新建访视会冻结其版本。' : '规则包配置已保存；既有访视仍使用自身冻结快照。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '规则包保存失败', 'error')
    }
  }

  const runRuleApprovalAction = async (action: ConfigurationApprovalAction) => {
    if (!selectedId) return
    try {
      const saved = await api.rulePackApprovalAction(selectedId, {
        action,
        actor_name: isQaReviewer ? '演示 QA/临床运营审批人' : '项目管理员',
        note: reviewNote,
      })
      await load()
      selectRule(saved)
      setReviewNote('')
      onNotice(action === 'approve' ? '规则包已获批准并启用，可供新建访视选择。' : action === 'reject' ? '规则包已退回配置人处理。' : action === 'submit' ? '规则包已提交 QA/临床运营审批。' : action === 'withdraw' ? '规则包审批已撤回，已回到草稿。' : '规则包已停用，后续新访视不可再选用。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '规则包审批操作失败', 'error')
    }
  }

  const saveAdapter = async () => {
    if (!adapter || !isAdmin) return
    try {
      const saved = await api.updateAdapterConfig(adapter)
      setAdapter(saved)
      onNotice('模型适配参数已保存；本地演示不会发起外部模型请求。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '适配器配置保存失败', 'error')
    }
  }

  const downloadStyleReference = async (reference: ControlledStyleReference) => {
    try {
      await api.downloadRevision(reference.revision_id)
      onNotice(`已开始下载来源报告：${controlledStyleReferenceLabel(reference)}。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '来源 Word 下载失败', 'error')
    }
  }

  const frozenRule = state.rule_pack

  return (
    <div className="governance-stack">
      <section className="governance-brief">
        <div>
          <p className="eyebrow">RULE PACK · TRACEABILITY · ARCHIVE</p>
          <h2>规则、模型与归档控制</h2>
          <p>项目配置可持续维护；每次新建访视会把适用规则、术语和版本冻结到该访视快照中。</p>
        </div>
        <dl className="governance-stats">
          <div><dt>项目规则包</dt><dd>{rules.length}</dd></div>
          <div><dt>本访视冻结版</dt><dd>{frozenRule?.version ?? '—'}</dd></div>
          <div><dt>外部调用</dt><dd>关闭</dd></div>
        </dl>
      </section>

      {!isAdmin && !isQaReviewer && <div className="role-readonly-card"><strong>当前为只读配置视图</strong><span>请切换为项目管理员维护草稿，或切换为 QA / 临床运营审批人处理待审批规则。</span></div>}

      <section className="governance-grid">
        <div className="section-block rule-register">
          <div className="section-header compact-header"><div><h2>项目规则包</h2><p>规则包可管理、可停用；不会反向改写既有访视的冻结版本。</p></div><span className="section-code">RULE PACKS</span></div>
          <div className="rule-list">
            {rules.map((rule) => <button key={rule.id} type="button" className={`rule-row ${selectedId === rule.id ? 'is-selected' : ''}`} onClick={() => selectRule(rule)}>
              <span className={`rule-status status-${rule.status}`}>{configurationStatusLabel[rule.status] ?? rule.status}</span><strong>{rule.name}</strong><small>{rule.version} · {rule.effective_from || '未设置生效日'} 至 {rule.effective_to || '持续有效'}</small>{rule.eligibility && <span className={`rule-eligibility status-${rule.eligibility.status} ${rule.eligibility.expires_soon ? 'is-warning' : ''}`}>{ruleEligibilityLabel[rule.eligibility.status] ?? rule.eligibility.status}{rule.eligibility.expires_soon ? ` · ${rule.eligibility.days_until_expiry} 天后失效` : ''}</span>}
            </button>)}
            {rules.length === 0 && <div className="empty-state"><strong>尚无规则包</strong><span>先创建一个规则包，再创建新的监查访视。</span></div>}
          </div>
        </div>

        <div className="section-block rule-editor">
          <div className="section-header compact-header"><div><h2>{selectedId ? '编辑规则包' : '新建规则包'}</h2><p>术语配置只用于受控语言候选稿；它不会自动改变 CRA 已确认事实。</p></div></div>
          <div className="governance-form">
            <label>规则包名称<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} disabled={!isRuleEditable} placeholder="例如：临床监查规则包" /></label>
            <label>版本号<input value={draft.version} onChange={(event) => setDraft({ ...draft, version: event.target.value })} disabled={!isRuleEditable} /></label>
            <label>生效日期<input value={draft.effective_from} onChange={(event) => setDraft({ ...draft, effective_from: event.target.value })} disabled={!isRuleEditable} placeholder="YYYY-MM-DD" /></label>
            <label>失效日期<input value={draft.effective_to} onChange={(event) => setDraft({ ...draft, effective_to: event.target.value })} disabled={!isRuleEditable} placeholder="YYYY-MM-DD" /></label>
            <label className="governance-wide">规则内容（JSON）<textarea value={draft.content} onChange={(event) => {
              const content = event.target.value
              setDraft({ ...draft, content })
              try {
                const parsed = parseRuleContent(content)
                setEscalationSlaEditor(escalationSlaEditorFromContent(parsed))
                setStyleReferences(readControlledStyleReferences(parsed))
                setTerminologyEntries(readConfiguredTerminology(parsed))
                setPreferredPhraseEntries(readPreferredPhraseReplacements(parsed))
              } catch { /* 保留上一份表单草稿，等待管理员修正 JSON。 */ }
            }} disabled={!isRuleEditable} /></label>
            <div className="controlled-language-rule-editor governance-wide">
              <div className="controlled-language-rule-heading"><div><strong>受控语言规则</strong><span>术语对照与固定表达会写入同一份规则 JSON；仅影响 CRA 主动生成的候选稿，采用前仍可编辑或拒绝。</span></div><span>{terminologyEntries.length + preferredPhraseEntries.length} 条</span></div>
              <p className="controlled-language-rule-boundary">固定表达用于同义、语气和专业化展示的明确替换，不用于新增、推断或删减任何监查事实、医学判断或中心解释。</p>
              <div className="controlled-language-rule-grid">
                <section>
                  <header><strong>术语对照</strong><span>例如缩写展开；写入 <code>terminology</code>。</span></header>
                  <div className="controlled-language-rule-list">
                    {terminologyEntries.map((entry, index) => <div className="controlled-language-rule-row" key={`term-${index}`}><input aria-label={`术语原称 ${index + 1}`} value={entry.source} disabled={!isRuleEditable} onChange={(event) => updateTerminologyEntry(index, { source: event.target.value })} placeholder="例如：ICF" /><input aria-label={`术语规范称 ${index + 1}`} value={entry.target} disabled={!isRuleEditable} onChange={(event) => updateTerminologyEntry(index, { target: event.target.value })} placeholder="例如：知情同意书（ICF）" /><button type="button" className="button-link danger" disabled={!isRuleEditable} onClick={() => updateControlledLanguageRules(terminologyEntries.filter((_, entryIndex) => entryIndex !== index), preferredPhraseEntries)}>移除</button></div>)}
                  </div>
                  <button type="button" className="button quiet small" disabled={!isRuleEditable} onClick={() => updateControlledLanguageRules([...terminologyEntries, { source: '', target: '' }], preferredPhraseEntries)}>新增术语</button>
                </section>
                <section>
                  <header><strong>固定表达</strong><span>按明确原文替换；写入 <code>language_rules.preferred_phrases</code>。</span></header>
                  <div className="controlled-language-rule-list">
                    {preferredPhraseEntries.map((entry, index) => <div className="controlled-language-rule-row" key={`phrase-${index}`}><textarea aria-label={`固定表达原文 ${index + 1}`} value={entry.source} disabled={!isRuleEditable} onChange={(event) => updatePreferredPhraseEntry(index, { source: event.target.value })} placeholder="例如：未发现问题" /><textarea aria-label={`固定表达规范稿 ${index + 1}`} value={entry.target} disabled={!isRuleEditable} onChange={(event) => updatePreferredPhraseEntry(index, { target: event.target.value })} placeholder="例如：经本次核查，未发现需记录的异常情况" /><button type="button" className="button-link danger" disabled={!isRuleEditable} onClick={() => updateControlledLanguageRules(terminologyEntries, preferredPhraseEntries.filter((_, entryIndex) => entryIndex !== index))}>移除</button></div>)}
                  </div>
                  <button type="button" className="button quiet small" disabled={!isRuleEditable} onClick={() => updateControlledLanguageRules(terminologyEntries, [...preferredPhraseEntries, { source: '', target: '' }])}>新增固定表达</button>
                </section>
              </div>
            </div>
            <div className="system-check-config-help governance-wide"><strong>系统／设备核查（可选）</strong><span>在 JSON 中增加 <code>system_checks</code> 数组即可；新访视会冻结为独立工作底稿任务，不会新增或改写 Word 的 15 张表。</span><code>{'"system_checks": [{ "title": "IWRS / IXRS 系统核查", "required": true, "description": "核对可用性和授权账户；不执行揭盲。" }]'}</code></div>
            <div className="system-check-config-help governance-wide"><strong>模板／SOP 契约（可选）</strong><span>可在规则包 JSON 中声明 <code>template_profile</code>（或兼容现有 <code>task_template</code>）和 <code>sop_version</code>。新访视会冻结实际模板与项目 SOP 版本；不一致时进入 CRA 的人工升级台账，不会由报告文本自动解除。</span><code>{'"template_profile": "imv_15_table", "sop_version": "常规监查访视 SOP V1.0"'}</code></div>
            <div className="system-check-config-help governance-wide"><strong>紧急升级 SLA（可选）</strong><span>按项目为高优先级／紧急升级配置接收时限、初始接收角色和逾期转送角色。配置只会冻结到新建访视；系统内提醒不替代 CRA 按方案、法规和 SOP 完成既有渠道上报。</span><code>{'"escalation_sla": { "urgent": { "acknowledge_within_hours": 4, "target_role": "PM_LM", "overdue_target_role": "PROJECT_ADMIN" }, "high": { "acknowledge_within_hours": 24, "target_role": "PM_LM", "overdue_target_role": "PM_LM" } }'}</code></div>
            <div className="escalation-sla-editor governance-wide">
              <div className="escalation-sla-editor-heading"><strong>项目紧急升级 SLA</strong><span>可视化配置会同步写入上述 JSON；仅草稿或退回状态可编辑。</span></div>
              {(['high', 'urgent'] as EscalationSeverity[]).map((severity) => {
                const entry = escalationSlaEditor[severity]
                return <fieldset className="escalation-sla-config-row" key={severity} disabled={!isRuleEditable}>
                  <legend>{severity === 'urgent' ? '紧急事项' : '高优先级事项'}</legend>
                  <label className="escalation-sla-enable"><input type="checkbox" checked={entry.enabled} onChange={(event) => updateEscalationSla(severity, { enabled: event.target.checked })} />启用本等级 SLA</label>
                  <label>接收时限（小时）<input inputMode="numeric" value={entry.acknowledge_within_hours} disabled={!entry.enabled} onChange={(event) => updateEscalationSla(severity, { acknowledge_within_hours: event.target.value })} placeholder="例如：4" /></label>
                  <label>初始接收角色<select value={entry.target_role} disabled={!entry.enabled} onChange={(event) => updateEscalationSla(severity, { target_role: event.target.value as EscalationTargetRole })}><option value="PM_LM">PM / LM</option><option value="PROJECT_ADMIN">项目管理员</option></select></label>
                  <label>逾期转送角色<select value={entry.overdue_target_role} disabled={!entry.enabled} onChange={(event) => updateEscalationSla(severity, { overdue_target_role: event.target.value as EscalationTargetRole })}><option value="PM_LM">PM / LM</option><option value="PROJECT_ADMIN">项目管理员</option></select></label>
                </fieldset>
              })}
            </div>
            <div className="style-reference-editor governance-wide">
              <div className="style-reference-editor-heading"><div><strong>经批准的历史写作样例</strong><span>仅可选择同项目、正式、已批准报告；写入同一份规则 JSON，随审批和新访视一并冻结。</span></div><span>{styleReferences.length} 条已选</span></div>
              <p className="style-reference-boundary">仅供人工查阅写作风格。不会自动复制历史事实、受试者编号、发现、行动项或报告段落到当前访视。</p>
              {styleReferences.length > 0 && <div className="style-reference-selected-list">
                {styleReferences.map((reference) => <article key={reference.revision_id} className="style-reference-selected-row">
                  <div><strong>{controlledStyleReferenceLabel(reference)}</strong><small>{reference.site_name || '来源中心名称未记录'}{reference.visit_type ? ` · ${reference.visit_type}` : ''} · 仅写作风格参考</small></div>
                  <label>用途说明<textarea value={reference.note} disabled={!isRuleEditable} onChange={(event) => updateStyleReferenceNote(reference.revision_id, event.target.value)} placeholder="例如：参考本项目常规监查总结的表述结构" /></label>
                  <button type="button" className="button quiet small" disabled={!isRuleEditable} onClick={() => removeStyleReference(reference.revision_id)}>移除</button>
                </article>)}
              </div>}
              <div className="style-reference-candidate-list">
                {styleReferenceCandidates.length === 0 ? <span>当前项目尚无可选的已批准历史正式报告。</span> : styleReferenceCandidates.map((report) => {
                  const selected = styleReferences.some((reference) => reference.revision_id === report.id)
                  return <article key={report.id} className={`style-reference-candidate-row ${selected ? 'is-selected' : ''}`}><div><strong>{report.site_code} · {report.visit_code}</strong><span>{report.site_name} · {report.visit_type} · {report.visit_date} · {report.version_number}</span></div><button type="button" className="button quiet small" disabled={!isRuleEditable || selected} onClick={() => addStyleReference(report)}>{selected ? '已选为样例' : '加入样例'}</button></article>
                })}
              </div>
            </div>
          </div>
          {selectedRule && <div className="configuration-control-card rule-approval-card">
            <div><strong>启用控制</strong><span>规则包需经 QA / 临床运营审批后才能用于创建新的监查访视；已创建访视始终使用自身冻结快照。</span></div>
            <dl className="configuration-facts"><div><dt>提交</dt><dd>{selectedRule.submitted_at ? `${selectedRule.submitted_by || '—'} · ${selectedRule.submitted_at}` : '尚未提交'}</dd></div><div><dt>审批</dt><dd>{selectedRule.reviewed_at ? `${selectedRule.reviewed_by || '—'} · ${selectedRule.reviewed_at}` : '尚未审批'}</dd></div></dl>
            {selectedRule.eligibility && <p className={`configuration-check ${selectedRule.eligibility.expires_soon ? 'is-warning' : ''}`}><strong>按 {selectedRule.eligibility.assessment_date} 判断：</strong>{selectedRule.eligibility.message}</p>}
            {selectedRule.review_note && <p className="configuration-note"><strong>最新意见：</strong>{selectedRule.review_note}</p>}
            {(isAdmin || isQaReviewer) && <label className="configuration-note-input">审批意见 / 退回理由<textarea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="批准时可补充说明；退回时必须填写原因。" /></label>}
            <div className="configuration-actions">
              {isAdmin && ['draft', 'rejected'].includes(selectedRule.status) && <button type="button" className="button primary" onClick={() => void runRuleApprovalAction('submit')}>提交审批</button>}
              {isAdmin && selectedRule.status === 'pending_approval' && <button type="button" className="button quiet" onClick={() => void runRuleApprovalAction('withdraw')}>撤回审批</button>}
              {isAdmin && selectedRule.status === 'active' && <button type="button" className="button quiet" onClick={() => void runRuleApprovalAction('deactivate')}>停用规则包</button>}
              {isQaReviewer && selectedRule.status === 'pending_approval' && <><button type="button" className="button primary" onClick={() => void runRuleApprovalAction('approve')}>批准并启用</button><button type="button" className="button danger" disabled={!reviewNote.trim()} onClick={() => void runRuleApprovalAction('reject')}>退回配置</button></>}
            </div>
          </div>}
          <div className="governance-actions">
            <button type="button" className="button quiet" onClick={() => { setSelectedId(''); setDraft(blankDraft()); setEscalationSlaEditor(blankEscalationSlaEditor()); setStyleReferences([]); setTerminologyEntries(readConfiguredTerminology(parseRuleContent(blankDraft().content))); setPreferredPhraseEntries([]); setReviewNote('') }} disabled={!isAdmin}>新建草稿</button>
            <button type="button" className="button primary" onClick={() => void saveRule(selectedId ? 'update' : 'create')} disabled={!isRuleEditable || !draft.name.trim()}>{selectedId ? '保存规则包' : '创建规则包'}</button>
          </div>
        </div>
      </section>

      <RulePackCitationSearch frozenRule={frozenRule} selectedRule={selectedRule} rules={rules} onNotice={onNotice} />

      <section className="governance-grid">
        <div className="section-block frozen-rule-card">
          <div className="section-header compact-header"><div><h2>本访视规则冻结快照</h2><p>以下内容以创建访视时的版本为准，后续项目规则改动不影响本访视报告。</p></div><span className="section-code">FROZEN</span></div>
          <dl className="frozen-rule-facts"><div><dt>规则包</dt><dd>{frozenRule?.name ?? '—'}</dd></div><div><dt>版本</dt><dd>{frozenRule?.version ?? '—'}</dd></div><div><dt>生效区间</dt><dd>{frozenRule?.effective_from || '—'} 至 {frozenRule?.effective_to || '—'}</dd></div></dl>
          <pre className="rule-json">{JSON.stringify(frozenRule?.content ?? {}, null, 2)}</pre>
        </div>

        <div className="section-block adapter-card">
          <div className="section-header compact-header"><div><h2>模型适配契约</h2><p>{adapter?.status_note ?? '正在加载适配器状态。'}</p></div><span className="section-code">ADAPTER</span></div>
          {adapter && <div className="governance-form adapter-form">
            <label>提供方<select value={adapter.provider} onChange={(event) => setAdapter({ ...adapter, provider: event.target.value as AdapterConfig['provider'] })} disabled={!isAdmin}><option value="deterministic">本地确定性适配器</option><option value="openai_compatible">OpenAI-compatible（待接入）</option></select></label>
            <label>模型名称<input value={adapter.model} onChange={(event) => setAdapter({ ...adapter, model: event.target.value })} disabled={!isAdmin} placeholder="仅作为后续配置" /></label>
            <label className="governance-wide">服务地址<input value={adapter.base_url} onChange={(event) => setAdapter({ ...adapter, base_url: event.target.value })} disabled={!isAdmin} placeholder="仅保存，不会请求" /></label>
            <label className="adapter-toggle"><input type="checkbox" checked={adapter.enabled} onChange={(event) => setAdapter({ ...adapter, enabled: event.target.checked })} disabled={!isAdmin} />记录为后续启用意向（演示环境仍不会联网）</label>
          </div>}
          <div className="governance-actions"><span className="adapter-status">本地确定性适配器当前可用</span><button type="button" className="button primary" onClick={() => void saveAdapter()} disabled={!isAdmin || !adapter}>保存适配参数</button></div>
        </div>
      </section>

      <section className="section-block frozen-style-reference-card">
        <div className="section-header compact-header"><div><h2>本访视冻结的历史写作样例</h2><p>来源由创建访视时的已审批规则包冻结；只供人工参考写作风格，不作为当前报告事实、证据或自动填写来源。</p></div><span className="section-code">STYLE REFERENCE</span></div>
        {frozenStyleReferences.length === 0 ? <div className="empty-state inline"><span>本访视冻结的规则包未配置历史写作样例。</span></div> : <div className="frozen-style-reference-list">{frozenStyleReferences.map((reference) => <article key={reference.revision_id} className="frozen-style-reference-row"><div><strong>{controlledStyleReferenceLabel(reference)}</strong><span>{reference.site_name || '来源中心名称未记录'}{reference.visit_type ? ` · ${reference.visit_type}` : ''} · 仅写作风格参考</span>{reference.note && <small>管理员备注：{reference.note}</small>}</div><button type="button" className="button quiet small" onClick={() => void downloadStyleReference(reference)}>下载来源 Word</button></article>)}</div>}
      </section>

      <section className="section-block frozen-language-rule-card">
        <div className="section-header compact-header"><div><h2>本访视冻结的语言规则</h2><p>术语对照和固定表达以创建访视时冻结的规则包为准；仅在 CRA 主动生成候选稿后提供可采纳的展示建议。</p></div><span className="section-code">LANGUAGE RULES</span></div>
        {frozenTerminologyEntries.length === 0 && frozenPreferredPhraseEntries.length === 0 ? <div className="empty-state inline"><span>本访视冻结的规则包未配置额外语言规则。</span></div> : <div className="frozen-language-rule-grid">
          <div><strong>术语对照</strong>{frozenTerminologyEntries.length === 0 ? <span>未配置</span> : frozenTerminologyEntries.map((entry) => <span key={`frozen-term-${entry.source}`}>{entry.source} → {entry.target}</span>)}</div>
          <div><strong>固定表达</strong>{frozenPreferredPhraseEntries.length === 0 ? <span>未配置</span> : frozenPreferredPhraseEntries.map((entry, index) => <span key={`frozen-phrase-${index}`}>{entry.source} → {entry.target}</span>)}</div>
        </div>}
      </section>

      <BreakGlassPanel state={state} onNotice={onNotice} />
    </div>
  )
}
