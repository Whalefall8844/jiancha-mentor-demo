import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../api'
import type { DemoState, OperationEscalation, UserRole, VisitHandover, VisitOperations } from '../types'

interface CollaborationPageProps {
  state: DemoState
  onStateChange: (state: DemoState) => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

const roleLabels: Record<UserRole, string> = {
  CRA: 'CRA',
  PM_LM: 'PM / LM',
  PROJECT_ADMIN: '项目管理员',
  QA_CLINICAL_OPS: 'QA / 临床运营审批人',
  MEDICAL_DATA_REVIEWER: '医学监察 / 数据管理',
}

const taskScopeLabel = (task: { task_type?: string; table_index: number }) => task.task_type === 'system_device_check' ? '系统／设备' : `表 ${task.table_index}`

const auditDetailLabels: Record<string, string> = {
  version: '报告版本',
  version_number: '报告版本',
  reason: '原因',
  status_transition: '状态转换',
  working_revision_id: '关联工作修订 ID',
  working_version: '关联工作修订',
  parent_revision_id: '上级修订 ID',
  target_key: '定位对象',
  action_item_id: '关联行动项 ID',
  resolution_note: '处置决定',
  acknowledgement_note: '接收说明',
  previous_status: '变更前状态',
  severity: '升级级别',
  target_role: '目标角色',
  requested_target_role: '请求目标角色',
  previous_target_role: '转送前目标角色',
  sla_due_at: 'SLA 接收截止时间',
  sla_snapshot: '冻结 SLA 配置',
  acknowledged_at: '接收时间',
  authorization_basis: '授权依据',
  handover_mode: '交接方式',
  from_member_id: '原负责成员',
  to_member_id: '接收成员',
  to_member_name: '接收 CRA',
  file_name: '文件名称',
  field_key: '字段标识',
}

const auditDetailValue = (value: unknown) => {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

const escalationStatusLabel: Record<OperationEscalation['status'], string> = {
  open: '待接收',
  acknowledged: '已接收',
  closed: '已处置',
}

const escalationTargetLabel = (role: OperationEscalation['target_role'] | '') => role === 'PROJECT_ADMIN' ? '项目管理员' : role === 'PM_LM' ? 'PM / LM' : '未指定'

const escalationSlaLabel = (item: OperationEscalation) => {
  if (!item.sla.configured) return '未配置项目 SLA：保留人工升级待办，不套用通用时限。'
  if (item.sla.receipt_state === 'overdue_escalated') return `已逾期并在系统内转送至 ${escalationTargetLabel(item.sla.overdue_target_role)}。`
  if (item.sla.receipt_state === 'acknowledged_within_sla') return '已在 SLA 内完成接收。'
  if (item.sla.receipt_state === 'acknowledged_late') return '已超期接收；原截止时间已保留。'
  const minutes = item.sla.remaining_minutes ?? 0
  return `接收截止：${item.sla.due_at}（剩余 ${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟）`
}

const handoverModeLabel: Record<VisitHandover['handover_mode'], string> = {
  cra_initiated: 'CRA 主动交接',
  administrator_authorized: '管理员授权交接',
}

const handoverStatusLabel: Record<VisitHandover['status'], string> = {
  completed: '已完成',
  pending_recipient_confirmation: '待接收 CRA 复核',
}

export function CollaborationPage({ state, onStateChange, onNotice }: CollaborationPageProps) {
  const visitId = state.visit.id ?? ''
  const projectId = state.visit.project_id ?? ''
  const [operations, setOperations] = useState<VisitOperations | null>(null)
  const [busy, setBusy] = useState(false)
  const [memberDraft, setMemberDraft] = useState<{ display_name: string; role: UserRole }>({ display_name: '', role: 'CRA' })
  const [handoverDraft, setHandoverDraft] = useState({ to_member_id: '', note: '' })
  const [administratorHandoverDraft, setAdministratorHandoverDraft] = useState({ from_member_id: '', to_member_id: '', reason: '', authorization_basis: '', note: '' })
  const [handoverAcknowledgements, setHandoverAcknowledgements] = useState<Record<string, string>>({})
  const [escalationDraft, setEscalationDraft] = useState({ action_item_id: '', severity: 'high' as 'high' | 'urgent' })
  const [escalationNotes, setEscalationNotes] = useState<Record<string, string>>({})
  const [selectedTaskIds, setSelectedTaskIds] = useState<string[]>([])
  const [batchEvidence, setBatchEvidence] = useState('')
  const [showAllAuditEvents, setShowAllAuditEvents] = useState(false)
  const isCRA = state.current_role === 'CRA'
  const isPMLM = state.current_role === 'PM_LM'
  const isProjectAdmin = state.current_role === 'PROJECT_ADMIN'

  const refresh = async () => {
    if (!visitId) return
    const nextOperations = await api.getVisitOperations(visitId)
    const nextState = await api.getState(visitId)
    setOperations(nextOperations)
    onStateChange(nextState)
  }

  useEffect(() => { void refresh().catch(() => undefined) }, [visitId])

  const changeRole = async (role: UserRole) => {
    try {
      setBusy(true)
      await api.updateCurrentRole(role)
      await refresh()
      onNotice(`当前演示角色已切换为 ${roleLabels[role]}。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '角色切换失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const createMember = async (event: FormEvent) => {
    event.preventDefault()
    if (!projectId || !isProjectAdmin) return
    try {
      setBusy(true)
      await api.createProjectMember(projectId, memberDraft)
      setMemberDraft({ display_name: '', role: 'CRA' })
      await refresh()
      onNotice('已添加项目成员。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '添加项目成员失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const toggleMemberStatus = async (memberId: string, status: 'active' | 'inactive') => {
    if (!projectId || !isProjectAdmin) return
    try {
      setBusy(true)
      await api.updateProjectMember(projectId, memberId, { status })
      await refresh()
      onNotice(status === 'inactive' ? '成员已停用；其历史操作与归属保持可追溯。' : '成员已恢复为有效项目成员。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '更新成员状态失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const createHandover = async (event: FormEvent) => {
    event.preventDefault()
    if (!isCRA) {
      onNotice('CRA 交接由当前负责 CRA 发起。', 'error')
      return
    }
    if (!visitId || !handoverDraft.to_member_id) {
      onNotice('请选择接收本次访视的 CRA。', 'error')
      return
    }
    try {
      setBusy(true)
      const origin = state.project_members.find((member) => member.display_name === state.visit.cra_name && member.role === 'CRA')
      await api.createHandover(visitId, { from_member_id: origin?.id, ...handoverDraft, actor_name: state.visit.cra_name })
      setHandoverDraft({ to_member_id: '', note: '' })
      await refresh()
      onNotice('本次访视已完成 CRA 交接，后续记录将显示新的负责 CRA。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '访视交接失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const createAdministratorHandover = async (event: FormEvent) => {
    event.preventDefault()
    if (!isProjectAdmin) {
      onNotice('管理员授权交接仅由项目管理员发起。', 'error')
      return
    }
    if (!visitId || !administratorHandoverDraft.from_member_id || !administratorHandoverDraft.to_member_id) {
      onNotice('请选择原负责 CRA 与接收 CRA。', 'error')
      return
    }
    try {
      setBusy(true)
      await api.createAdministratorHandover(visitId, { ...administratorHandoverDraft, actor_name: '项目管理员' })
      setAdministratorHandoverDraft({ from_member_id: '', to_member_id: '', reason: '', authorization_basis: '', note: '' })
      await refresh()
      onNotice('已依据授权完成责任交接，接收 CRA 需要在协作台账中完成重新核对。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '管理员授权交接失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const acknowledgeAdministratorHandover = async (item: VisitHandover) => {
    if (!visitId) return
    const acknowledgementNote = handoverAcknowledgements[item.id] ?? ''
    if (!acknowledgementNote.trim()) {
      onNotice('请填写重新核对说明后再确认接收。', 'error')
      return
    }
    try {
      setBusy(true)
      await api.acknowledgeAdministratorHandover(visitId, item.id, {
        acknowledgement_note: acknowledgementNote,
        actor_name: state.visit.cra_name,
      })
      setHandoverAcknowledgements((current) => ({ ...current, [item.id]: '' }))
      await refresh()
      onNotice('已记录接收 CRA 的重新核对确认。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '确认管理员交接失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const createEscalation = async (event: FormEvent) => {
    event.preventDefault()
    if (!isCRA) {
      onNotice('人工升级待办由 CRA 从监查工作区发起。', 'error')
      return
    }
    if (!visitId || !escalationDraft.action_item_id) {
      onNotice('请选择需要人工升级的开放行动项。', 'error')
      return
    }
    try {
      setBusy(true)
      const created = await api.createEscalation(visitId, { ...escalationDraft, actor_name: state.visit.cra_name, target_role: 'PM_LM' })
      setEscalationDraft({ action_item_id: '', severity: 'high' })
      await refresh()
      onNotice(created.sla.configured ? `已按规则包创建升级待办，目标：${escalationTargetLabel(created.target_role)}；接收截止：${created.sla_due_at}。` : `已创建人工升级待办，目标：${escalationTargetLabel(created.target_role)}；该访视未配置 SLA。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '创建升级待办失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const disposeEscalation = async (item: OperationEscalation, action: 'acknowledge' | 'close') => {
    if (!visitId) return
    const actorRole = item.target_role === 'PROJECT_ADMIN' ? 'PROJECT_ADMIN' : 'PM_LM'
    const actorName = state.project_members.find((member) => member.role === actorRole && member.status === 'active')?.display_name || escalationTargetLabel(actorRole)
    try {
      setBusy(true)
      await api.disposeEscalation(visitId, item.id, {
        action,
        note: escalationNotes[item.id] ?? '',
        actor_name: actorName,
      })
      setEscalationNotes((current) => ({ ...current, [item.id]: '' }))
      await refresh()
      onNotice(action === 'acknowledge' ? `已确认接收升级待办“${item.title}”。` : `已记录处置决定并关闭“${item.title}”。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '升级待办处置失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const toggleTask = (taskId: string) => {
    setSelectedTaskIds((current) => current.includes(taskId) ? current.filter((id) => id !== taskId) : [...current, taskId])
  }

  const batchComplete = async () => {
    if (!isCRA) {
      onNotice('批量补录由 CRA 完成。', 'error')
      return
    }
    if (!visitId || selectedTaskIds.length === 0) {
      onNotice('请先选择需要集中补录的任务区域。', 'error')
      return
    }
    try {
      setBusy(true)
      const result = await api.bulkUpdateTasks(visitId, {
        task_ids: selectedTaskIds,
        status: '已检查',
        evidence: batchEvidence || 'CRA 已集中补录本次检查结果。',
        actor_name: state.visit.cra_name,
      })
      setSelectedTaskIds([])
      setBatchEvidence('')
      setOperations(await api.getVisitOperations(visitId))
      onStateChange(result.workspace)
      onNotice(`已批量更新 ${result.items.length} 项监查任务。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '批量更新任务失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const craMembers = state.project_members.filter((member) => member.role === 'CRA' && member.status === 'active')
  const allCraMembers = state.project_members.filter((member) => member.role === 'CRA')
  const currentResponsibleCraMembers = allCraMembers.filter((member) => member.display_name === state.visit.cra_name)
  const administratorOriginOptions = currentResponsibleCraMembers.length ? currentResponsibleCraMembers : allCraMembers
  const openActions = state.action_items.filter((item) => item.status !== 'closed')
  const activeEscalations = (operations?.escalations ?? []).filter((item) => item.status !== 'closed')
  const canHandleEscalation = (item: OperationEscalation) => (isPMLM && item.target_role === 'PM_LM') || (isProjectAdmin && item.target_role === 'PROJECT_ADMIN')
  const timeline = showAllAuditEvents ? state.audit_events : state.audit_events.slice(0, 12)

  return (
    <div className="collaboration-stack">
      <section className="section-block collaboration-brief">
        <div>
          <p className="eyebrow">CONTINUITY &amp; COLLABORATION</p>
          <h2>连续工作与协作中心</h2>
          <p>将离线草稿、待补录区域、行动项提醒、人工升级、CRA 交接和业务留痕放在同一访视工作区。</p>
        </div>
        <dl className="collaboration-stats">
          <div><dt>逾期行动项</dt><dd>{operations?.overdue_actions.length ?? '—'}</dd></div>
          <div><dt>待补录任务</dt><dd>{operations?.missing_tasks.length ?? '—'}</dd></div>
          <div><dt>升级待办</dt><dd>{operations ? activeEscalations.length : '—'}</dd></div>
        </dl>
      </section>

      <section className="section-block role-and-members">
        <div className="section-header">
          <div><h2>项目成员与当前角色</h2><p>此处模拟实际工作职责切换，不代表正式登录或电子签名。</p></div>
          <span className="section-code">TEAM</span>
        </div>
        <div className="role-switch-row">
          <label>当前演示角色<select value={state.current_role} disabled={busy} onChange={(event) => void changeRole(event.target.value as UserRole)}>{(Object.keys(roleLabels) as UserRole[]).map((role) => <option key={role} value={role}>{roleLabels[role]}</option>)}</select></label>
          <span>当前访视负责人：<strong>{state.visit.cra_name}</strong></span>
        </div>
        <div className="member-ledger">
          {state.project_members.map((member) => <div className="member-row" key={member.id}><strong>{member.display_name}</strong><span>{roleLabels[member.role]}</span><small>{member.status === 'active' ? '有效成员' : '已停用'}</small>{isProjectAdmin && <button type="button" className="member-status-button" disabled={busy} onClick={() => void toggleMemberStatus(member.id, member.status === 'active' ? 'inactive' : 'active')}>{member.status === 'active' ? '停用成员' : '恢复成员'}</button>}</div>)}
        </div>
        {isProjectAdmin ? <form className="member-create-form" onSubmit={createMember}>
          <label>新增内部成员<input required value={memberDraft.display_name} onChange={(event) => setMemberDraft({ ...memberDraft, display_name: event.target.value })} placeholder="例如：王 CRA" /></label>
          <label>角色<select value={memberDraft.role} onChange={(event) => setMemberDraft({ ...memberDraft, role: event.target.value as UserRole })}>{(Object.keys(roleLabels) as UserRole[]).map((role) => <option key={role} value={role}>{roleLabels[role]}</option>)}</select></label>
          <button type="submit" className="button quiet" disabled={busy}>添加成员</button>
        </form> : <div className="role-readonly-banner">成员维护由项目管理员完成；当前角色可查看团队台账与负责 CRA。</div>}
      </section>

      <div className="collaboration-grid">
        <section className="section-block operations-panel">
          <div className="section-header compact-header"><div><h2>提醒与人工升级</h2><p>演示环境按行动项计划完成日即时计算，不依赖后台定时任务。</p></div></div>
          <div className="alert-groups">
            <div className="alert-group overdue"><strong>逾期（{operations?.overdue_actions.length ?? 0}）</strong>{operations?.overdue_actions.length ? operations.overdue_actions.map((action) => <p key={action.id}>{action.title}<small>计划完成：{action.due_date}</small></p>) : <span>暂无逾期行动项</span>}</div>
            <div className="alert-group due-soon"><strong>临期（{operations?.due_soon_actions.length ?? 0}）</strong>{operations?.due_soon_actions.length ? operations.due_soon_actions.map((action) => <p key={action.id}>{action.title}<small>计划完成：{action.due_date}</small></p>) : <span>未来 3 日暂无临期项</span>}</div>
          </div>
          {isCRA ? <form className="escalation-form" onSubmit={createEscalation}>
            <label>选择开放行动项<select value={escalationDraft.action_item_id} onChange={(event) => setEscalationDraft({ ...escalationDraft, action_item_id: event.target.value })}><option value="">请选择</option>{openActions.map((action) => <option key={action.id} value={action.id}>{action.title}</option>)}</select></label>
            <label>升级级别<select value={escalationDraft.severity} onChange={(event) => setEscalationDraft({ ...escalationDraft, severity: event.target.value as 'high' | 'urgent' })}><option value="high">高优先级</option><option value="urgent">紧急</option></select></label>
            <button type="submit" className="button secondary" disabled={busy || openActions.length === 0}>按规则包创建升级待办</button>
          </form> : <div className="role-readonly-banner">当前角色可查看提醒和升级待办；由 CRA 发起新的人工升级。</div>}
          <div className="escalation-list">{operations?.escalations.length ? operations.escalations.map((item) => <article key={item.id} className={`escalation-row status-${item.status}`}><span className={`escalation-severity ${item.severity}`}>{item.severity === 'urgent' ? '紧急' : '高'}</span><div><div className="escalation-heading"><strong>{item.title}</strong><span className={`escalation-status ${item.status}`}>{escalationStatusLabel[item.status]}</span></div><p>{item.description}</p><small>当前目标：{escalationTargetLabel(item.target_role)} · 发起：{item.created_at}</small><p className={`escalation-sla state-${item.sla.state}`}><strong>项目 SLA</strong>{escalationSlaLabel(item)}</p>{item.status !== 'open' && <small>接收：{item.acknowledged_by || escalationTargetLabel(item.target_role)} · {item.acknowledged_at || '时间未记录'}</small>}{item.acknowledgement_note && <p className="escalation-note">接收说明：{item.acknowledgement_note}</p>}{item.status === 'closed' && <><small>处置：{item.closed_by || escalationTargetLabel(item.target_role)} · {item.closed_at || '时间未记录'}</small><p className="escalation-resolution">处置决定：{item.resolution_note || '未填写补充说明'}</p></>}{canHandleEscalation(item) && item.status === 'open' && <div className="escalation-disposition"><label>接收说明（可选）<input value={escalationNotes[item.id] ?? ''} onChange={(event) => setEscalationNotes((current) => ({ ...current, [item.id]: event.target.value }))} placeholder="例如：已接收，将按项目 SOP 协调处理。" /></label><button type="button" className="button quiet" disabled={busy} onClick={() => void disposeEscalation(item, 'acknowledge')}>确认接收</button></div>}{canHandleEscalation(item) && item.status === 'acknowledged' && <div className="escalation-disposition resolution"><label>处置决定<textarea value={escalationNotes[item.id] ?? ''} onChange={(event) => setEscalationNotes((current) => ({ ...current, [item.id]: event.target.value }))} placeholder="记录协调结果、后续责任人或按项目 SOP 完成的处理决定。" /></label><button type="button" className="button secondary" disabled={busy} onClick={() => void disposeEscalation(item, 'close')}>完成处置</button></div>}</div></article>) : <div className="empty-state inline"><span>暂无人工升级待办。</span></div>}</div>
        </section>

        <section className="section-block handover-panel">
          <div className="section-header compact-header"><div><h2>CRA 交接</h2><p>交接后当前访视负责人会更新为接收 CRA，原始记录和 Word 版本保持不变。</p></div></div>
          {isCRA ? <form className="handover-form" onSubmit={createHandover}>
            <label>接收 CRA<select required value={handoverDraft.to_member_id} onChange={(event) => setHandoverDraft({ ...handoverDraft, to_member_id: event.target.value })}><option value="">请选择</option>{craMembers.filter((member) => member.display_name !== state.visit.cra_name).map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
            <label>交接说明<textarea value={handoverDraft.note} onChange={(event) => setHandoverDraft({ ...handoverDraft, note: event.target.value })} placeholder="例如：请继续跟进已建立的 ICF 归档行动项。" /></label>
            <button type="submit" className="button primary" disabled={busy || craMembers.length < 2}>完成访视交接</button>
          </form> : isProjectAdmin ? <form className="handover-form administrator-handover-form" onSubmit={createAdministratorHandover}>
            <div className="handover-form-heading"><strong>管理员授权交接</strong><span>仅用于原 CRA 离职、长期缺席或项目重分配；接收 CRA 仍需重新核对并本人提交。</span></div>
            <label>原负责 CRA<select required value={administratorHandoverDraft.from_member_id} onChange={(event) => setAdministratorHandoverDraft({ ...administratorHandoverDraft, from_member_id: event.target.value })}><option value="">请选择</option>{administratorOriginOptions.map((member) => <option key={member.id} value={member.id}>{member.display_name}{member.status === 'inactive' ? '（已停用）' : ''}</option>)}</select></label>
            <label>接收 CRA<select required value={administratorHandoverDraft.to_member_id} onChange={(event) => setAdministratorHandoverDraft({ ...administratorHandoverDraft, to_member_id: event.target.value })}><option value="">请选择</option>{craMembers.filter((member) => member.id !== administratorHandoverDraft.from_member_id).map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
            <label>交接原因<textarea required value={administratorHandoverDraft.reason} onChange={(event) => setAdministratorHandoverDraft({ ...administratorHandoverDraft, reason: event.target.value })} placeholder="例如：原 CRA 离职，未提交工作需按项目安排转交。" /></label>
            <label>已批准的授权依据<textarea required value={administratorHandoverDraft.authorization_basis} onChange={(event) => setAdministratorHandoverDraft({ ...administratorHandoverDraft, authorization_basis: event.target.value })} placeholder="例如：项目授权单 PA-2026-018，批准日期 2026-08-12。" /></label>
            <label>补充说明（可选）<textarea value={administratorHandoverDraft.note} onChange={(event) => setAdministratorHandoverDraft({ ...administratorHandoverDraft, note: event.target.value })} placeholder="记录需要重点复核的未提交工作。" /></label>
            <button type="submit" className="button primary" disabled={busy || craMembers.length === 0}>依据授权完成交接</button>
          </form> : <div className="role-readonly-banner">当前角色可查看交接历史；只有当前负责 CRA 可以主动交接，离职或重分配场景由项目管理员依据授权处理。</div>}
          <div className="handover-list">{operations?.handovers.length ? operations.handovers.map((item) => <article key={item.id} className={`handover-row ${item.handover_mode} ${item.status}`}><div className="handover-heading"><strong>{item.from_member_name || '原负责 CRA'} → {item.to_member_name}</strong><span className={`handover-status ${item.status}`}>{handoverStatusLabel[item.status]}</span></div><small>{handoverModeLabel[item.handover_mode]} · {item.created_at}</small>{item.reason && <p>交接原因：{item.reason}</p>}{item.authorization_basis && <p className="handover-authority">授权依据：{item.authorization_basis}</p>}{item.note && <p>{item.note}</p>}{item.acknowledged_at && <p className="handover-confirmed">接收确认：{item.acknowledged_by || item.to_member_name} · {item.acknowledged_at}<br />{item.acknowledgement_note || '未填写确认说明'}</p>}{isCRA && item.handover_mode === 'administrator_authorized' && item.status === 'pending_recipient_confirmation' && item.to_member_name === state.visit.cra_name && <div className="handover-acknowledgement"><label>重新核对说明<textarea value={handoverAcknowledgements[item.id] ?? ''} onChange={(event) => setHandoverAcknowledgements((current) => ({ ...current, [item.id]: event.target.value }))} placeholder="例如：已重新核对当前工作记录、待处理行动项和报告状态，确认接收后续责任。" /></label><button type="button" className="button secondary" disabled={busy} onClick={() => void acknowledgeAdministratorHandover(item)}>确认已重新核对</button></div>}</article>) : <div className="empty-state inline"><span>暂无本访视的 CRA 交接记录。</span></div>}</div>
        </section>
      </div>

      <section className="section-block batch-task-panel">
        <div className="section-header"><div><h2>批量补录缺失任务</h2><p>选中多个尚未填写的报告区域后，以同一条检查说明集中更新；仍由 CRA 对实际检查结论负责。</p></div><span className="section-code">BATCH UPDATE</span></div>
        {operations?.missing_tasks.length ? <>
          <div className="missing-task-grid">{operations.missing_tasks.map((task) => <label className={`missing-task-option ${selectedTaskIds.includes(task.id) ? 'is-selected' : ''}`} key={task.id}><input type="checkbox" disabled={!isCRA} checked={selectedTaskIds.includes(task.id)} onChange={() => toggleTask(task.id)} /><span>{taskScopeLabel(task)}</span><strong>{task.title}</strong></label>)}</div>
          {isCRA ? <div className="batch-complete-row"><label>集中补录说明<input value={batchEvidence} onChange={(event) => setBatchEvidence(event.target.value)} placeholder="例如：CRA 已完成文件核查，未见需进一步跟进事项。" /></label><button type="button" className="button secondary" disabled={busy || selectedTaskIds.length === 0} onClick={() => void batchComplete()}>更新已选 {selectedTaskIds.length} 项</button></div> : <div className="role-readonly-banner">当前角色可查看缺失任务；实际检查状态由 CRA 批量或逐项更新。</div>}
        </> : <div className="empty-state"><strong>当前没有待补录任务</strong><span>所有模板区域均已完成映射、确认或检查状态更新。</span></div>}
      </section>

      <section className="section-block collaboration-timeline">
        <div className="section-header"><div><h2>访视业务时间线</h2><p>统一保留记录、建议、附件、行动项、报告、审核、同步、升级和交接动作；展开事件可查看系统已保存的原因、对象和版本详情。</p></div><span className="section-code">AUDIT TIMELINE</span></div>
        {timeline.length ? <><div className="timeline audit-timeline">{timeline.map((event) => {
          const detailEntries = Object.entries(event.detail ?? {})
          return <article className="timeline-item" key={event.id}><span className="timeline-marker" /><div className="timeline-content"><div><strong>{event.entity_type} · {event.action}</strong><span>{event.created_at}</span></div><p>操作人：{event.actor_name}</p>{detailEntries.length > 0 && <details className="audit-detail"><summary>查看留痕详情 · {detailEntries.length} 项</summary><dl>{detailEntries.map(([key, value]) => <div key={key}><dt>{auditDetailLabels[key] ?? key}</dt><dd className={typeof value === 'object' && value !== null ? 'is-structured' : ''}>{auditDetailValue(value)}</dd></div>)}</dl></details>}</div></article>
        })}</div>{state.audit_events.length > 12 && <div className="audit-timeline-footer"><span>{showAllAuditEvents ? `已显示全部 ${state.audit_events.length} 条事件` : `已显示最近 12 / ${state.audit_events.length} 条事件`}</span><button type="button" className="button quiet" onClick={() => setShowAllAuditEvents((current) => !current)}>{showAllAuditEvents ? '仅看最近 12 条' : '查看全部事件'}</button></div>}</> : <div className="empty-state"><span>当前访视尚无业务留痕。</span></div>}
      </section>
    </div>
  )
}
