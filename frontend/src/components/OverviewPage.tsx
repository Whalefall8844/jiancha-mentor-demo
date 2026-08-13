import { useEffect, useState } from 'react'
import { api } from '../api'
import type { DemoState, MasterDataRefreshPreview, ProjectInfo, Recruitment, VisitInfo } from '../types'

interface OverviewPageProps {
  state: DemoState
  onStateChange: (state: DemoState) => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

const statusClass: Record<string, string> = {
  已映射: 'tone-ready',
  已确认: 'tone-confirmed',
  待补录: 'tone-pending',
}

function masterDataTargetLabel(target: string): string {
  if (target === 'site_profile') return '中心资料（PI / 团队）'
  if (target.startsWith('document:')) return `受控文件 · ${target.slice('document:'.length).toUpperCase()}`
  return target
}

export function OverviewPage({ state, onStateChange, onNotice }: OverviewPageProps) {
  const [project, setProject] = useState<ProjectInfo>(state.project)
  const [visit, setVisit] = useState<VisitInfo>(state.visit)
  const [recruitment, setRecruitment] = useState<Recruitment>(state.recruitment)
  const [saving, setSaving] = useState(false)
  const [masterDataPreview, setMasterDataPreview] = useState<MasterDataRefreshPreview | null>(null)
  const [masterDataBusy, setMasterDataBusy] = useState(false)
  const [selectedMasterDataTargets, setSelectedMasterDataTargets] = useState<string[]>([])
  const [masterDataRefreshReason, setMasterDataRefreshReason] = useState('')
  const [masterDataRollbackReason, setMasterDataRollbackReason] = useState('')
  const templateLabel = state.template
    ? `${state.template.name} · ${state.template.version} · ${state.template.table_count} 张表`
    : `当前访视模板 · ${state.table_tasks.length} 张表`
  const frozenEligibility = state.project.project_eligibility

  useEffect(() => {
    setProject(state.project)
    setVisit(state.visit)
    setRecruitment(state.recruitment)
    setMasterDataPreview(null)
    setSelectedMasterDataTargets([])
    setMasterDataRefreshReason('')
    setMasterDataRollbackReason('')
  }, [state])

  const changeProject = (key: keyof ProjectInfo, value: string) => setProject((current) => ({ ...current, [key]: value }))
  const changeVisit = (key: keyof VisitInfo, value: string) => setVisit((current) => ({ ...current, [key]: value }))
  const changeRecruitment = (key: keyof Recruitment, value: number) => setRecruitment((current) => ({ ...current, [key]: value }))

  const save = async () => {
    try {
      setSaving(true)
      onStateChange(await api.updateProject(project, visit, recruitment))
      onNotice('项目与访视信息已保存。', 'success')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  const canRefreshMasterData = state.current_role === 'CRA' && ['draft', 'returned'].includes(visit.status ?? 'draft')

  const previewMasterDataRefresh = async () => {
    if (!visit.id || !canRefreshMasterData) return
    try {
      setMasterDataBusy(true)
      const preview = await api.getMasterDataRefreshPreview(visit.id)
      setMasterDataPreview(preview)
      setSelectedMasterDataTargets(preview.available_targets)
      setMasterDataRefreshReason('')
      setMasterDataRollbackReason('')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '固定资料更新预览失败', 'error')
    } finally {
      setMasterDataBusy(false)
    }
  }

  const applyMasterDataRefresh = async () => {
    if (!visit.id || !canRefreshMasterData) return
    if (selectedMasterDataTargets.length === 0) {
      onNotice('请至少选择一项发生变化的固定资料后再采纳。', 'error')
      return
    }
    const reason = masterDataRefreshReason.trim()
    if (!reason) {
      onNotice('请填写采纳固定资料变更的原因。', 'error')
      return
    }
    try {
      setMasterDataBusy(true)
      const result = await api.applyMasterDataRefresh(visit.id, {
        actor_name: visit.cra_name || '演示 CRA',
        selected_targets: selectedMasterDataTargets,
        reason,
      })
      onStateChange(result.workspace)
      setMasterDataPreview(null)
      setSelectedMasterDataTargets([])
      setMasterDataRefreshReason('')
      onNotice(`已采纳 ${selectedMasterDataTargets.length} 项当前有效固定资料，并更新本访视快照。`, 'success')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '固定资料刷新失败', 'error')
    } finally {
      setMasterDataBusy(false)
    }
  }

  const rollbackMasterDataRefresh = async () => {
    if (!visit.id || !canRefreshMasterData) return
    const reason = masterDataRollbackReason.trim()
    if (!reason) {
      onNotice('请填写撤销固定资料采纳的原因。', 'error')
      return
    }
    try {
      setMasterDataBusy(true)
      const result = await api.rollbackMasterDataRefresh(visit.id, {
        actor_name: visit.cra_name || '演示 CRA',
        reason,
      })
      onStateChange(result.workspace)
      setMasterDataPreview(null)
      setSelectedMasterDataTargets([])
      setMasterDataRollbackReason('')
      onNotice('已撤销最近一次固定资料采纳，并恢复当时的访视快照。', 'success')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '撤销固定资料采纳失败', 'error')
    } finally {
      setMasterDataBusy(false)
    }
  }

  return (
    <div className="page-stack">
      <section className="section-block intro-row">
        <div>
          <h2>访视控制面板</h2>
          <p>固定信息在本项目内持续复用；每次访视只补充变化字段和现场监查记录。</p>
        </div>
        <button type="button" className="button primary" onClick={save} disabled={saving}>
          {saving ? '正在保存…' : '保存项目资料'}
        </button>
      </section>

      <section className="section-block">
        <div className="section-header">
          <div>
            <h2>项目与中心固定信息</h2>
            <p>写入模板第 1、6、8、15 张表；均可在 Demo 中直接修改。</p>
          </div>
          <span className="section-code">MASTER DATA</span>
        </div>
        <div className="form-grid form-grid-three">
          <label>研究名称<input value={project.study_name} onChange={(event) => changeProject('study_name', event.target.value)} /></label>
          <label>研究编号<input value={project.study_id} onChange={(event) => changeProject('study_id', event.target.value)} /></label>
          <label>中心名称<input value={project.site_name} onChange={(event) => changeProject('site_name', event.target.value)} /></label>
          <label>主要研究者<input value={project.pi_name} onChange={(event) => changeProject('pi_name', event.target.value)} /></label>
          <label>申办方<input value={project.sponsor} onChange={(event) => changeProject('sponsor', event.target.value)} /></label>
          <label>NMPA 批件号<input value={project.approval_number} onChange={(event) => changeProject('approval_number', event.target.value)} /></label>
          <label>方案版本<input value={project.protocol_version} onChange={(event) => changeProject('protocol_version', event.target.value)} /></label>
          <label>ICF 版本<input value={project.icf_version} onChange={(event) => changeProject('icf_version', event.target.value)} /></label>
          <label>伦理信息<input value={project.ethics_date} onChange={(event) => changeProject('ethics_date', event.target.value)} /></label>
        </div>
      </section>

      <section className="section-block master-data-refresh-card">
        <div className="section-header">
          <div>
            <h2>固定资料变更检查</h2>
            <p>当前访视冻结在活动结束日期 {visit.visit_date} 的资料版本；历史报告不会被自动改写。</p>
          </div>
          <span className={`master-data-refresh-status ${canRefreshMasterData ? 'is-editable' : ''}`}>{canRefreshMasterData ? 'CRA 可预览并采纳' : '当前版本已锁定'}</span>
        </div>
        <div className="master-data-refresh-actions">
          <div><strong>检查 PI、中心资料、方案、ICF 与伦理版本</strong><small>先比较差异，再由 CRA 明确决定是否采用。</small></div>
          <button type="button" className="button quiet" disabled={!canRefreshMasterData || masterDataBusy} onClick={() => void previewMasterDataRefresh()}>{masterDataBusy ? '正在检查…' : '检查固定资料更新'}</button>
        </div>
        {masterDataPreview && <div className={`master-data-refresh-preview ${masterDataPreview.can_apply ? 'is-ready' : 'has-issues'}`}>
          <div className="template-migration-heading"><strong>{masterDataPreview.visit.code}</strong><span>·</span><strong>{masterDataPreview.visit.visit_date}</strong></div>
          {masterDataPreview.has_changes && <>
            <dl className="template-migration-summary"><div><dt>发现差异</dt><dd>{masterDataPreview.summary.changed_master_items}</dd></div><div><dt>中心团队</dt><dd>{masterDataPreview.site_team.action === 'refresh' ? '刷新' : '保留'}</dd></div></dl>
            <div className="date-reassessment-detail-grid">
              <div><strong>中心资料</strong><p>{masterDataPreview.master_data_changes.site_profile.changed ? `${masterDataPreview.master_data_changes.site_profile.from.display || '未登记'} → ${masterDataPreview.master_data_changes.site_profile.to.display || '未登记'}` : '中心资料版本不变。'}</p><small>{masterDataPreview.site_team.message}</small></div>
              <div><strong>受控文件</strong>{masterDataPreview.master_data_changes.documents.filter((item) => item.changed).length === 0 ? <p>方案、ICF、伦理及其他受控文件版本不变。</p> : masterDataPreview.master_data_changes.documents.filter((item) => item.changed).map((item) => <p key={item.document_type}>{item.document_type.toUpperCase()}：{item.from.display || item.from.title || '未登记'} → {item.to.display || item.to.title || '未登记'}</p>)}</div>
            </div>
            <div className="master-data-target-list" aria-label="选择本次采纳的固定资料">
              {masterDataPreview.master_data_changes.site_profile.changed && <label className={`master-data-target-option ${selectedMasterDataTargets.includes(masterDataPreview.master_data_changes.site_profile.target) ? 'is-selected' : ''}`}><input type="checkbox" disabled={!masterDataPreview.can_apply || masterDataBusy} checked={selectedMasterDataTargets.includes(masterDataPreview.master_data_changes.site_profile.target)} onChange={() => setSelectedMasterDataTargets((current) => current.includes(masterDataPreview.master_data_changes.site_profile.target) ? current.filter((item) => item !== masterDataPreview.master_data_changes.site_profile.target) : [...current, masterDataPreview.master_data_changes.site_profile.target])} /><span><strong>{masterDataTargetLabel(masterDataPreview.master_data_changes.site_profile.target)}</strong><small>采用当前有效的中心版本；仅在当前团队仍为原默认值时更新团队信息。</small></span></label>}
              {masterDataPreview.master_data_changes.documents.filter((item) => item.changed).map((item) => <label key={item.target} className={`master-data-target-option ${selectedMasterDataTargets.includes(item.target) ? 'is-selected' : ''}`}><input type="checkbox" disabled={!masterDataPreview.can_apply || masterDataBusy} checked={selectedMasterDataTargets.includes(item.target)} onChange={() => setSelectedMasterDataTargets((current) => current.includes(item.target) ? current.filter((target) => target !== item.target) : [...current, item.target])} /><span><strong>{masterDataTargetLabel(item.target)}</strong><small>{item.from.display || item.from.title || '未登记'} → {item.to.display || item.to.title || '未登记'}</small></span></label>)}
            </div>
            <label className="master-data-adoption-reason">采纳原因<input disabled={!masterDataPreview.can_apply || masterDataBusy} value={masterDataRefreshReason} onChange={(event) => setMasterDataRefreshReason(event.target.value)} placeholder="例如：中心已正式启用新版 ICF，本次访视需引用该版本" /></label>
            {masterDataPreview.can_apply && <button type="button" className="button primary" disabled={!canRefreshMasterData || masterDataBusy || selectedMasterDataTargets.length === 0 || !masterDataRefreshReason.trim()} onClick={() => void applyMasterDataRefresh()}>采纳已选 {selectedMasterDataTargets.length} 项资料</button>}
            {!masterDataPreview.can_apply && <p className="template-migration-warning">{masterDataPreview.reason}</p>}
          </>}
          {!masterDataPreview.has_changes && <p className="template-migration-warning">{masterDataPreview.reason || '当前冻结资料已经匹配有效版本。'}</p>}
          {masterDataPreview.rollback.can_rollback && <div className="master-data-rollback"><div><strong>撤销最近一次资料采纳</strong><small>上次于 {masterDataPreview.rollback.created_at} 采纳：{masterDataPreview.rollback.selected_targets.map(masterDataTargetLabel).join('、')}。撤销会恢复当时保存的访视快照。</small></div><label>撤销原因<input disabled={masterDataBusy} value={masterDataRollbackReason} onChange={(event) => setMasterDataRollbackReason(event.target.value)} placeholder="例如：本次访视仍应沿用原冻结版本" /></label><button type="button" className="button danger-outline" disabled={!canRefreshMasterData || masterDataBusy} onClick={() => void rollbackMasterDataRefresh()}>撤销本次采纳</button></div>}
          {!masterDataPreview.rollback.can_rollback && masterDataPreview.rollback.reason && <small className="master-data-rollback-note">{masterDataPreview.rollback.reason}</small>}
        </div>}
      </section>

      {frozenEligibility && <section className={`section-block frozen-eligibility-card ${frozenEligibility.boundary.matches_local_mvp_boundary ? 'is-in-boundary' : ''}`}>
        <div className="section-header">
          <div>
            <h2>本访视冻结的项目适用性结论</h2>
            <p>该结论在创建访视时按实际监查活动结束日期 {visit.visit_date} 选定，不随之后项目台账的更新而自动改写。</p>
          </div>
          <span className="section-code">ELIGIBILITY SNAPSHOT</span>
        </div>
        <div className="frozen-eligibility-body">
          <div><span>评估版本</span><strong>V{frozenEligibility.assessment_version}</strong><small>{frozenEligibility.assessment_scope || 'IMV_DOCX'}</small></div>
          <div><span>结论</span><strong>{frozenEligibility.boundary.matches_local_mvp_boundary ? '本地 MVP 边界内' : '已审批，需扩展评估'}</strong><small>{frozenEligibility.assessment_as_of || visit.visit_date}</small></div>
          <div><span>审批留痕</span><strong>{frozenEligibility.reviewed_by || '未记录审批人'}</strong><small>{frozenEligibility.reviewed_at || '未记录审批时间'}</small></div>
        </div>
        {!frozenEligibility.boundary.matches_local_mvp_boundary && <p className="frozen-eligibility-note">边界提示：{frozenEligibility.boundary.boundary_notes.join('；')}</p>}
      </section>}

      <section className="section-block">
        <div className="section-header">
          <div>
            <h2>本次访视信息</h2>
            <p>写入模板第 2、3、15 张表。</p>
          </div>
          <span className="section-code">VISIT SNAPSHOT</span>
        </div>
        <div className="form-grid form-grid-three">
          <label>访视类型<input value={visit.visit_type} onChange={(event) => changeVisit('visit_type', event.target.value)} /></label>
          <label>监查方式<select value={visit.visit_method} onChange={(event) => changeVisit('visit_method', event.target.value)}><option value="现场">现场</option><option value="远程">远程</option></select></label>
          <label>实际活动开始日期<input value={visit.activity_start_date} onChange={(event) => changeVisit('activity_start_date', event.target.value)} placeholder="YYYY-MM-DD" /></label>
          <label>实际活动结束日期<input value={visit.visit_date} onChange={(event) => changeVisit('visit_date', event.target.value)} placeholder="YYYY-MM-DD" /></label>
          <label>报告日期<input value={visit.report_date} onChange={(event) => changeVisit('report_date', event.target.value)} /></label>
          <label>监查地点 / 远程渠道<input value={visit.visit_location} onChange={(event) => changeVisit('visit_location', event.target.value)} placeholder="例如：中心会议室 / Teams" /></label>
          <label>本次接触人员<input value={visit.contact_persons} onChange={(event) => changeVisit('contact_persons', event.target.value)} placeholder="例如：PI、CRC、研究护士" /></label>
          <label>基地研究人员<input value={visit.site_team} onChange={(event) => changeVisit('site_team', event.target.value)} /></label>
          <label>监查团队<input value={visit.monitoring_team} onChange={(event) => changeVisit('monitoring_team', event.target.value)} /></label>
          <label>下次访视<input value={visit.next_visit} onChange={(event) => changeVisit('next_visit', event.target.value)} /></label>
        </div>
      </section>

      <div className="two-column-grid">
        <section className="section-block">
          <div className="section-header">
            <div>
              <h2>招募概况</h2>
              <p>对应模板第 4 张表。</p>
            </div>
            <span className="section-code">RECRUITMENT</span>
          </div>
          <div className="recruitment-grid">
            {([
              ['screened', '进入筛查'], ['screen_failed', '筛查脱落'], ['treated', '进入治疗'],
              ['ae_dropout', '因 AE 放弃治疗'], ['other_dropout', '其他原因放弃'], ['completed_treatment', '完成治疗'],
              ['follow_up', '进入随访'], ['follow_up_dropout', '随访脱落'], ['completed_follow_up', '完成随访'],
            ] as Array<[keyof Recruitment, string]>).map(([key, label]) => (
              <label key={key} className="compact-field">
                <span>{label}</span>
                <input type="number" min="0" value={recruitment[key]} onChange={(event) => changeRecruitment(key, Number(event.target.value))} />
              </label>
            ))}
          </div>
        </section>

        <section className="section-block">
          <div className="section-header">
            <div>
              <h2>数据归档说明</h2>
            <p>当前访视已冻结 Word 模板、主数据与任务清单，并以 SQLite 留存演示数据。</p>
            </div>
            <span className="section-code">DEMO SCOPE</span>
          </div>
          <div className="definition-list">
            <div><span>模板</span><strong>{templateLabel}</strong></div>
            <div><span>输入方式</span><strong>CRA 自然语言碎片化记录</strong></div>
            <div><span>确认角色</span><strong>CRA 确认并提交；PM/LM 审核</strong></div>
            <div><span>模型</span><strong>内置可替换的模拟提取引擎</strong></div>
          </div>
        </section>
      </div>

      <section className="section-block">
        <div className="section-header">
          <div>
            <h2>模板映射台账</h2>
            <p>全部 15 张表均保留在导出 Word 中；状态反映当前 Demo 工作底稿的完成度。</p>
          </div>
          <span className="section-code">{state.table_tasks.length} TABLES</span>
        </div>
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>序号</th><th>模板区域</th><th>当前状态</th><th>数据来源 / 说明</th></tr></thead>
            <tbody>
              {state.table_tasks.map((task) => (
                <tr key={task.id}>
                  <td className="tabular">{String(task.index).padStart(2, '0')}</td>
                  <td>{task.title}</td>
                  <td><span className={`status-dot ${statusClass[task.status] ?? 'tone-pending'}`}>{task.status}</span></td>
                  <td className="muted-cell">{task.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
