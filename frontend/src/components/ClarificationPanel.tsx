import { useMemo, useState } from 'react'
import { api } from '../api'
import type { ClarificationItem, DemoState, TableTask } from '../types'

interface ClarificationPanelProps {
  state: DemoState
  canEdit: boolean
  onStateChange: (state: DemoState) => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
  onSelectTask: (task: TableTask) => void
  onSelectAction: (actionItemId: string) => void
}

type DisplayMode = 'focused' | 'batch'

const issueTypeLabel: Record<string, string> = {
  missing: '待补录',
  conflict: '待决策',
}

const issueStatusLabel: Record<string, string> = {
  open: '待 CRA 处理',
  manual_required: '已转人工待办',
  resolved: '已处理',
}

const taskPosition = (task: TableTask) => task.task_type === 'system_device_check'
  ? '系统／设备核查'
  : `表 ${String(task.index).padStart(2, '0')}`

const activeIssue = (item: ClarificationItem) => item.status === 'open' || item.status === 'manual_required'

export function ClarificationPanel({ state, canEdit, onStateChange, onNotice, onSelectTask, onSelectAction }: ClarificationPanelProps) {
  const [displayMode, setDisplayMode] = useState<DisplayMode>('focused')
  const [answerByItem, setAnswerByItem] = useState<Record<string, string>>({})
  const [candidateByItem, setCandidateByItem] = useState<Record<string, string>>({})
  const [busyItemId, setBusyItemId] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  const allTasks = [...state.table_tasks, ...(state.system_check_tasks ?? [])]
  const issues = state.clarification_items ?? []
  const unresolved = useMemo(() => issues.filter(activeIssue), [issues])
  const visibleIssues = displayMode === 'focused' ? unresolved.slice(0, 1) : unresolved
  const blockingCount = unresolved.filter((item) => item.is_blocking).length

  const refresh = async () => {
    if (!state.visit.id) return
    try {
      setRefreshing(true)
      const response = await api.refreshClarifications(state.visit.id, state.visit.cra_name || '演示 CRA')
      onStateChange(response.workspace)
      onNotice(response.items.length > 0 ? `已更新 ${response.items.length} 项缺失或冲突问题。` : '当前未发现需要补录或决策的问题。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '问题扫描失败', 'error')
    } finally {
      setRefreshing(false)
    }
  }

  const respond = async (item: ClarificationItem, action: 'answer' | 'select_candidate' | 'supplement' | 'manual_escalation') => {
    if (!canEdit || !state.visit.id) return
    const answer = (answerByItem[item.id] ?? '').trim()
    const selectedCandidate = candidateByItem[item.id] ?? ''
    if (action === 'answer' && !answer) {
      onNotice('请先补录该必填字段的 CRA 已确认内容。', 'error')
      return
    }
    if (action === 'select_candidate' && !selectedCandidate) {
      onNotice('请选择一条可采用的候选记录作为冲突决策依据。', 'error')
      return
    }
    if (action === 'supplement' && !answer) {
      onNotice('请填写经核对后的 CRA 决策文本。', 'error')
      return
    }
    if (action === 'manual_escalation' && !answer) {
      onNotice('请填写提交人工升级的背景说明。', 'error')
      return
    }
    try {
      setBusyItemId(item.id)
      const response = await api.respondToClarification(state.visit.id, item.id, {
        action,
        answer_text: answer,
        selected_candidate_id: selectedCandidate,
        actor_name: state.visit.cra_name || '演示 CRA',
      })
      onStateChange(response.workspace)
      if (response.item.status === 'manual_required' && action === 'manual_escalation') {
        const contextLabel = response.item.source.conflict_kind === 'template_rule_contract' ? '模板／规则包契约' : '规则包适用期'
        onNotice(`已建立${contextLabel}人工升级待办；报告仍会保持阻断，直至按项目 SOP 完成人工确认。`)
      } else if (response.item.status === 'manual_required') {
        onNotice('本项连续两次未形成有效补录，已转入人工待办；请核对来源后再处理。', 'error')
      } else if (response.item.status === 'resolved') {
        setAnswerByItem((current) => ({ ...current, [item.id]: '' }))
        setCandidateByItem((current) => ({ ...current, [item.id]: '' }))
        onNotice('CRA 处理决定已留痕，报告门禁将重新计算。')
      } else {
        onNotice('本次补录未能解决目标问题，请按提示补充。', 'error')
      }
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '问题处理保存失败', 'error')
    } finally {
      setBusyItemId('')
    }
  }

  const openTask = (item: ClarificationItem) => {
    const task = allTasks.find((candidate) => candidate.id === item.target_task_id)
    if (!task) {
      onNotice('未找到该问题关联的监查任务，请刷新后重试。', 'error')
      return
    }
    onSelectTask(task)
    onNotice(`已定位到${taskPosition(task)}“${task.title}”，请补录结论和执行依据后重新扫描。`)
  }

  const openAction = (item: ClarificationItem) => {
    const actionItemId = String(item.source.action_item_id ?? '')
    if (!actionItemId) {
      onNotice('未找到该问题关联的行动项，请刷新后重试。', 'error')
      return
    }
    onSelectAction(actionItemId)
    onNotice('已定位到关联行动项；请修正状态，或补充关闭说明/附件证据后重新扫描。')
  }

  const renderIssue = (item: ClarificationItem) => {
    const isBusy = busyItemId === item.id
    const task = allTasks.find((candidate) => candidate.id === item.target_task_id)
    const selectableCandidates = item.candidates.filter((candidate) => candidate.kind === 'confirmed_field' || candidate.kind === 'frozen_document')
    const latestInvalid = item.responses?.find((response) => response.response_status === 'invalid')
    const conflictKind = String(item.source.conflict_kind ?? '')
    const actionTitle = String(item.source.action_title ?? '')
    const rulePack = item.source.rule_pack as Record<string, unknown> | undefined
    const activityStart = String(item.source.activity_start_date ?? '')
    const activityEnd = String(item.source.activity_end_date ?? '')
    const expectedTemplateProfile = String(item.source.expected_template_profile ?? '')
    const actualTemplateProfile = String(item.source.actual_template_profile ?? '')
    const expectedSopVersion = String(item.source.expected_sop_version ?? '')
    const actualSopVersion = String(item.source.actual_sop_version ?? '')
    const isConfigurationConflict = conflictKind === 'rule_period' || conflictKind === 'template_rule_contract'

    return <article className={`clarification-item ${item.status === 'manual_required' ? 'is-manual' : ''}`} key={item.id}>
      <div className="clarification-item-heading">
        <div>
          <div className="clarification-badges">
            <span className={`clarification-type ${item.issue_type}`}>{issueTypeLabel[item.issue_type] ?? item.issue_type}</span>
            {item.is_blocking && <span className="clarification-blocking">阻断提交</span>}
            {item.status === 'manual_required' && <span className="clarification-manual">人工核对</span>}
          </div>
          <h3>{item.title}</h3>
        </div>
        <small>{item.target_table ? `表 ${String(item.target_table).padStart(2, '0')}` : '访视级'}</small>
      </div>
      <p className="clarification-reason">{item.reason}</p>
      <p className="clarification-prompt">{item.prompt}</p>
      {latestInvalid && <p className="clarification-last-response">上次未采纳：{latestInvalid.invalid_reason}</p>}

      {item.issue_type === 'missing' && task && <div className="clarification-task-route">
        <span>此项需要通过任务执行区补录，系统不会以自由文本替代监查结论。</span>
        <button type="button" className="button secondary" disabled={!canEdit} onClick={() => openTask(item)}>前往补录任务</button>
      </div>}

      {item.issue_type === 'missing' && !task && <div className="clarification-answer">
        <label>CRA 已确认内容
          <textarea
            value={answerByItem[item.id] ?? ''}
            disabled={!canEdit || isBusy}
            placeholder="仅录入已核实的事实；系统会保留本次补录来源。"
            onChange={(event) => setAnswerByItem((current) => ({ ...current, [item.id]: event.target.value }))}
          />
        </label>
        <div className="clarification-actions">
          <span>{item.field_key ? `写入字段：${item.field_key}` : '写入模板必填位置'}</span>
          <button type="button" className="button secondary" disabled={!canEdit || isBusy} onClick={() => void respond(item, 'answer')}>
            {isBusy ? '正在保存…' : '确认补录'}
          </button>
        </div>
      </div>}

      {item.issue_type === 'conflict' && isConfigurationConflict && <div className="clarification-manual-route">
        <div><strong>{conflictKind === 'template_rule_contract' ? '模板／规则包契约需要人工确认' : '规则包适用期需要人工确认'}</strong><span>{conflictKind === 'template_rule_contract' ? <>冻结规则包：{String(rulePack?.name ?? '未登记')}{rulePack?.version ? ` · ${String(rulePack.version)}` : ''}；模板：期望 {expectedTemplateProfile || '未登记'} / 当前 {actualTemplateProfile || '未解析'}；SOP：期望 {expectedSopVersion || '未登记'} / 当前 {actualSopVersion || '未登记'}。</> : <>冻结规则包：{String(rulePack?.name ?? '未登记')}{rulePack?.version ? ` · ${String(rulePack.version)}` : ''}；活动日期：{activityStart || '未登记'} 至 {activityEnd || '未登记'}。</>}</span></div>
        <label>提交人工升级的背景说明
          <textarea
            value={answerByItem[item.id] ?? ''}
            disabled={!canEdit || isBusy}
            placeholder={conflictKind === 'template_rule_contract' ? '例如：已发现规则包与模板/SOP 冻结契约不一致，按项目 SOP 提请 PM/LM 协调 QA/临床运营确认。' : '例如：该多日监查跨规则包失效日，已按项目 SOP 提请 PM/LM 协调 QA/临床运营确认过渡策略。'}
            onChange={(event) => setAnswerByItem((current) => ({ ...current, [item.id]: event.target.value }))}
          />
        </label>
        <div className="clarification-actions">
          <span>该操作只创建人工升级待办，不会改变规则包、监查日期或报告事实。</span>
          <button type="button" className="button secondary" disabled={!canEdit || isBusy} onClick={() => void respond(item, 'manual_escalation')}>
            {isBusy ? '正在提交…' : '提交人工升级'}
          </button>
        </div>
      </div>}

      {item.issue_type === 'conflict' && conflictKind === 'action_closure' && <div className="clarification-manual-route action-remediation-route">
        <div><strong>需要回到行动项修正</strong><span>{actionTitle || '关联行动项'}的状态、关闭说明和附件证据必须在原行动项中维护。</span></div>
        <div className="clarification-actions">
          <span>修正后点击“扫描问题”，系统会按当前行动项状态重新计算。</span>
          <button type="button" className="button secondary" disabled={!canEdit} onClick={() => openAction(item)}>前往行动项</button>
        </div>
      </div>}

      {item.issue_type === 'conflict' && !conflictKind && <div className="clarification-conflict-resolution">
        <div className="clarification-candidates">
          <strong>可采用候选记录</strong>
          {selectableCandidates.length > 0 ? <select
            value={candidateByItem[item.id] ?? ''}
            disabled={!canEdit || isBusy}
            onChange={(event) => setCandidateByItem((current) => ({ ...current, [item.id]: event.target.value }))}
          >
            <option value="">请选择经核对后可采用的记录</option>
            {selectableCandidates.map((candidate) => <option key={candidate.id} value={candidate.id}>
              {candidate.kind === 'frozen_document' ? '冻结受控文件 · ' : '已确认记录 · '}{candidate.value || '（无文本）'}
            </option>)}
          </select> : <span className="clarification-empty-candidate">暂无可直接采用的候选记录，请填写补充决策。</span>}
        </div>
        <div className="clarification-actions">
          <span>选择后将保留全部候选来源，并以 CRA 决策生成新的确认字段。</span>
          <button type="button" className="button secondary" disabled={!canEdit || isBusy || selectableCandidates.length === 0} onClick={() => void respond(item, 'select_candidate')}>
            {isBusy ? '正在保存…' : '采用所选记录'}
          </button>
        </div>
        <label>或填写经核对后的 CRA 决策文本
          <textarea
            value={answerByItem[item.id] ?? ''}
            disabled={!canEdit || isBusy}
            placeholder="仅在已完成来源核对后填写；不可凭经验推测文件版本。"
            onChange={(event) => setAnswerByItem((current) => ({ ...current, [item.id]: event.target.value }))}
          />
        </label>
        <div className="clarification-actions">
          <span>补充决策不会覆盖候选记录，原始候选将保留为历史依据。</span>
          <button type="button" className="button secondary" disabled={!canEdit || isBusy} onClick={() => void respond(item, 'supplement')}>
            {isBusy ? '正在保存…' : '确认补充决策'}
          </button>
        </div>
      </div>}
    </article>
  }

  return <section className="section-block clarification-panel">
    <div className="section-header clarification-header">
      <div>
        <h2>缺失与冲突处理</h2>
        <p>按风险和报告阻断性排序。系统只追问明确缺失点；不会猜测法规适用性、医学判断或严重程度。</p>
      </div>
      <div className="clarification-header-actions">
        <span className={blockingCount > 0 ? 'clarification-count is-blocking' : 'clarification-count'}>{blockingCount} 项阻断</span>
        <button type="button" className="button tertiary" disabled={refreshing || !state.visit.id} onClick={() => void refresh()}>{refreshing ? '正在扫描…' : '扫描问题'}</button>
      </div>
    </div>
    <div className="clarification-toolbar">
      <div className="clarification-mode" role="group" aria-label="问题处理模式">
        <button type="button" className={displayMode === 'focused' ? 'is-active' : ''} onClick={() => setDisplayMode('focused')}>聚焦追问</button>
        <button type="button" className={displayMode === 'batch' ? 'is-active' : ''} onClick={() => setDisplayMode('batch')}>批量清单</button>
      </div>
      <span>{unresolved.length > 0 ? `当前 ${unresolved.length} 项待处理，状态：${issueStatusLabel[unresolved[0].status] ?? unresolved[0].status}` : '尚未扫描，或当前没有待处理问题。'}</span>
    </div>
    {visibleIssues.length === 0 ? <div className="empty-state inline"><strong>当前没有待处理的问题</strong><span>在提交或生成报告前，系统仍会重新计算关键缺失与冲突。</span></div> : <div className="clarification-list">{visibleIssues.map(renderIssue)}</div>}
    {displayMode === 'focused' && unresolved.length > 1 && <div className="clarification-next"><span>其余 {unresolved.length - 1} 项将在本项处理后继续提示。</span><button type="button" className="button text" onClick={() => setDisplayMode('batch')}>切换为批量处理</button></div>}
  </section>
}
