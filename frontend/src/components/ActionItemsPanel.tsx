import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../api'
import type { ActionItem, DemoState, Finding } from '../types'

interface ActionItemsPanelProps {
  state: DemoState
  onStateChange: (state: DemoState) => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
  focusActionId?: string | null
}

const statusLabel: Record<ActionItem['status'], string> = {
  open: '待跟进',
  in_progress: '跟进中',
  closed: '已关闭',
}

const findingCategoryLabel = (finding: Finding) => {
  if (finding.category === 'sae') return 'SAE'
  if (finding.category === 'ae') return 'AE'
  if (finding.category === 'deviation') return '方案偏离'
  return finding.category || '监查发现'
}

const toggleFindingId = (current: string[], findingId: string) => (
  current.includes(findingId) ? current.filter((item) => item !== findingId) : [...current, findingId]
)

export function ActionItemsPanel({ state, onStateChange, onNotice, focusActionId }: ActionItemsPanelProps) {
  const [draft, setDraft] = useState({ title: '', description: '', owner: '中心 CRC', due_date: '' })
  const [draftFindingIds, setDraftFindingIds] = useState<string[]>([])
  const [editingLinksFor, setEditingLinksFor] = useState<string | null>(null)
  const [linkDrafts, setLinkDrafts] = useState<Record<string, string[]>>({})
  const [closureNotes, setClosureNotes] = useState<Record<string, string>>({})
  const [statusDrafts, setStatusDrafts] = useState<Record<string, ActionItem['status']>>({})
  const [statusNotes, setStatusNotes] = useState<Record<string, string>>({})
  const [files, setFiles] = useState<Record<string, File | null>>({})
  const [deidentificationAcks, setDeidentificationAcks] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const visitId = state.visit.id
  const canManage = state.current_role === 'CRA'
  const findings = state.findings ?? []
  const historicalOpenActions = state.historical_open_actions ?? []

  useEffect(() => {
    if (!focusActionId) return
    document.getElementById(`action-item-${focusActionId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [focusActionId])

  const refresh = async () => {
    if (visitId) onStateChange(await api.getState(visitId))
  }

  const refreshClarifications = async () => {
    if (!visitId) return
    const response = await api.refreshClarifications(visitId, state.visit.cra_name || '演示 CRA')
    onStateChange(response.workspace)
  }

  const clearStatusDraft = (actionItemId: string) => {
    setStatusDrafts((current) => {
      const next = { ...current }
      delete next[actionItemId]
      return next
    })
    setStatusNotes((current) => {
      const next = { ...current }
      delete next[actionItemId]
      return next
    })
  }

  const createAction = async (event: FormEvent) => {
    event.preventDefault()
    if (!visitId || !canManage) return
    try {
      setBusy(true)
      await api.createActionItem(visitId, { ...draft, finding_ids: draftFindingIds, actor_name: state.visit.cra_name })
      setDraft({ title: '', description: '', owner: '中心 CRC', due_date: '' })
      setDraftFindingIds([])
      await refresh()
      onNotice('已建立行动项，可在本页持续补充关闭证据。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '新建行动项失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const closeAction = async (action: ActionItem) => {
    if (!visitId || !canManage) return
    try {
      setBusy(true)
      await api.updateActionItem(visitId, action.id, {
        status: 'closed',
        closure_note: closureNotes[action.id] ?? action.closure_note,
        actor_name: state.visit.cra_name,
      })
      clearStatusDraft(action.id)
      await refreshClarifications()
      onNotice(`行动项“${action.title}”已关闭。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '关闭行动项失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const saveActionStatus = async (action: ActionItem) => {
    if (!visitId || !canManage) return
    const nextStatus = statusDrafts[action.id] ?? action.status
    if (nextStatus === action.status) return
    try {
      setBusy(true)
      await api.updateActionItem(visitId, action.id, {
        status: nextStatus,
        status_change_note: statusNotes[action.id] ?? '',
        actor_name: state.visit.cra_name,
      })
      clearStatusDraft(action.id)
      await refreshClarifications()
      onNotice(nextStatus === 'in_progress' ? `行动项“${action.title}”已标记为跟进中。` : `行动项“${action.title}”已重新打开。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '行动项状态更新失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const uploadEvidence = async (action: ActionItem) => {
    const file = files[action.id]
    if (!file || !visitId || !canManage) {
      onNotice('请先选择需要留存的整改证据文件。', 'error')
      return
    }
    if (!deidentificationAcks[action.id]) {
      onNotice('请先勾选“本附件已脱敏”声明后再上传。', 'error')
      return
    }
    try {
      setBusy(true)
      await api.uploadAttachment(visitId, file, action.id, `行动项证据：${action.title}`, true)
      setFiles((current) => ({ ...current, [action.id]: null }))
      setDeidentificationAcks((current) => ({ ...current, [action.id]: false }))
      await refreshClarifications()
      onNotice(`已留存“${file.name}”作为行动项证据。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '附件上传失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const saveLinkedFindings = async (action: ActionItem) => {
    if (!visitId || !canManage) return
    try {
      setBusy(true)
      await api.replaceActionItemFindings(
        visitId,
        action.id,
        linkDrafts[action.id] ?? action.finding_ids ?? [],
        state.visit.cra_name,
      )
      setEditingLinksFor(null)
      await refresh()
      onNotice(`已更新“${action.title}”的关联发现。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '关联发现更新失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const bringHistoricalActionForward = async (sourceActionItemId: string) => {
    if (!visitId || !canManage) return
    try {
      setBusy(true)
      await api.createHistoricalActionFollowUp(visitId, sourceActionItemId, state.visit.cra_name)
      await refresh()
      onNotice('已将既往未关闭行动项带入本次访视跟进。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '既往行动项带入失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="section-block action-items-panel">
      <div className="section-header">
        <div><h2>行动项与关闭证据</h2><p>CRA 建立、跟进和关闭行动项；整改文件只作证据留存，不进行 AI 解析或自动判断。</p></div>
        <span className="section-code">ACTION / EVIDENCE</span>
      </div>

      {historicalOpenActions.length > 0 && <div className="historical-actions">
        <div className="historical-actions-heading">
          <div><strong>既往未关闭行动项</strong><span>来自同项目、同中心的早期访视；带入后会创建新的本次跟进事项，不改写历史报告。</span></div>
          <span>{historicalOpenActions.length} 项待跟进</span>
        </div>
        <div className="historical-action-list">
          {historicalOpenActions.map((action) => <article key={action.id} className="historical-action-row">
            <div>
              <strong>{action.title}</strong>
              <p>来源访视：{action.source_visit_code} · {action.source_visit_date}{action.due_date ? ` · 原计划完成：${action.due_date}` : ''}</p>
              <span>{action.description}</span>
            </div>
            {canManage ? <button type="button" className="button quiet" disabled={busy} onClick={() => void bringHistoricalActionForward(action.id)}>带入本次跟进</button> : <small>由 CRA 带入本次跟进</small>}
          </article>)}
        </div>
      </div>}

      {canManage ? <form className="action-create-form" onSubmit={createAction}>
        <label>行动项标题<input required value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} placeholder="例如：补充 ICF 版本归档" /></label>
        <label>责任人<input value={draft.owner} onChange={(event) => setDraft({ ...draft, owner: event.target.value })} /></label>
        <label>计划完成日<input value={draft.due_date} onChange={(event) => setDraft({ ...draft, due_date: event.target.value })} placeholder="YYYY-MM-DD" /></label>
        <label className="action-description">行动项说明<textarea required value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} placeholder="记录需要整改的事实、中心承诺或下一步跟进方式。" /></label>
        {findings.length > 0 && <fieldset className="action-finding-picker">
          <legend>关联已有发现（可多选）</legend>
          <div className="finding-option-list">
            {findings.map((finding) => <label key={finding.id} className="finding-option">
              <input
                type="checkbox"
                checked={draftFindingIds.includes(finding.id)}
                onChange={() => setDraftFindingIds((current) => toggleFindingId(current, finding.id))}
              />
              <span><b>{findingCategoryLabel(finding)}</b>{finding.subject_code ? ` · ${finding.subject_code}` : ''} · {finding.description}</span>
            </label>)}
          </div>
        </fieldset>}
        <button type="submit" className="button secondary" disabled={busy || !visitId}>建立行动项</button>
      </form> : <div className="role-readonly-banner">当前为 {state.current_role === 'PM_LM' ? 'PM / LM' : state.current_role === 'MEDICAL_DATA_REVIEWER' ? '医学监察 / 数据管理' : state.current_role === 'QA_CLINICAL_OPS' ? 'QA / 临床运营审批人' : '项目管理员'} 视图：可查看行动项与证据，事实建立、附件留存与关闭由 CRA 完成。</div>}

      {state.action_items.length === 0 ? <div className="empty-state"><strong>尚无行动项</strong><span>发现需跟进事项后，可由 CRA 在此建立并持续归档证据。</span></div> : (
        <div className="action-item-list">
          {state.action_items.map((action) => {
            const evidence = state.attachments.filter((attachment) => attachment.action_item_id === action.id)
            const linkedFindings = action.linked_findings ?? []
            const selectedFindingIds = linkDrafts[action.id] ?? action.finding_ids ?? []
            const nextStatus = statusDrafts[action.id] ?? action.status
            const closureNeedsBasis = action.status === 'closed' && !action.closure_note.trim() && evidence.length === 0
            return <article id={`action-item-${action.id}`} className={`action-item ${focusActionId === action.id ? 'is-highlighted' : ''}`} key={action.id}>
              <div className="action-item-header">
                <div><span className={`action-status action-${action.status}`}>{statusLabel[action.status]}</span><h3>{action.title}</h3></div>
                <span className="action-due">责任人：{action.owner || '待指定'} {action.due_date ? `· 计划完成：${action.due_date}` : ''}{action.source_visit_code ? ` · 来源：${action.source_visit_code}` : ''}</span>
              </div>
              <p>{action.description}</p>
              {canManage && <div className="action-status-controls">
                <label>跟进状态
                  <select value={nextStatus} onChange={(event) => setStatusDrafts((current) => ({ ...current, [action.id]: event.target.value as ActionItem['status'] }))}>
                    <option value="open">待跟进</option>
                    <option value="in_progress">跟进中</option>
                    {action.status === 'closed' && <option value="closed">已关闭</option>}
                  </select>
                </label>
                <label>状态更新说明（可选）
                  <input value={statusNotes[action.id] ?? ''} onChange={(event) => setStatusNotes((current) => ({ ...current, [action.id]: event.target.value }))} placeholder="例如：已收到中心补充材料，CRA 开始复核。" />
                </label>
                <button type="button" className="button quiet" disabled={busy || nextStatus === action.status} onClick={() => void saveActionStatus(action)}>{action.status === 'closed' ? '重新打开行动项' : '更新状态'}</button>
                <small>{action.status === 'closed' ? '重新打开后，需要再次补充关闭依据并由 CRA 关闭。' : '需要关闭时，请使用下方关闭区保存说明或整改证据。'}</small>
              </div>}
              <div className="linked-findings">
                <div className="linked-findings-heading">
                  <strong>关联发现（{linkedFindings.length}）</strong>
                  {canManage && <button
                    type="button"
                    className="text-button"
                    disabled={busy}
                    onClick={() => {
                      setEditingLinksFor(editingLinksFor === action.id ? null : action.id)
                      setLinkDrafts((current) => ({ ...current, [action.id]: current[action.id] ?? action.finding_ids ?? [] }))
                    }}
                  >{editingLinksFor === action.id ? '收起调整' : '调整关联'}</button>}
                </div>
                {linkedFindings.length === 0 ? <span className="linked-findings-empty">尚未关联具体发现</span> : <div className="linked-finding-tags">
                  {linkedFindings.map((finding) => <span key={finding.id} className="linked-finding-tag"><b>{findingCategoryLabel(finding)}</b>{finding.subject_code ? ` · ${finding.subject_code}` : ''} · {finding.description}</span>)}
                </div>}
                {editingLinksFor === action.id && <div className="linked-finding-editor">
                  {findings.length === 0 ? <span>当前访视暂无可关联发现。</span> : findings.map((finding) => <label key={finding.id} className="finding-option">
                    <input
                      type="checkbox"
                      checked={selectedFindingIds.includes(finding.id)}
                      onChange={() => setLinkDrafts((current) => ({
                        ...current,
                        [action.id]: toggleFindingId(current[action.id] ?? action.finding_ids ?? [], finding.id),
                      }))}
                    />
                    <span><b>{findingCategoryLabel(finding)}</b>{finding.subject_code ? ` · ${finding.subject_code}` : ''} · {finding.description}</span>
                  </label>)}
                  <button type="button" className="button quiet" disabled={busy} onClick={() => void saveLinkedFindings(action)}>保存关联</button>
                </div>}
              </div>
              {action.status === 'closed' && <p className="closure-note">关闭说明：{action.closure_note || '未填写关闭说明'} {action.closed_at ? `· ${action.closed_at}` : ''}</p>}
              <div className="evidence-list">
                <strong>留存证据（{evidence.length}）</strong>
                {evidence.length === 0 ? <span>暂未上传附件</span> : evidence.map((attachment) => <a key={attachment.id} className="evidence-link" href={`/api/attachments/${attachment.id}/download`} target="_blank" rel="noreferrer">{attachment.file_name}<small>{attachment.created_at}</small></a>)}
              </div>
              {(action.status !== 'closed' || closureNeedsBasis) && canManage && <div className="action-close-row">
                <label className="action-file-field">上传关闭证据<input type="file" accept=".pdf,.png,.jpg,.jpeg,.txt,.csv,.eml,.docx,.xlsx" onChange={(event) => setFiles({ ...files, [action.id]: event.target.files?.[0] ?? null })} /><small>{files[action.id]?.name ?? '尚未选择文件'}</small></label>
                <label className="deidentification-ack"><input type="checkbox" checked={deidentificationAcks[action.id] ?? false} onChange={(event) => setDeidentificationAcks({ ...deidentificationAcks, [action.id]: event.target.checked })} />本附件已脱敏，不含直接身份信息、源文件或非盲数据</label>
                <button type="button" className="button quiet" disabled={busy} onClick={() => void uploadEvidence(action)}>留存附件</button>
                <label className="closure-field">关闭说明<textarea value={closureNotes[action.id] ?? ''} onChange={(event) => setClosureNotes({ ...closureNotes, [action.id]: event.target.value })} placeholder="例如：已核对中心整改材料，符合关闭条件。" /></label>
                <button type="button" className="button primary" disabled={busy} onClick={() => void closeAction(action)}>{closureNeedsBasis ? '补充关闭依据' : 'CRA 确认关闭'}</button>
              </div>}
            </article>
          })}
        </div>
      )}
    </section>
  )
}
