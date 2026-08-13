import { useEffect, useState } from 'react'
import { api } from '../api'
import { clearOfflineDraftQueue, clearOfflineEncryptionKey, getBrowserClientId, makeBrowserDraftId, readOfflineDraftQueue, type BrowserDraft, writeOfflineDraftQueue } from '../offlineDraftStorage'
import type { DemoState, SyncConflict } from '../types'

interface OfflineDraftsPanelProps {
  state: DemoState
  draftText: string
  onDraftStored: () => void
  onStateChange: (state: DemoState) => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

export function OfflineDraftsPanel({ state, draftText, onDraftStored, onStateChange, onNotice }: OfflineDraftsPanelProps) {
  const visitId = state.visit.id ?? ''
  const [localDrafts, setLocalDrafts] = useState<BrowserDraft[]>([])
  const [conflicts, setConflicts] = useState<SyncConflict[]>([])
  const [online, setOnline] = useState(() => navigator.onLine)
  const [busyId, setBusyId] = useState<string | null>(null)

  const refreshRemote = async () => {
    if (!visitId) return
    const remote = await api.getOfflineDrafts(visitId)
    setConflicts(remote.conflicts.filter((item) => item.status === 'open'))
  }

  useEffect(() => {
    let cancelled = false
    void readOfflineDraftQueue(visitId).then((items) => {
      if (!cancelled) setLocalDrafts(items)
    })
    void refreshRemote().catch(() => undefined)
    const updateOnline = () => setOnline(navigator.onLine)
    window.addEventListener('online', updateOnline)
    window.addEventListener('offline', updateOnline)
    return () => {
      cancelled = true
      window.removeEventListener('online', updateOnline)
      window.removeEventListener('offline', updateOnline)
    }
  }, [visitId])

  const storeLocal = async () => {
    const text = draftText.trim()
    if (!text || !visitId) {
      onNotice('请先在“现场记录”中写入需要暂存的内容。', 'error')
      return
    }
    const next = [
      {
        id: makeBrowserDraftId('draft'),
        client_id: getBrowserClientId(),
        text,
        base_updated_at: state.visit.sync_token ?? state.visit.updated_at ?? '',
        created_at: new Date().toLocaleString('zh-CN', { hour12: false }),
      },
      ...localDrafts,
    ]
    await writeOfflineDraftQueue(visitId, next)
    setLocalDrafts(next)
    onDraftStored()
    onNotice('已加密暂存到本机离线草稿；即使刷新页面也会保留。')
  }

  const syncDraft = async (draft: BrowserDraft) => {
    if (!visitId) return
    try {
      setBusyId(draft.id)
      const result = await api.syncOfflineDraft(visitId, {
        client_id: draft.client_id,
        payload: { text: draft.text },
        base_updated_at: draft.base_updated_at,
        actor_name: state.visit.cra_name,
      })
      const remaining = localDrafts.filter((item) => item.id !== draft.id)
      await writeOfflineDraftQueue(visitId, remaining)
      setLocalDrafts(remaining)
      await refreshRemote()
      if (result.status === 'synced') {
        onStateChange(await api.getState(visitId))
        onNotice('离线草稿已同步，并进入 CRA 建议确认流程。')
      } else {
        onNotice('服务器存在后续更新，已建立同步冲突待办，请选择保留方式。', 'error')
      }
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '离线草稿同步失败；本机草稿仍保留。', 'error')
    } finally {
      setBusyId(null)
    }
  }

  const controlledClear = () => {
    clearOfflineDraftQueue(visitId)
    clearOfflineEncryptionKey()
    setLocalDrafts([])
    onNotice('已受控清除本机加密离线草稿，权限撤销或更换设备后不可再读取。')
  }

  const resolveConflict = async (conflict: SyncConflict, resolution: 'local' | 'server') => {
    if (!visitId) return
    try {
      setBusyId(conflict.id)
      await api.resolveSyncConflict(visitId, conflict.id, resolution, state.visit.cra_name)
      await refreshRemote()
      onStateChange(await api.getState(visitId))
      onNotice(resolution === 'local' ? '已保留本机记录，并重新进入建议确认流程。' : '已保留服务器状态，本机冲突草稿不再写入工作区。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '同步冲突处理失败', 'error')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="section-block offline-drafts-panel">
      <div className="section-header">
        <div>
          <h2>离线草稿与同步</h2>
          <p>碎片记录可先留在本机；恢复联网后由 CRA 主动同步，发现同一工作区已有更新时会进入明确的冲突待办。</p>
        </div>
        <span className={`connection-indicator ${online ? 'is-online' : 'is-offline'}`}>{online ? '网络可用' : '离线中'}</span>
      </div>

      <div className="offline-store-row">
        <div><strong>当前现场记录</strong><span>{draftText.trim() ? `${draftText.trim().length} 字待暂存` : '尚未输入内容'}</span></div>
        <button type="button" className="button quiet" onClick={() => void storeLocal()} disabled={!draftText.trim() || !visitId}>暂存至本机离线草稿</button>
      </div>

      {localDrafts.length === 0 ? <div className="empty-state inline"><span>当前浏览器没有待同步草稿。</span></div> : (
        <div className="offline-draft-list">
          {localDrafts.map((draft) => <article className="offline-draft-row" key={draft.id}>
            <div><span className="draft-status">本机加密草稿</span><p>{draft.text}</p><small>暂存时间：{draft.created_at}</small></div>
            <button type="button" className="button secondary small" disabled={busyId === draft.id} onClick={() => void syncDraft(draft)}>{busyId === draft.id ? '正在同步…' : '同步到工作区'}</button>
          </article>)}
          <button type="button" className="button quiet small controlled-clear" onClick={controlledClear}>受控清除本机全部离线草稿</button>
        </div>
      )}

      {conflicts.length > 0 && <div className="sync-conflict-list">
        <div className="subsection-caption"><strong>同步冲突待办</strong><span>{conflicts.length} 项需要 CRA 选择</span></div>
        {conflicts.map((conflict) => <article className="sync-conflict-row" key={conflict.id}>
          <div className="conflict-copy"><strong>本机记录</strong><p>{conflict.local_value}</p><strong>服务器状态</strong><p>{conflict.server_value}</p></div>
          <div className="conflict-actions">
            <button type="button" className="button primary small" disabled={busyId === conflict.id} onClick={() => void resolveConflict(conflict, 'local')}>保留本机记录</button>
            <button type="button" className="button quiet small" disabled={busyId === conflict.id} onClick={() => void resolveConflict(conflict, 'server')}>保留服务器状态</button>
          </div>
        </article>)}
      </div>}
    </section>
  )
}
