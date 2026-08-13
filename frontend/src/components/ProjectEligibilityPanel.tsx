import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../api'
import type { ProjectEligibilityAssessment, ProjectEligibilityAssessmentInput, UserRole } from '../types'

interface ProjectEligibilityPanelProps {
  projectId: string
  currentRole: UserRole
  currentBlindingMode: 'open_label' | 'blinded_with_separation'
  onChanged: () => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

type AssessmentDraft = Omit<ProjectEligibilityAssessmentInput, 'actor_name'>
type AssessmentAction = 'submit' | 'approve' | 'reject' | 'withdraw'

const statusLabel: Record<ProjectEligibilityAssessment['status'], string> = {
  draft: '草稿',
  pending_approval: '待 QA／临床运营审批',
  approved: '已审批',
  rejected: '已退回',
  withdrawn: '已撤回',
}

const blindingModeLabel = {
  open_label: '开放标签',
  blinded_with_separation: '盲态职责隔离',
} as const

function createBlankDraft(blindingMode: 'open_label' | 'blinded_with_separation'): AssessmentDraft {
  return {
    assessment_scope: 'IMV_DOCX',
    blinding_mode: blindingMode,
    processes_nonblind_data: false,
    contains_direct_identifiers: false,
    requires_full_blind_separation: false,
    uses_editable_docx_only: true,
    requires_ctms_etmf_integration: false,
    assessment_note: '',
    effective_from: '',
    effective_to: '',
  }
}

function draftFrom(item: ProjectEligibilityAssessment): AssessmentDraft {
  return {
    assessment_scope: item.assessment_scope,
    blinding_mode: item.blinding_mode,
    processes_nonblind_data: item.processes_nonblind_data,
    contains_direct_identifiers: item.contains_direct_identifiers,
    requires_full_blind_separation: item.requires_full_blind_separation,
    uses_editable_docx_only: item.uses_editable_docx_only,
    requires_ctms_etmf_integration: item.requires_ctms_etmf_integration,
    assessment_note: item.assessment_note,
    effective_from: item.effective_from,
    effective_to: item.effective_to,
  }
}

function effectivePeriod(item: ProjectEligibilityAssessment): string {
  return `${item.effective_from || '未限定起始日'} 至 ${item.effective_to || '持续有效'}`
}

export function ProjectEligibilityPanel({ projectId, currentRole, currentBlindingMode, onChanged, onNotice }: ProjectEligibilityPanelProps) {
  const [items, setItems] = useState<ProjectEligibilityAssessment[]>([])
  const [currentApproved, setCurrentApproved] = useState<ProjectEligibilityAssessment | null>(null)
  const [draftId, setDraftId] = useState('')
  const [draft, setDraft] = useState<AssessmentDraft>(() => createBlankDraft(currentBlindingMode))
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)

  const canManage = currentRole === 'PROJECT_ADMIN'
  const canReview = currentRole === 'QA_CLINICAL_OPS'

  const load = async () => {
    if (!projectId) return
    try {
      setLoading(true)
      const response = await api.listProjectEligibilityAssessments(projectId)
      setItems(response.items)
      setCurrentApproved(response.current_approved)
      const existingDraft = response.items.find((item) => item.status === 'draft')
      if (existingDraft) {
        setDraftId(existingDraft.id)
        setDraft(draftFrom(existingDraft))
      } else {
        setDraftId('')
        setDraft(createBlankDraft(currentBlindingMode))
      }
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '无法读取项目适用性评估台账', 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [projectId])

  useEffect(() => {
    if (!draftId) setDraft((current) => ({ ...current, blinding_mode: currentBlindingMode }))
  }, [currentBlindingMode, draftId])

  const persistDraft = async (): Promise<ProjectEligibilityAssessment> => {
    const payload: ProjectEligibilityAssessmentInput = { ...draft, actor_name: '项目管理员' }
    if (draftId) return api.updateProjectEligibilityAssessment(projectId, draftId, payload)
    return api.createProjectEligibilityAssessment(projectId, payload)
  }

  const startNewDraft = async () => {
    try {
      setBusy(true)
      const created = await api.createProjectEligibilityAssessment(projectId, {
        ...createBlankDraft(currentBlindingMode),
        actor_name: '项目管理员',
      })
      setDraftId(created.id)
      setDraft(draftFrom(created))
      await load()
      onChanged()
      onNotice(`已建立适用性评估 V${created.assessment_version} 草稿。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '建立适用性评估草稿失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const saveDraft = async (event: FormEvent) => {
    event.preventDefault()
    try {
      setBusy(true)
      const saved = await persistDraft()
      setDraftId(saved.id)
      await load()
      onChanged()
      onNotice(`适用性评估 V${saved.assessment_version} 已保存为草稿。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '适用性评估保存失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const submitDraft = async () => {
    try {
      setBusy(true)
      const saved = await persistDraft()
      await api.projectEligibilityAssessmentApproval(projectId, saved.id, {
        action: 'submit',
        actor_name: '项目管理员',
      })
      await load()
      onChanged()
      onNotice(`适用性评估 V${saved.assessment_version} 已提交给 QA／临床运营审批。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '提交适用性评估失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const transition = async (item: ProjectEligibilityAssessment, action: AssessmentAction) => {
    const note = (reviewNotes[item.id] ?? '').trim()
    if (action === 'reject' && !note) {
      onNotice('退回评估前请填写审核意见。', 'error')
      return
    }
    try {
      setBusy(true)
      await api.projectEligibilityAssessmentApproval(projectId, item.id, {
        action,
        actor_name: action === 'approve' || action === 'reject' ? 'QA／临床运营审批人' : '项目管理员',
        note,
      })
      setReviewNotes((current) => ({ ...current, [item.id]: '' }))
      await load()
      onChanged()
      const message = action === 'approve'
        ? `适用性评估 V${item.assessment_version} 已审批。`
        : action === 'reject'
          ? `适用性评估 V${item.assessment_version} 已退回。`
          : `适用性评估 V${item.assessment_version} 已撤回。`
      onNotice(message)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '适用性评估状态更新失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  if (!projectId) return null

  return (
    <section className="section-block project-eligibility-panel">
      <div className="section-header">
        <div>
          <h2>项目 MVP／盲态适用性评估</h2>
          <p>项目管理员发起并提交，QA／临床运营审批；已审批结论会在后续新建访视时按实际监查活动结束日期冻结。</p>
        </div>
        <span className="section-code">MVP ELIGIBILITY</span>
      </div>

      <div className={`eligibility-current ${currentApproved?.boundary.matches_local_mvp_boundary ? 'is-in-boundary' : ''}`}>
        <div>
          <span>截至今日的生效结论</span>
          <strong>{currentApproved ? (currentApproved.boundary.matches_local_mvp_boundary ? '适用于当前本地 MVP 边界' : '已审批，但声明条件超出当前本地 MVP 边界') : '尚无已审批评估'}</strong>
          <p>{currentApproved
            ? `评估 V${currentApproved.assessment_version} · ${effectivePeriod(currentApproved)}${currentApproved.boundary.boundary_notes.length ? ` · ${currentApproved.boundary.boundary_notes.join('；')}` : ''}`
            : '请先由项目管理员建立评估草稿并提交审批。'}</p>
        </div>
        {currentApproved && <span className={`eligibility-badge ${currentApproved.boundary.matches_local_mvp_boundary ? 'in-boundary' : 'out-of-boundary'}`}>{currentApproved.boundary.matches_local_mvp_boundary ? '本地 MVP 内' : '需扩展评估'}</span>}
      </div>
      <p className="eligibility-deferred-note">当前先提供受控台账与访视快照；创建访视的强制资格门禁将在交互路径确认后接入。</p>

      <div className="eligibility-history">
        <div className="eligibility-history-heading"><strong>评估版本台账</strong><small>{items.length} 条</small></div>
        {items.length === 0 ? <p className="eligibility-empty">尚无适用性评估记录。</p> : items.map((item) => (
          <article className="eligibility-record" key={item.id}>
            <div className="eligibility-record-heading">
              <div><span>评估 V{item.assessment_version}</span><strong>{item.assessment_scope || 'IMV DOCX 工作流'}</strong></div>
              <span className={`eligibility-status status-${item.status}`}>{statusLabel[item.status]}</span>
            </div>
            <dl className="eligibility-facts">
              <div><dt>盲态模式</dt><dd>{blindingModeLabel[item.blinding_mode]}</dd></div>
              <div><dt>适用期间</dt><dd>{effectivePeriod(item)}</dd></div>
              <div><dt>提交人</dt><dd>{item.submitted_by || '尚未提交'}</dd></div>
              <div><dt>审批人</dt><dd>{item.reviewed_by || '尚未审批'}</dd></div>
            </dl>
            <p className={`eligibility-boundary ${item.boundary.matches_local_mvp_boundary ? 'is-in-boundary' : 'is-out-of-boundary'}`}>
              {item.boundary.matches_local_mvp_boundary ? '该版本声明满足当前本地 MVP 的数据与模板边界。' : `边界提示：${item.boundary.boundary_notes.join('；')}`}
            </p>
            {item.assessment_note && <p className="eligibility-note">{item.assessment_note}</p>}
            {item.review_note && <p className="eligibility-review-note">审核意见：{item.review_note}</p>}
            {canManage && item.status === 'pending_approval' && <div className="eligibility-action-row">
              <label>撤回说明<input disabled={busy} value={reviewNotes[item.id] ?? ''} onChange={(event) => setReviewNotes((current) => ({ ...current, [item.id]: event.target.value }))} placeholder="可选；例如：需补充项目资料" /></label>
              <button type="button" className="button quiet small" disabled={busy} onClick={() => void transition(item, 'withdraw')}>撤回提交</button>
            </div>}
            {canReview && item.status === 'pending_approval' && <div className="eligibility-review-actions">
              <label>审核意见<textarea disabled={busy} value={reviewNotes[item.id] ?? ''} onChange={(event) => setReviewNotes((current) => ({ ...current, [item.id]: event.target.value }))} placeholder="审批可留空；退回请说明待补充内容" /></label>
              <div><button type="button" className="button secondary small" disabled={busy} onClick={() => void transition(item, 'approve')}>审批通过</button><button type="button" className="button danger-outline small" disabled={busy} onClick={() => void transition(item, 'reject')}>退回补充</button></div>
            </div>}
          </article>
        ))}
      </div>

      {canManage ? (draftId ? <form className="eligibility-draft-form" onSubmit={saveDraft}>
        <div className="eligibility-form-heading"><strong>编辑评估草稿</strong><small>可在提交前持续补充；被退回或撤回后请建立新的评估版本。</small></div>
        <div className="compact-form">
          <label>评估范围<input required disabled={busy} value={draft.assessment_scope} onChange={(event) => setDraft({ ...draft, assessment_scope: event.target.value })} placeholder="例如：IMV_DOCX" /></label>
          <label>盲态模式<select disabled={busy} value={draft.blinding_mode} onChange={(event) => setDraft({ ...draft, blinding_mode: event.target.value as AssessmentDraft['blinding_mode'] })}><option value="open_label">开放标签</option><option value="blinded_with_separation">盲态职责隔离</option></select></label>
          <label>生效起始日<input disabled={busy} value={draft.effective_from} onChange={(event) => setDraft({ ...draft, effective_from: event.target.value })} placeholder="YYYY-MM-DD；留空即不限" /></label>
          <label>生效截止日<input disabled={busy} value={draft.effective_to} onChange={(event) => setDraft({ ...draft, effective_to: event.target.value })} placeholder="YYYY-MM-DD；留空即持续" /></label>
          <label className="eligibility-wide">评估说明<textarea disabled={busy} value={draft.assessment_note} onChange={(event) => setDraft({ ...draft, assessment_note: event.target.value })} placeholder="记录项目盲态职责隔离、数据边界或评估结论依据。" /></label>
        </div>
        <div className="eligibility-checklist" aria-label="MVP 边界声明">
          <label><input type="checkbox" disabled={busy} checked={draft.processes_nonblind_data} onChange={(event) => setDraft({ ...draft, processes_nonblind_data: event.target.checked })} />本工作流需要处理非盲态／揭盲数据</label>
          <label><input type="checkbox" disabled={busy} checked={draft.contains_direct_identifiers} onChange={(event) => setDraft({ ...draft, contains_direct_identifiers: event.target.checked })} />可能录入受试者直接身份信息</label>
          <label><input type="checkbox" disabled={busy} checked={draft.requires_full_blind_separation} onChange={(event) => setDraft({ ...draft, requires_full_blind_separation: event.target.checked })} />需要系统支持完整盲态隔离能力</label>
          <label><input type="checkbox" disabled={busy} checked={draft.uses_editable_docx_only} onChange={(event) => setDraft({ ...draft, uses_editable_docx_only: event.target.checked })} />交付模板为可编辑 DOCX（当前支持）</label>
          <label><input type="checkbox" disabled={busy} checked={draft.requires_ctms_etmf_integration} onChange={(event) => setDraft({ ...draft, requires_ctms_etmf_integration: event.target.checked })} />本期必须与 CTMS／eTMF 系统集成</label>
        </div>
        <div className="eligibility-form-actions"><span>提交后版本转入 QA／临床运营审批，不能再直接编辑。</span><div><button className="button quiet" disabled={busy}>{busy ? '正在保存…' : '保存草稿'}</button><button type="button" className="button primary" disabled={busy} onClick={() => void submitDraft()}>提交审批</button></div></div>
      </form> : <div className="eligibility-start">
        <div><strong>建立新评估版本</strong><span>每次重新评估均生成独立版本，既往审批与撤回记录会保留在台账中。</span></div>
        <button type="button" className="button secondary" disabled={busy} onClick={() => void startNewDraft()}>新建评估草稿</button>
      </div>) : !canReview && <p className="eligibility-readonly">当前为 {currentRole === 'CRA' ? 'CRA' : 'PM／LM'} 角色：可查看项目适用性结论和版本历史；发起由项目管理员完成。</p>}
      {loading && <p className="eligibility-loading">正在刷新适用性评估台账…</p>}
    </section>
  )
}
