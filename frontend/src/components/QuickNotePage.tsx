import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { getBrowserClientId, makeBrowserDraftId, readOfflineDraftQueue, type BrowserDraft, writeOfflineDraftQueue } from '../offlineDraftStorage'
import type { DemoState, RecordItem, TableTask } from '../types'

interface QuickNotePageProps {
  state: DemoState
  onStateChange: (state: DemoState) => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

const currentClientTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'unknown'

const taskLabel = (task: TableTask) => `${task.task_type === 'system_device_check' ? '系统／设备' : `表 ${String(task.index).padStart(2, '0')}`} · ${task.title}`

const displayDraftTime = (value: string) => value.replace('T', ' ')

export function QuickNotePage({ state, onStateChange, onNotice }: QuickNotePageProps) {
  const visitId = state.visit.id ?? ''
  const reportLocked = ['submitted', 'approved'].includes(state.report_status)
  const canEdit = state.current_role === 'CRA' && !reportLocked
  const allTasks = useMemo(() => [...state.table_tasks, ...(state.system_check_tasks ?? [])], [state.table_tasks, state.system_check_tasks])
  const [text, setText] = useState('')
  const [linkedTaskId, setLinkedTaskId] = useState('')
  const [tags, setTags] = useState('')
  const [clientKey, setClientKey] = useState('')
  const [drafts, setDrafts] = useState<BrowserDraft[]>([])
  const [duplicateCandidates, setDuplicateCandidates] = useState<RecordItem[]>([])
  const [saving, setSaving] = useState(false)
  const [syncingDraftId, setSyncingDraftId] = useState<string | null>(null)
  const [online, setOnline] = useState(() => navigator.onLine)

  useEffect(() => {
    let cancelled = false
    void readOfflineDraftQueue(visitId).then((items) => {
      if (!cancelled) setDrafts(items)
    })
    setText('')
    setLinkedTaskId('')
    setTags('')
    setClientKey('')
    setDuplicateCandidates([])
    return () => {
      cancelled = true
    }
  }, [visitId])

  useEffect(() => {
    const updateOnline = () => setOnline(navigator.onLine)
    window.addEventListener('online', updateOnline)
    window.addEventListener('offline', updateOnline)
    return () => {
      window.removeEventListener('online', updateOnline)
      window.removeEventListener('offline', updateOnline)
    }
  }, [])

  const updateDrafts = async (next: BrowserDraft[]) => {
    await writeOfflineDraftQueue(visitId, next)
    setDrafts(next)
  }

  const resetComposer = () => {
    setText('')
    setLinkedTaskId('')
    setTags('')
    setClientKey('')
    setDuplicateCandidates([])
  }

  const saveRecord = async (forceNew = false) => {
    if (!canEdit) {
      onNotice('当前角色仅可查看；现场速记由 CRA 保存。', 'error')
      return
    }
    const normalizedText = text.trim()
    if (!normalizedText || !visitId) {
      onNotice('请先填写现场速记内容。', 'error')
      return
    }
    try {
      setSaving(true)
      if (!forceNew && !clientKey) {
        const duplicates = await api.previewVisitRecordDuplicates(visitId, normalizedText)
        if (duplicates.items.length > 0) {
          setDuplicateCandidates(duplicates.items)
          return
        }
      }
      const stableClientKey = clientKey || makeBrowserDraftId('quick-note')
      setClientKey(stableClientKey)
      const response = await api.createVisitRecord(visitId, {
        text: normalizedText,
        created_by: state.visit.cra_name || '演示 CRA',
        linked_task_id: linkedTaskId,
        client_created_at: new Date().toISOString(),
        client_timezone: currentClientTimezone(),
        tags: tags.split(/[,，;；\n\r]+/).map((item) => item.trim()).filter(Boolean),
        client_idempotency_key: stableClientKey,
      })
      onStateChange(response.workspace)
      resetComposer()
      onNotice(response.idempotent_reuse ? '已恢复此前保存的现场记录，未重复写入。' : '现场速记已保存，已进入 CRA 建议确认流程。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '现场速记保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  const storeOffline = async () => {
    const normalizedText = text.trim()
    if (!normalizedText || !visitId) {
      onNotice('请先填写需要离线暂存的速记内容。', 'error')
      return
    }
    const next = [{
      id: makeBrowserDraftId('quick-draft'),
      client_id: getBrowserClientId(),
      text: normalizedText,
      base_updated_at: state.visit.sync_token ?? state.visit.updated_at ?? '',
      created_at: new Date().toLocaleString('zh-CN', { hour12: false }),
    }, ...drafts]
    await updateDrafts(next)
    resetComposer()
    onNotice('速记已加密暂存到本机离线草稿。')
  }

  const syncDraft = async (draft: BrowserDraft) => {
    if (!visitId) return
    try {
      setSyncingDraftId(draft.id)
      const result = await api.syncOfflineDraft(visitId, {
        client_id: draft.client_id,
        payload: { text: draft.text },
        base_updated_at: draft.base_updated_at,
        actor_name: state.visit.cra_name || '演示 CRA',
      })
      await updateDrafts(drafts.filter((item) => item.id !== draft.id))
      if (result.status === 'synced') {
        onStateChange(await api.getState(visitId))
        onNotice('离线速记已同步并进入 CRA 建议确认流程。')
      } else {
        onNotice('服务器已有后续更新，已创建同步冲突待办，请在监查工作台处理。', 'error')
      }
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '离线速记同步失败；本机草稿仍保留。', 'error')
    } finally {
      setSyncingDraftId(null)
    }
  }

  const selectedTask = allTasks.find((item) => item.id === linkedTaskId)
  const recentRecords = state.records.slice(0, 3)

  return (
    <div className="quick-note-stack">
      <section className="section-block quick-note-brief">
        <div>
          <p className="eyebrow">FIELD QUICK NOTE</p>
          <h2>现场速记</h2>
          <p>适合在访视间隙快速留下可追溯的工作底稿；完整任务结论和建议确认仍在监查工作台完成。</p>
        </div>
        <dl className="quick-note-facts">
          <div><dt>当前 CRA</dt><dd>{state.visit.cra_name}</dd></div>
          <div><dt>待同步</dt><dd>{drafts.length}</dd></div>
        </dl>
      </section>

      {!canEdit && <section className="section-block quick-note-readonly"><strong>当前速记入口为只读</strong><span>{reportLocked ? '报告已提交审核或批准，不能继续写入工作底稿。' : '请切换到 CRA 演示角色后再保存现场速记。'}</span></section>}

      <section className="section-block quick-note-composer">
        <div className="section-header compact-header">
          <div><h2>记录当前发现</h2><p>先保存原文，再由既有整理流程生成待确认建议；没有证据时不会补写事实。</p></div>
          <span className="section-code">NOTE</span>
        </div>
        <div className="quick-note-body">
          <textarea value={text} disabled={!canEdit} onChange={(event) => { setText(event.target.value); setDuplicateCandidates([]) }} placeholder="例如：抽查 8 例知情同意书，受试者 102-003 签署时使用旧版 ICF；中心说明文件替换当日未及时归档。" aria-label="现场速记内容" />
          <div className="quick-note-context">
            <label>关联任务（可选）<select value={linkedTaskId} disabled={!canEdit} onChange={(event) => setLinkedTaskId(event.target.value)}><option value="">不关联，由系统建议归类</option>{allTasks.map((task) => <option key={task.id} value={task.id}>{taskLabel(task)}</option>)}</select></label>
            <label>标签（可选）<input value={tags} disabled={!canEdit} onChange={(event) => setTags(event.target.value)} placeholder="例如：ICF、现场、待跟进" /></label>
          </div>
          <div className="quick-note-footer"><span>{selectedTask ? `本条将关联：${taskLabel(selectedTask)}` : '可直接记录，后续在监查工作台确认归类与结论。'}</span><div><button type="button" className="button quiet" disabled={!canEdit || !text.trim()} onClick={() => void storeOffline()}>暂存离线</button><button type="button" className="button primary" disabled={!canEdit || saving || !text.trim()} onClick={() => void saveRecord()}>{saving ? '正在保存…' : '保存并整理'}</button></div></div>
          <p className="quick-note-offline-hint">离线暂存仅保留速记原文；如需保留关联任务或标签，请恢复网络后使用“保存并整理”。</p>
        </div>
      </section>

      {duplicateCandidates.length > 0 && <section className="section-block quick-note-duplicate">
        <div className="section-header compact-header"><div><h2>发现疑似重复记录</h2><p>系统只提示，不会自动合并或丢弃。请由 CRA 决定是否另存为新记录。</p></div><span className="section-code">CRA DECISION</span></div>
        <div className="quick-note-duplicate-list">{duplicateCandidates.map((record) => <article key={record.id}><strong>{record.created_at} · {record.created_by || 'CRA'}</strong><p>{record.text}</p></article>)}</div>
        <div className="quick-note-duplicate-actions"><span>返回修改不会写入任何新记录。</span><div><button type="button" className="button quiet" disabled={saving} onClick={() => setDuplicateCandidates([])}>返回修改</button><button type="button" className="button secondary" disabled={saving || !canEdit} onClick={() => void saveRecord(true)}>仍保存为新记录</button></div></div>
      </section>}

      <section className="section-block quick-note-drafts">
        <div className="section-header compact-header"><div><h2>离线速记</h2><p>此处与监查工作台共享同一浏览器草稿队列；发生冲突时请回到工作台选择保留版本。</p></div><span className={`connection-indicator ${online ? 'is-online' : 'is-offline'}`}>{online ? '网络可用' : '离线中'}</span></div>
        {drafts.length === 0 ? <div className="empty-state inline"><span>当前没有待同步的离线速记。</span></div> : <div className="quick-note-draft-list">{drafts.map((draft) => <article key={draft.id}><div><span className="draft-status">本机草稿</span><p>{draft.text}</p><small>暂存时间：{displayDraftTime(draft.created_at)}</small></div><button type="button" className="button secondary small" disabled={syncingDraftId === draft.id} onClick={() => void syncDraft(draft)}>{syncingDraftId === draft.id ? '正在同步…' : '同步到工作区'}</button></article>)}</div>}
      </section>

      <section className="section-block quick-note-recent">
        <div className="section-header compact-header"><div><h2>最近速记</h2><p>最近三条工作记录摘要，便于确认刚才的现场输入已留存。</p></div><span className="section-code">RECENT</span></div>
        {recentRecords.length === 0 ? <div className="empty-state inline"><span>尚无现场记录。</span></div> : <div className="quick-note-recent-list">{recentRecords.map((record) => <article key={record.id}><time>{record.created_at}</time><div><p>{record.text}</p><small>{record.tags?.length ? `标签：${record.tags.join(' · ')}` : record.record_kind === 'center_explanation' ? '中心解释（独立留存）' : 'CRA 监查记录'}</small></div></article>)}</div>}
      </section>
    </div>
  )
}
