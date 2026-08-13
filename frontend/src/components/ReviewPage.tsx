import { useState } from 'react'
import { api, reportStatusLabel } from '../api'
import type { DemoState } from '../types'
import { buildReportPreviewParagraphs, reviewCommentLabel, reviewTargetLabel } from '../reportPreview'

interface ReviewPageProps {
  state: DemoState
  onStateChange: (state: DemoState) => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

type SpecialistAction = 'specialist_comment' | 'specialist_concurrence'

const reviewActionLabel = { comment: '审核建议', returned: '退回 CRA', approved: '批准报告' }
const specialistActionLabel: Record<SpecialistAction, string> = {
  specialist_comment: '提交专项批注',
  specialist_concurrence: '记录专项阅知',
}

export function ReviewPage({ state, onStateChange, onNotice }: ReviewPageProps) {
  const [reviewerName, setReviewerName] = useState('PM/LM 审核人')
  const [message, setMessage] = useState('')
  const [targetKey, setTargetKey] = useState('')
  const [startingReview, setStartingReview] = useState(false)
  const [specialistName, setSpecialistName] = useState('医学监察／数据管理')
  const [specialistAction, setSpecialistAction] = useState<SpecialistAction>('specialist_comment')
  const [specialistMessage, setSpecialistMessage] = useState('')
  const [submittingSpecialist, setSubmittingSpecialist] = useState(false)
  const isReviewer = state.current_role === 'PM_LM'
  const isSpecialist = state.current_role === 'MEDICAL_DATA_REVIEWER'
  const latestRevision = state.revisions[0]
  const hasSubmittedRevision = Boolean(latestRevision) && state.report_status === 'submitted' && latestRevision?.status === 'submitted'
  const isReviewEligible = isReviewer && hasSubmittedRevision
  const canReview = isReviewEligible && Boolean(latestRevision?.review_started_at)
  const canSpecialistComment = isSpecialist && hasSubmittedRevision
  const canAnnotate = canReview || canSpecialistComment
  const paragraphs = buildReportPreviewParagraphs(state)
  const targetOptions = <>
    <option value="">整份报告</option>
    <optgroup label="报告预览段落">{paragraphs.map((paragraph) => <option key={paragraph.targetKey} value={paragraph.targetKey}>段落 {paragraph.sequence} · 表 {paragraph.targetTable} · {paragraph.text}</option>)}</optgroup>
    <optgroup label="按 Word 表格定位">{state.table_tasks.map((task) => <option key={task.id} value={`table_${task.table_index ?? task.index}`}>表 {task.table_index ?? task.index} · {task.title}</option>)}</optgroup>
    <optgroup label="按已确认字段定位">{state.confirmed_items.map((field) => <option key={field.id} value={`field_${field.id}`}>表 {field.target_table} · {field.report_text ?? field.text}</option>)}</optgroup>
  </>

  const startReview = async () => {
    if (!latestRevision || !state.visit.id || !isReviewEligible) return
    try {
      setStartingReview(true)
      const response = await api.startRevisionReview(latestRevision.id, reviewerName)
      onStateChange(response.workspace)
      onNotice('已领取报告审核。CRA 主动撤回窗口已关闭；后续可提出建议、退回或批准。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '开始审核失败', 'error')
    } finally {
      setStartingReview(false)
    }
  }

  const doReview = async (action: 'comment' | 'returned' | 'approved') => {
    if (!latestRevision || !state.visit.id || !canReview) return
    try {
      await api.reviewRevision(latestRevision.id, { action, message, reviewer_name: reviewerName, target_key: targetKey })
      onStateChange(await api.getState(state.visit.id))
      setMessage('')
      onNotice(`${reviewActionLabel[action]}已记录。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '审核操作失败', 'error')
    }
  }

  const doSpecialistReview = async () => {
    if (!latestRevision || !state.visit.id || !canSpecialistComment) return
    if (specialistAction === 'specialist_comment' && !specialistMessage.trim()) {
      onNotice('请填写专项批注内容；如无补充意见，请改选“专项阅知 / 无补充意见”。', 'error')
      return
    }
    try {
      setSubmittingSpecialist(true)
      await api.createSpecialistReviewComment(latestRevision.id, {
        action: specialistAction,
        message: specialistMessage,
        reviewer_name: specialistName,
        target_key: targetKey,
      })
      onStateChange(await api.getState(state.visit.id))
      setSpecialistMessage('')
      onNotice(specialistAction === 'specialist_comment' ? '专项批注已记录，等待 CRA 处置。' : '专项阅知已记录；该记录不会改变报告审核状态。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '专项意见记录失败', 'error')
    } finally {
      setSubmittingSpecialist(false)
    }
  }

  return (
    <div className="review-layout">
      <section className="section-block review-summary">
        <div className="section-header">
          <div><h2>审核队列</h2><p>CRA 对报告事实负责并完成提交；PM/LM 提出审核结论。医学监察／数据管理仅作专项批注或阅知，不替代任一职责。</p></div>
          <span className={`report-status status-${state.report_status}`}>{reportStatusLabel[state.report_status]}</span>
        </div>
        <div className="review-facts"><div><span>提交人</span><strong>{state.visit.cra_name}</strong></div><div><span>提交时间</span><strong>{state.last_submitted_at ?? '尚未提交'}</strong></div><div><span>已确认工作底稿</span><strong>{state.confirmed_items.length} 条</strong></div><div><span>当前版本</span><strong>{latestRevision?.version_number ?? '—'}</strong></div></div>
      </section>

      {isReviewer && <section className="section-block reviewer-composer">
        <div className="section-header"><div><h2>PM / LM 审核操作</h2><p>{canReview ? '选择整份报告、预览段落、表格或已确认字段作为建议定位；建议不会直接覆盖 CRA 事实。' : isReviewEligible ? '填写审核人后领取报告，即可进入审核；领取后 CRA 不再可以主动撤回。' : '请先由 CRA 在“报告生成”页面确认并提交当前版本。'}</p></div><span className="section-code">TARGETED REVIEW</span></div>
        {isReviewEligible && !canReview && <div className="review-lock-start"><span>领取后即可执行审核动作；领取本身会进入审计时间线。</span><button type="button" className="button secondary" disabled={startingReview || !reviewerName.trim()} onClick={() => void startReview()}>{startingReview ? '正在领取…' : '开始审核'}</button></div>}
        {canReview && <div className="review-lock-state"><span>审核锁已建立</span><strong>{latestRevision?.review_started_by || 'PM/LM 审核人'}</strong><small>{latestRevision?.review_started_at}</small></div>}
        <div className="form-grid review-fields">
          <label>审核人<input value={reviewerName} onChange={(event) => setReviewerName(event.target.value)} disabled={!isReviewEligible || canReview} /></label>
          <label>建议定位<select value={targetKey} onChange={(event) => setTargetKey(event.target.value)} disabled={!canReview}>{targetOptions}</select></label>
          <label className="review-message">审核意见<textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="例如：请补充偏离事件的纠正措施及预计完成时间。" disabled={!canReview} /></label>
        </div>
        <div className="review-actions"><button type="button" className="button quiet" disabled={!canReview} onClick={() => void doReview('comment')}>添加建议</button><button type="button" className="button secondary" disabled={!canReview} onClick={() => void doReview('returned')}>退回 CRA 修订</button><button type="button" className="button primary" disabled={!canReview} onClick={() => void doReview('approved')}>批准报告</button></div>
      </section>}

      {isSpecialist && <section className="section-block specialist-composer">
        <div className="section-header"><div><h2>医学监察／数据管理专项意见</h2><p>{canSpecialistComment ? '可对整份报告、段落、表格或字段留下专项批注或阅知记录；不会领取审核、退回或批准报告。' : '请先由 CRA 提交当前报告版本；专项意见仅记录在待审核报告上。'}</p></div><span className="section-code">SPECIALIST NOTE</span></div>
        <div className="specialist-boundary"><strong>职责边界</strong><span>专项意见不自动形成医学判断、方案偏离、AE/SAE 结论、严重性或编码；CRA 决定事实与提交，PM/LM 保留退回与批准权限。</span></div>
        <div className="form-grid review-fields specialist-review-fields">
          <label>专项参与人<input value={specialistName} onChange={(event) => setSpecialistName(event.target.value)} disabled={!canSpecialistComment} /></label>
          <label>意见类型<select value={specialistAction} onChange={(event) => setSpecialistAction(event.target.value as SpecialistAction)} disabled={!canSpecialistComment}><option value="specialist_comment">专项批注</option><option value="specialist_concurrence">专项阅知 / 无补充意见</option></select></label>
          <label>意见定位<select value={targetKey} onChange={(event) => setTargetKey(event.target.value)} disabled={!canSpecialistComment}>{targetOptions}</select></label>
          <label className="review-message">{specialistAction === 'specialist_comment' ? '专项批注' : '补充说明（可选）'}<textarea value={specialistMessage} onChange={(event) => setSpecialistMessage(event.target.value)} placeholder={specialistAction === 'specialist_comment' ? '例如：请按客户 SOP 由 CRA 进一步核对相关安全性信息的记录完整性。' : '例如：已按授权范围阅知，无补充专项意见。'} disabled={!canSpecialistComment} /></label>
        </div>
        <div className="review-actions"><button type="button" className="button primary" disabled={!canSpecialistComment || submittingSpecialist || !specialistName.trim()} onClick={() => void doSpecialistReview()}>{submittingSpecialist ? '正在记录…' : specialistActionLabel[specialistAction]}</button></div>
      </section>}

      {!isReviewer && !isSpecialist && <section className="section-block role-readonly-card"><strong>当前角色可查看审核上下文</strong><span>PM/LM 执行审核、退回与批准；医学监察／数据管理可在协作中心切换后记录专项批注；CRA 在报告页处置开放意见。</span></section>}

      <section className="section-block report-preview-review">
        <div className="section-header compact-header"><div><h2>报告预览段落</h2><p>系统内预览按已确认、可进入报告的文字形成稳定段落锚点；PM/LM 或专项角色可点击定位意见，不等同于 Word 原生批注或修订。</p></div><span className="section-code">PARAGRAPH REVIEW</span></div>
        {paragraphs.length === 0 ? <div className="empty-state inline"><span>尚无可供审核定位的报告预览段落。</span></div> : <div className="review-paragraph-list">{paragraphs.map((paragraph) => <article key={paragraph.targetKey} className={`review-paragraph-row ${targetKey === paragraph.targetKey ? 'is-selected' : ''}`}><div><span>段落 {paragraph.sequence} · 表 {paragraph.targetTable}</span><strong>{paragraph.taskTitle}</strong><p>{paragraph.text}</p></div><button type="button" className="button quiet small" disabled={!canAnnotate} onClick={() => setTargetKey(paragraph.targetKey)}>{targetKey === paragraph.targetKey ? '已选中' : '定位到此段'}</button></article>)}</div>}
      </section>

      <section className="section-block">
        <div className="section-header compact-header"><div><h2>审核与专项意见留痕</h2><p>PM/LM 审核建议与医学监察／数据管理专项意见在同一过程台账中区分呈现；CRA 处置均保留独立记录。</p></div><span className="section-code">REVIEW LEDGER</span></div>
        {state.review_comments.length === 0 ? <div className="empty-state"><strong>尚无审核或专项意见</strong><span>CRA 提交后，PM/LM 可创建审核建议，医学监察／数据管理可记录专项批注或阅知。</span></div> : <div className="timeline">{[...state.review_comments].reverse().map((item) => <article className={`timeline-item comment-type-${item.comment_type ?? 'pm_lm_review'}`} key={item.id}><div className="timeline-marker" /><div className="timeline-content"><div><strong>{reviewCommentLabel(item)}</strong><span>{item.created_at}</span></div><span className={`review-comment-kind kind-${item.comment_type ?? 'pm_lm_review'}`}>{item.comment_type === 'pm_lm_review' || !item.comment_type ? 'PM / LM 审核' : '医学监察 / 数据管理'}</span><span className="review-target">{reviewTargetLabel(item, state)}</span><p>{item.message}</p><small>记录人：{item.reviewer_name}</small>{item.status === 'resolved' && <small className="review-resolution">CRA 已{item.resolution === 'accepted' ? '接受' : '不采用'}：{item.resolution_note || '未填写补充说明'} · {item.resolved_by}</small>}</div></article>)}</div>}
      </section>
    </div>
  )
}
