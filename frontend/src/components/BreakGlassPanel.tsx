import { useEffect, useState } from 'react'
import { api } from '../api'
import type { BreakGlassRequest, DemoState } from '../types'

interface BreakGlassPanelProps {
  state: DemoState
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

const statusLabel: Record<BreakGlassRequest['status'], string> = {
  pending_business_approval: '待业务审批',
  pending_security_approval: '待安全审批',
  active: '生效中',
  ended: '已结束',
}

export function BreakGlassPanel({ state, onNotice }: BreakGlassPanelProps) {
  const projectId = state.visit.project_id ?? ''
  const role = state.current_role
  const isSystemAdmin = role === 'SYSTEM_ADMIN'
  const isBusinessApprover = role === 'PROJECT_ADMIN' || role === 'QA_CLINICAL_OPS'
  const canRequest = role !== 'SYSTEM_ADMIN'

  const [items, setItems] = useState<BreakGlassRequest[]>([])
  const [busyId, setBusyId] = useState<string | null>(null)
  const [draft, setDraft] = useState({ object_scope: '', purpose: '', max_duration_minutes: '60', emergency: false })
  const [endReason, setEndReason] = useState<Record<string, string>>({})
  const [reviewNote, setReviewNote] = useState<Record<string, string>>({})

  const refresh = async () => {
    if (!projectId) return
    try {
      const result = await api.listBreakGlassRequests(projectId)
      setItems(result.items)
    } catch {
      // Break-glass visibility itself is access-controlled; a 403 here just means
      // the current identity (e.g. system admin without an active grant) can't see it.
      setItems([])
    }
  }

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, role])

  const createRequest = async () => {
    if (!projectId || !draft.purpose.trim()) {
      onNotice('请填写破窗访问目的。', 'error')
      return
    }
    try {
      setBusyId('create')
      await api.createBreakGlassRequest({
        project_id: projectId,
        object_scope: draft.object_scope,
        purpose: draft.purpose,
        max_duration_minutes: Number(draft.max_duration_minutes) || 60,
        emergency_self_activate: draft.emergency,
      })
      setDraft({ object_scope: '', purpose: '', max_duration_minutes: '60', emergency: false })
      await refresh()
      onNotice(draft.emergency ? '已按应急 SOP 自激活破窗访问，需在时限内完成双人复核。' : '破窗访问申请已提交，等待业务审批。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '破窗访问申请失败', 'error')
    } finally {
      setBusyId(null)
    }
  }

  const businessApprove = async (item: BreakGlassRequest) => {
    try {
      setBusyId(item.id)
      await api.approveBreakGlassBusiness(item.id)
      await refresh()
      onNotice('已完成业务审批，等待安全审批（系统管理员）。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '业务审批失败', 'error')
    } finally {
      setBusyId(null)
    }
  }

  const securityApprove = async (item: BreakGlassRequest) => {
    try {
      setBusyId(item.id)
      await api.approveBreakGlassSecurity(item.id)
      await refresh()
      onNotice('已完成安全审批，破窗访问已生效并进入独立审计。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '安全审批失败', 'error')
    } finally {
      setBusyId(null)
    }
  }

  const endRequest = async (item: BreakGlassRequest) => {
    const reason = endReason[item.id] ?? ''
    if (!reason.trim()) {
      onNotice('请先填写提前结束原因。', 'error')
      return
    }
    try {
      setBusyId(item.id)
      await api.endBreakGlass(item.id, reason)
      setEndReason((current) => ({ ...current, [item.id]: '' }))
      await refresh()
      onNotice('已提前结束破窗访问。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '结束破窗访问失败', 'error')
    } finally {
      setBusyId(null)
    }
  }

  const review = async (item: BreakGlassRequest) => {
    const note = reviewNote[item.id] ?? ''
    if (!note.trim()) {
      onNotice('请先填写复核结论。', 'error')
      return
    }
    try {
      setBusyId(item.id)
      await api.reviewBreakGlass(item.id, note)
      setReviewNote((current) => ({ ...current, [item.id]: '' }))
      await refresh()
      onNotice('已完成破窗访问复核。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '复核失败', 'error')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="section-block break-glass-panel">
      <div className="section-header">
        <div>
          <h2>破窗访问</h2>
          <p>系统管理员默认不能查看临床内容；紧急访问需业务数据负责人与安全（系统管理员）双人审批、限时限项目，并自动进入独立审计与时限内复核。</p>
        </div>
        <span className="section-code">BREAK GLASS</span>
      </div>

      {canRequest && <form className="break-glass-request-form" onSubmit={(event) => { event.preventDefault(); void createRequest() }}>
        <label>访问范围<input value={draft.object_scope} onChange={(event) => setDraft({ ...draft, object_scope: event.target.value })} placeholder="例如：本项目 2026-08 报告生成异常排查" /></label>
        <label>目的（必填）<textarea required value={draft.purpose} onChange={(event) => setDraft({ ...draft, purpose: event.target.value })} placeholder="说明为何需要系统管理员临时访问本项目临床内容" /></label>
        <label>时效（分钟）<input type="number" min={1} max={1440} value={draft.max_duration_minutes} onChange={(event) => setDraft({ ...draft, max_duration_minutes: event.target.value })} /></label>
        <label className="break-glass-emergency"><input type="checkbox" checked={draft.emergency} onChange={(event) => setDraft({ ...draft, emergency: event.target.checked })} />按客户批准的生命安全应急 SOP 自激活（跳过预先双人审批，但强制事后双人复核）</label>
        <button type="submit" className="button primary" disabled={busyId === 'create'}>提交破窗访问申请</button>
      </form>}

      <div className="break-glass-list">
        {items.length === 0 ? <div className="empty-state inline"><span>{isSystemAdmin ? '当前没有已授权本身份的破窗访问记录。' : '当前项目暂无破窗访问申请。'}</span></div> : items.map((item) => (
          <article className={`break-glass-row status-${item.status}`} key={item.id}>
            <div className="break-glass-heading">
              <strong>{item.purpose}</strong>
              <span className={`break-glass-status ${item.status}`}>{statusLabel[item.status]}{item.is_expired ? '（已超时）' : ''}</span>
            </div>
            <small>申请人：{item.requested_by}（{item.requested_by_role}） · {item.created_at} · 范围：{item.object_scope || '未填写'}</small>
            {item.emergency_self_activated === 1 && <p className="break-glass-emergency-note">应急自激活，须完成事后双人复核</p>}
            {item.business_approver && <p>业务审批：{item.business_approver} · {item.business_approved_at}</p>}
            {item.security_approver && <p>安全审批：{item.security_approver} · {item.security_approved_at}</p>}
            {item.status === 'active' && <p>生效时段：{item.activated_at} ～ {item.expires_at}</p>}
            {item.ended_at && <p>已结束：{item.ended_at} · 原因：{item.ended_reason}</p>}
            {item.review_status === 'completed' && <p>复核：{item.reviewed_by} · {item.reviewed_at} · {item.review_note}</p>}

            {item.status === 'pending_business_approval' && isBusinessApprover && <button type="button" className="button secondary small" disabled={busyId === item.id} onClick={() => void businessApprove(item)}>业务审批通过</button>}
            {item.status === 'pending_security_approval' && isSystemAdmin && <button type="button" className="button secondary small" disabled={busyId === item.id} onClick={() => void securityApprove(item)}>安全审批通过并激活</button>}
            {item.status === 'active' && (isBusinessApprover || isSystemAdmin) && <div className="break-glass-end-row">
              <input value={endReason[item.id] ?? ''} onChange={(event) => setEndReason({ ...endReason, [item.id]: event.target.value })} placeholder="提前结束原因" />
              <button type="button" className="button quiet small" disabled={busyId === item.id} onClick={() => void endRequest(item)}>提前结束</button>
            </div>}
            {item.review_status === 'pending' && isBusinessApprover && <div className="break-glass-review-row">
              <input value={reviewNote[item.id] ?? ''} onChange={(event) => setReviewNote({ ...reviewNote, [item.id]: event.target.value })} placeholder="复核结论：操作范围与目的是否一致" />
              <button type="button" className="button quiet small" disabled={busyId === item.id} onClick={() => void review(item)}>提交复核</button>
            </div>}
          </article>
        ))}
      </div>
    </section>
  )
}
