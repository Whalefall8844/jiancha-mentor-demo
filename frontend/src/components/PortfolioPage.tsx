import { Fragment, useEffect, useRef, useState, type FormEvent } from 'react'
import { api, reportStatusLabel } from '../api'
import { ControlledDataPanel } from './ControlledDataPanel'
import { ExternalReadOnlyAdapterPanel } from './ExternalReadOnlyAdapterPanel'
import { ImportPanel } from './ImportPanel'
import { ImportQualityPanel } from './ImportQualityPanel'
import { MasterDataImportProfilePanel } from './MasterDataImportProfilePanel'
import { ProjectEligibilityPanel } from './ProjectEligibilityPanel'
import { readExternalReadOnlyAdapter } from '../externalReadOnlyAdapter'
import { readMasterDataImportProfiles } from '../masterDataImportProfiles'
import type { DemoState, ProjectSummary, RulePack, SiteSummary, TemplateRecommendationResponse, TemplateSummary, VisitSummary } from '../types'

interface PortfolioPageProps {
  state: DemoState
  onStateChange: (state: DemoState) => void
  onOpenWorkspace: () => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

type CreateMode = 'project' | 'site' | 'visit'

const blindingModeLabel = {
  open_label: '开放标签',
  blinded_with_separation: '盲态职责隔离',
} as const

const subjectCodeDisplayModeLabel = {
  masked: '掩码显示',
  full: '完整显示',
} as const

const ruleEligibilityLabel: Record<string, string> = {
  eligible: '适用',
  not_yet_effective: '尚未生效',
  expired: '已失效',
  visit_date_required: '待匹配日期',
  invalid_visit_date: '日期格式无效',
  invalid_rule_dates: '规则日期异常',
}

const templateMatchConfidenceLabel: Record<string, string> = {
  high: '高置信度',
  medium: '中等置信度',
  low: '待 CRA 复核',
}

export function PortfolioPage({ state, onStateChange, onOpenWorkspace, onNotice }: PortfolioPageProps) {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [templates, setTemplates] = useState<TemplateSummary[]>([])
  const [rulePacks, setRulePacks] = useState<RulePack[]>([])
  const [sites, setSites] = useState<SiteSummary[]>([])
  const [visits, setVisits] = useState<VisitSummary[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [selectedSiteId, setSelectedSiteId] = useState('')
  const [createMode, setCreateMode] = useState<CreateMode>('project')
  const [busy, setBusy] = useState(false)
  const [projectDraft, setProjectDraft] = useState({ code: '', name: '', sponsor: '', blinding_mode: 'open_label' as keyof typeof blindingModeLabel, subject_code_display_mode: 'masked' as keyof typeof subjectCodeDisplayModeLabel })
  const [siteDraft, setSiteDraft] = useState({ code: '', name: '', pi_name: '', protocol_version: '', icf_version: '' })
  const [visitDraft, setVisitDraft] = useState({
    code: '',
    visit_type: 'IMV',
    visit_date: '',
    activity_start_date: '',
    visit_method: '现场',
    visit_location: '',
    contact_persons: '',
    report_date: '',
    cra_name: '演示 CRA',
    template_id: '',
    rule_pack_id: '',
  })
  const [projectControlDraft, setProjectControlDraft] = useState({ blinding_mode: 'open_label' as keyof typeof blindingModeLabel, subject_code_display_mode: 'masked' as keyof typeof subjectCodeDisplayModeLabel })
  const [templateRecommendation, setTemplateRecommendation] = useState<TemplateRecommendationResponse | null>(null)
  const [templateMatchLoading, setTemplateMatchLoading] = useState(false)
  const [cancellingVisitId, setCancellingVisitId] = useState<string | null>(null)
  const [visitCancellationReasons, setVisitCancellationReasons] = useState<Record<string, string>>({})
  const [importQualityRefreshToken, setImportQualityRefreshToken] = useState(0)
  const autoMatchedTemplateId = useRef('')

  const selectedProject = projects.find((item) => item.id === selectedProjectId)
  const selectedSite = sites.find((item) => item.id === selectedSiteId)
  const selectedExternalReadOnlyAdapter = selectedProject ? readExternalReadOnlyAdapter(selectedProject.metadata) : undefined
  const selectedMasterDataImportProfiles = selectedProject ? readMasterDataImportProfiles(selectedProject.metadata) : []
  const selectedRulePack = rulePacks.find((item) => item.id === visitDraft.rule_pack_id)
  const eligibleRulePacks = rulePacks.filter((item) => item.eligibility?.selectable)
  const canManageMasterData = state.current_role === 'PROJECT_ADMIN'
  const canCreateVisit = state.current_role === 'CRA' || state.current_role === 'PROJECT_ADMIN'
  const isCRA = state.current_role === 'CRA'

  const loadVisits = async (projectId: string, siteId: string) => {
    const response = await api.listVisits(projectId, siteId || undefined)
    setVisits(response.items)
  }

  const selectProject = async (projectId: string, preferredSiteId?: string) => {
    setSelectedProjectId(projectId)
    const siteResponse = await api.listSites(projectId)
    setSites(siteResponse.items)
    setRulePacks([])
    const siteId = preferredSiteId ?? siteResponse.items[0]?.id ?? ''
    setSelectedSiteId(siteId)
    await loadVisits(projectId, siteId)
  }

  const refreshPortfolio = async () => {
    const [projectResponse, templateResponse] = await Promise.all([api.listProjects(), api.listTemplates()])
    setProjects(projectResponse.items)
    setTemplates(templateResponse.items)
    const currentProjectId = state.visit.project_id && projectResponse.items.some((item) => item.id === state.visit.project_id)
      ? state.visit.project_id
      : projectResponse.items[0]?.id ?? ''
    if (currentProjectId) await selectProject(currentProjectId, state.visit.site_id)
  }

  useEffect(() => { void refreshPortfolio() }, [])

  useEffect(() => {
    if (!selectedProjectId) return
    let cancelled = false
    const loadEligibleRules = async () => {
      try {
        const response = await api.listRulePackEligibility(selectedProjectId, visitDraft.visit_date)
        if (cancelled) return
        setRulePacks(response.items)
        setVisitDraft((current) => {
          const stillSelectable = response.items.some((item) => item.id === current.rule_pack_id && item.eligibility?.selectable)
          if (stillSelectable) return current
          return { ...current, rule_pack_id: response.items.find((item) => item.eligibility?.selectable)?.id ?? '' }
        })
      } catch (error) {
        if (!cancelled) onNotice(error instanceof Error ? error.message : '规则适用性加载失败', 'error')
      }
    }
    void loadEligibleRules()
    return () => { cancelled = true }
  }, [selectedProjectId, visitDraft.visit_date])

  useEffect(() => {
    if (!selectedProjectId || !visitDraft.visit_type.trim()) {
      setTemplateRecommendation(null)
      setTemplateMatchLoading(false)
      return
    }
    let cancelled = false
    const requestedVisitType = visitDraft.visit_type.trim()
    const loadTemplateRecommendation = async () => {
      try {
        setTemplateMatchLoading(true)
        const response = await api.getTemplateRecommendations(selectedProjectId, requestedVisitType)
        if (cancelled) return
        setTemplateRecommendation(response)
        if (response.auto_selectable && response.recommended_template_id) {
          setVisitDraft((current) => {
            if (current.visit_type.trim() !== requestedVisitType) return current
            if (current.template_id && current.template_id !== autoMatchedTemplateId.current) return current
            autoMatchedTemplateId.current = response.recommended_template_id
            return current.template_id === response.recommended_template_id
              ? current
              : { ...current, template_id: response.recommended_template_id }
          })
        }
      } catch {
        if (!cancelled) setTemplateRecommendation(null)
      } finally {
        if (!cancelled) setTemplateMatchLoading(false)
      }
    }
    void loadTemplateRecommendation()
    return () => { cancelled = true }
  }, [selectedProjectId, visitDraft.visit_type])

  useEffect(() => {
    const mode = selectedProject?.metadata?.blinding_mode
    const displayMode = selectedProject?.metadata?.subject_code_display_mode
    setProjectControlDraft({
      blinding_mode: mode === 'blinded_with_separation' ? 'blinded_with_separation' : 'open_label',
      subject_code_display_mode: displayMode === 'full' ? 'full' : 'masked',
    })
  }, [selectedProjectId, projects])

  const selectSite = async (siteId: string) => {
    setSelectedSiteId(siteId)
    if (selectedProjectId) await loadVisits(selectedProjectId, siteId)
  }

  const openVisit = async (visit: VisitSummary) => {
    if (visit.latest_revision_status === 'cancelled') {
      onNotice('该访视草稿已取消，工作底稿和审计记录仍在台账中保留。', 'error')
      return
    }
    try {
      setBusy(true)
      onStateChange(await api.getState(visit.id))
      onOpenWorkspace()
      onNotice(`已打开 ${visit.code} 访视工作区。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '打开访视失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const cancelVisit = async (visit: VisitSummary) => {
    const reason = (visitCancellationReasons[visit.id] ?? '').trim()
    if (!reason) {
      onNotice('请填写取消该草稿访视的原因。', 'error')
      return
    }
    try {
      setBusy(true)
      await api.cancelVisit(visit.id, { reason, actor_name: state.visit.cra_name || '演示 CRA' })
      setCancellingVisitId(null)
      setVisitCancellationReasons((current) => ({ ...current, [visit.id]: '' }))
      await loadVisits(selectedProjectId, selectedSiteId)
      if (state.visit.id === visit.id) onStateChange(await api.getState(visit.id))
      onNotice(`草稿访视 ${visit.code} 已取消；历史工作底稿和审计记录已保留。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '取消草稿访视失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const createProject = async (event: FormEvent) => {
    event.preventDefault()
    if (!canManageMasterData) {
      onNotice('项目与中心固定资料由项目管理员维护。', 'error')
      return
    }
    try {
      setBusy(true)
      const project = await api.createProject({
        code: projectDraft.code,
        name: projectDraft.name,
        sponsor: projectDraft.sponsor,
        metadata: { blinding_mode: projectDraft.blinding_mode, subject_code_display_mode: projectDraft.subject_code_display_mode },
      })
      setProjectDraft({ code: '', name: '', sponsor: '', blinding_mode: 'open_label', subject_code_display_mode: 'masked' })
      await refreshPortfolio()
      await selectProject(project.id)
      setCreateMode('site')
      onNotice('项目已建立，请继续维护中心信息。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '新建项目失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const createSite = async (event: FormEvent) => {
    event.preventDefault()
    if (!selectedProjectId || !canManageMasterData) {
      if (!canManageMasterData) onNotice('项目与中心固定资料由项目管理员维护。', 'error')
      return
    }
    try {
      setBusy(true)
      const site = await api.createSite({ project_id: selectedProjectId, ...siteDraft })
      setSiteDraft({ code: '', name: '', pi_name: '', protocol_version: '', icf_version: '' })
      setProjects((await api.listProjects()).items)
      await selectProject(selectedProjectId, site.id)
      setCreateMode('visit')
      onNotice('中心已建立，可以创建监查访视。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '新建中心失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const createVisit = async (event: FormEvent) => {
    event.preventDefault()
    if (!selectedProjectId || !selectedSiteId || !canCreateVisit) {
      if (!canCreateVisit) onNotice('监查访视由 CRA 创建；项目管理员可协助维护演示台账。', 'error')
      return
    }
    const templateId = visitDraft.template_id || templates[0]?.id
    if (!templateId) {
      onNotice('请先在模板库登记一个 Word 模板。', 'error')
      return
    }
    if (!visitDraft.rule_pack_id || !selectedRulePack?.eligibility?.selectable) {
      onNotice('请填写访视日期，并选择当前日期适用的已启用规则包。', 'error')
      return
    }
    try {
      setBusy(true)
      const response = await api.createVisit({ project_id: selectedProjectId, site_id: selectedSiteId, ...visitDraft, template_id: templateId })
      onStateChange(await api.getState(response.visit.id))
      onOpenWorkspace()
      onNotice('访视已建立，并已生成 15 项监查任务。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '新建访视失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const saveProjectControl = async () => {
    if (!selectedProject || !canManageMasterData) return
    try {
      setBusy(true)
      const saved = await api.patchProject(selectedProject.id, {
        metadata: {
          ...selectedProject.metadata,
          blinding_mode: projectControlDraft.blinding_mode,
          subject_code_display_mode: projectControlDraft.subject_code_display_mode,
        },
      })
      setProjects((current) => current.map((item) => item.id === saved.id ? { ...item, ...saved } : item))
      onNotice(`${projectControlDraft.blinding_mode === 'blinded_with_separation'
        ? '已启用盲态职责隔离：系统不会执行揭盲，新访视将冻结该边界。'
        : '项目已设为开放标签；系统仍不会记录或推断治疗分组。'} 受试者编号将按“${subjectCodeDisplayModeLabel[projectControlDraft.subject_code_display_mode]}”呈现。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '项目控制配置保存失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const recommendedTemplate = templateRecommendation?.items[0] ?? null

  const adoptRecommendedTemplate = () => {
    if (!recommendedTemplate) return
    autoMatchedTemplateId.current = recommendedTemplate.template.id
    setVisitDraft((current) => ({ ...current, template_id: recommendedTemplate.template.id }))
    onNotice(`已采用推荐模板：${recommendedTemplate.template.name} · ${recommendedTemplate.template.version}`)
  }

  return (
    <div className="portfolio-stack">
      <section className="portfolio-brief">
        <div>
          <p className="eyebrow">Portfolio / Site / Visit</p>
          <h2>项目组合与访视台账</h2>
          <p>固定主数据按项目和中心持续复用；每一次 IMV 在独立工作区中记录、生成版本并留存审核结果。</p>
        </div>
        <dl className="portfolio-stats">
          <div><dt>项目</dt><dd>{projects.length}</dd></div>
          <div><dt>当前中心</dt><dd>{sites.length}</dd></div>
          <div><dt>当前访视</dt><dd>{visits.length}</dd></div>
        </dl>
      </section>

      <div className="portfolio-layout">
        <section className="section-block project-register">
          <div className="section-header compact-header"><div><h2>项目台账</h2><p>选择一个项目后，右侧显示其中心与访视记录。</p></div><span className="section-code">PORTFOLIO</span></div>
          <div className="portfolio-project-list" role="list">
            {projects.map((project) => (
              <button key={project.id} type="button" role="listitem" className={`portfolio-project ${project.id === selectedProjectId ? 'is-selected' : ''}`} onClick={() => void selectProject(project.id)}>
                <span className="project-code">{project.code}</span>
                <strong>{project.name}</strong>
                <small>{project.sponsor || '未填写申办方'} · {project.site_count} 个中心 / {project.visit_count} 次访视</small>
              </button>
            ))}
          </div>
        </section>

        <div className="portfolio-detail">
          <section className="section-block portfolio-context">
            <div className="section-header compact-header">
              <div><p className="eyebrow">CURRENT PROJECT</p><h2>{selectedProject?.name ?? '请选择项目'}</h2><p>{selectedProject ? `${selectedProject.code} · ${selectedProject.sponsor || '未填写申办方'}` : '可先在下方创建一个新项目。'}</p></div>
              {selectedProject && <span className="project-status">{selectedProject.status}</span>}
            </div>
            <div className="site-picker">
              <span>中心</span>
              <div className="site-chip-list">
                {sites.length === 0 ? <small>该项目尚无中心</small> : sites.map((site) => <button type="button" key={site.id} className={`site-chip ${site.id === selectedSiteId ? 'is-selected' : ''}`} onClick={() => void selectSite(site.id)}>{site.code} · {site.name}</button>)}
              </div>
            </div>
            {selectedSite && <div className="site-meta"><span>PI：{selectedSite.pi_name || '未填写'}</span><span>方案：{selectedSite.protocol_version || '未填写'}</span><span>ICF：{selectedSite.icf_version || '未填写'}</span></div>}
            {selectedProject && <div className={`trial-control-strip ${projectControlDraft.blinding_mode}`}>
              <div>
                <span>试验盲态控制</span>
                <strong>{blindingModeLabel[projectControlDraft.blinding_mode]}</strong>
                <small>{projectControlDraft.blinding_mode === 'blinded_with_separation' ? '系统不执行揭盲；请依照项目职责隔离安排，仅记录非盲态监查信息。' : '系统不记录或推断治疗分组，可用于常规开放标签监查工作。'} 工作台受试者编号：{subjectCodeDisplayModeLabel[projectControlDraft.subject_code_display_mode]}。</small>
              </div>
              {canManageMasterData ? <div className="trial-control-actions"><select aria-label="项目盲态控制" value={projectControlDraft.blinding_mode} disabled={busy} onChange={(event) => setProjectControlDraft({ ...projectControlDraft, blinding_mode: event.target.value as keyof typeof blindingModeLabel })}><option value="open_label">开放标签</option><option value="blinded_with_separation">盲态职责隔离</option></select><select aria-label="工作台受试者编号显示" value={projectControlDraft.subject_code_display_mode} disabled={busy} onChange={(event) => setProjectControlDraft({ ...projectControlDraft, subject_code_display_mode: event.target.value as keyof typeof subjectCodeDisplayModeLabel })}><option value="masked">编号掩码显示</option><option value="full">编号完整显示</option></select><button type="button" className="button small" disabled={busy} onClick={() => void saveProjectControl()}>保存控制</button></div> : <span className="trial-control-readonly">仅项目管理员可维护</span>}
            </div>}
          </section>

          {selectedProject && <ProjectEligibilityPanel
            projectId={selectedProject.id}
            currentRole={state.current_role}
            currentBlindingMode={projectControlDraft.blinding_mode}
            onChanged={() => { if (selectedProjectId) void selectProject(selectedProjectId, selectedSiteId) }}
            onNotice={onNotice}
          />}

          {selectedProject && <ExternalReadOnlyAdapterPanel
            project={selectedProject}
            canManage={canManageMasterData}
            onChanged={() => { void refreshPortfolio() }}
            onNotice={onNotice}
          />}

          {selectedProject && <MasterDataImportProfilePanel
            project={selectedProject}
            canManage={canManageMasterData}
            onChanged={() => { void refreshPortfolio() }}
            onNotice={onNotice}
          />}

          <section className="section-block visit-ledger">
            <div className="section-header"><div><h2>访视记录</h2><p>每个访视独立冻结主数据、规则包与报告修订版本。</p></div><span className="section-code">VISIT LEDGER</span></div>
            {visits.length === 0 ? <div className="empty-state"><strong>当前中心尚无访视</strong><span>使用下方“新建访视”即可按选定模板生成监查任务。</span></div> : (
              <div className="data-table-wrap"><table className="data-table"><thead><tr><th>访视编号</th><th>类型 / 活动</th><th>冻结模板</th><th>报告版本</th><th>状态</th><th /></tr></thead><tbody>{visits.map((visit) => {
                const visitStatus = visit.latest_revision_status ?? 'draft'
                const canCancel = isCRA && Boolean(visit.cancellation_eligible)
                const isCancelled = visitStatus === 'cancelled'
                return <Fragment key={visit.id}>
                  <tr>
                    <td><strong>{visit.code}</strong><br /><small className="muted-cell">{visit.site_name}</small></td>
                    <td>{visit.visit_type}<br /><small className="muted-cell">{visit.visit_method || '现场'} · {visit.activity_start_date && visit.activity_start_date !== visit.visit_date ? `${visit.activity_start_date} → ` : ''}{visit.visit_date}</small></td>
                    <td>{visit.template_name}<br /><small className="muted-cell">{visit.template_version}</small></td>
                    <td className="tabular">{visit.revision_count ? `V0.${visit.revision_count}` : '未生成'}</td>
                    <td><span className={`report-status status-${visitStatus}`}>{reportStatusLabel[visitStatus]}</span></td>
                    <td className="visit-ledger-actions"><div className="visit-ledger-action-buttons">
                      <button type="button" className="button small" disabled={busy || isCancelled} onClick={() => void openVisit(visit)}>{isCancelled ? '已取消' : '打开'}</button>
                      {canCancel && <button type="button" className="button small danger-outline" disabled={busy} onClick={() => setCancellingVisitId((current) => current === visit.id ? null : visit.id)}>{cancellingVisitId === visit.id ? '收起取消' : '取消草稿'}</button>}
                    </div>{isCancelled && <small className="visit-cancelled-note">取消记录已保留</small>}</td>
                  </tr>
                  {canCancel && cancellingVisitId === visit.id && <tr className="visit-cancel-row"><td colSpan={6}><div className="visit-cancel-form">
                    <label>取消原因<input autoFocus disabled={busy} value={visitCancellationReasons[visit.id] ?? ''} onChange={(event) => setVisitCancellationReasons((current) => ({ ...current, [visit.id]: event.target.value }))} placeholder="例如：误建重复访视，尚未录入正式报告" /></label>
                    <div className="visit-cancel-form-actions"><small className="visit-cancel-form-note">取消后保留记录，不可恢复为工作中。</small><button type="button" className="button quiet small" disabled={busy} onClick={() => setCancellingVisitId(null)}>返回</button><button type="button" className="button danger-outline small" disabled={busy} onClick={() => void cancelVisit(visit)}>确认取消</button></div>
                  </div></td></tr>}
                </Fragment>
              })}</tbody></table></div>
            )}
          </section>

          <ControlledDataPanel
            projectId={selectedProjectId}
            site={selectedSite}
            visitDate={visitDraft.visit_date}
            currentRole={state.current_role}
            onChanged={() => { if (selectedProjectId) void selectProject(selectedProjectId, selectedSiteId) }}
            onNotice={onNotice}
          />

          <section className="section-block create-ledger">
            <div className="section-header"><div><h2>快速建档</h2><p>按项目 → 中心 → 访视的顺序建立新的工作空间。</p></div><span className="section-code">CREATE</span></div>
            <div className="create-tabs" role="tablist" aria-label="新建对象">
              {(['project', 'site', 'visit'] as CreateMode[]).map((mode) => <button type="button" role="tab" aria-selected={createMode === mode} key={mode} className={createMode === mode ? 'is-active' : ''} onClick={() => setCreateMode(mode)}>{mode === 'project' ? '新建项目' : mode === 'site' ? '新建中心' : '新建访视'}</button>)}
            </div>
            {createMode === 'project' && <form className="compact-form" onSubmit={createProject}>
              <label>项目编号<input required disabled={!canManageMasterData} value={projectDraft.code} onChange={(event) => setProjectDraft({ ...projectDraft, code: event.target.value })} placeholder="例如：ABC-101" /></label>
              <label>项目名称<input required disabled={!canManageMasterData} value={projectDraft.name} onChange={(event) => setProjectDraft({ ...projectDraft, name: event.target.value })} /></label>
              <label>申办方<input disabled={!canManageMasterData} value={projectDraft.sponsor} onChange={(event) => setProjectDraft({ ...projectDraft, sponsor: event.target.value })} /></label>
              <label>试验盲态控制<select disabled={!canManageMasterData} value={projectDraft.blinding_mode} onChange={(event) => setProjectDraft({ ...projectDraft, blinding_mode: event.target.value as keyof typeof blindingModeLabel })}><option value="open_label">开放标签</option><option value="blinded_with_separation">盲态职责隔离（不揭盲）</option></select></label>
              <label>工作台受试者编号显示<select disabled={!canManageMasterData} value={projectDraft.subject_code_display_mode} onChange={(event) => setProjectDraft({ ...projectDraft, subject_code_display_mode: event.target.value as keyof typeof subjectCodeDisplayModeLabel })}><option value="masked">掩码显示（默认）</option><option value="full">完整显示</option></select></label>
              <button className="button primary" disabled={busy || !canManageMasterData}>保存项目</button>
            </form>}
            {createMode === 'site' && <form className="compact-form" onSubmit={createSite}><label>中心编号<input required disabled={!selectedProjectId || !canManageMasterData} value={siteDraft.code} onChange={(event) => setSiteDraft({ ...siteDraft, code: event.target.value })} placeholder="例如：001" /></label><label>中心名称<input required disabled={!selectedProjectId || !canManageMasterData} value={siteDraft.name} onChange={(event) => setSiteDraft({ ...siteDraft, name: event.target.value })} /></label><label>中心 PI<input disabled={!selectedProjectId || !canManageMasterData} value={siteDraft.pi_name} onChange={(event) => setSiteDraft({ ...siteDraft, pi_name: event.target.value })} /></label><label>方案版本<input disabled={!selectedProjectId || !canManageMasterData} value={siteDraft.protocol_version} onChange={(event) => setSiteDraft({ ...siteDraft, protocol_version: event.target.value })} /></label><label>ICF 版本<input disabled={!selectedProjectId || !canManageMasterData} value={siteDraft.icf_version} onChange={(event) => setSiteDraft({ ...siteDraft, icf_version: event.target.value })} /></label><button className="button primary" disabled={busy || !selectedProjectId || !canManageMasterData}>保存中心</button></form>}
            {createMode === 'visit' && <form className="compact-form" onSubmit={createVisit}>
              <label>访视编号<input required disabled={!selectedSiteId || !canCreateVisit} value={visitDraft.code} onChange={(event) => setVisitDraft({ ...visitDraft, code: event.target.value })} placeholder="例如：IMV-20260810" /></label>
              <label>访视类型<input required disabled={!selectedSiteId || !canCreateVisit} value={visitDraft.visit_type} onChange={(event) => setVisitDraft({ ...visitDraft, visit_type: event.target.value })} /></label>
              <label>监查方式<select disabled={!selectedSiteId || !canCreateVisit} value={visitDraft.visit_method} onChange={(event) => setVisitDraft({ ...visitDraft, visit_method: event.target.value })}><option value="现场">现场</option><option value="远程">远程</option></select></label>
              <label>实际活动开始日期<input disabled={!selectedSiteId || !canCreateVisit} value={visitDraft.activity_start_date} onChange={(event) => setVisitDraft({ ...visitDraft, activity_start_date: event.target.value })} placeholder="YYYY-MM-DD；留空默认同结束日期" /></label>
              <label>实际活动结束日期<input required disabled={!selectedSiteId || !canCreateVisit} value={visitDraft.visit_date} onChange={(event) => setVisitDraft((current) => ({ ...current, visit_date: event.target.value, activity_start_date: !current.activity_start_date || current.activity_start_date === current.visit_date ? event.target.value : current.activity_start_date }))} placeholder="YYYY-MM-DD" /></label>
              <label>报告日期<input disabled={!selectedSiteId || !canCreateVisit} value={visitDraft.report_date} onChange={(event) => setVisitDraft({ ...visitDraft, report_date: event.target.value })} placeholder="YYYY-MM-DD" /></label>
              <label>监查地点 / 远程渠道<input disabled={!selectedSiteId || !canCreateVisit} value={visitDraft.visit_location} onChange={(event) => setVisitDraft({ ...visitDraft, visit_location: event.target.value })} placeholder="例如：中心会议室 / Teams" /></label>
              <label>本次接触人员<input disabled={!selectedSiteId || !canCreateVisit} value={visitDraft.contact_persons} onChange={(event) => setVisitDraft({ ...visitDraft, contact_persons: event.target.value })} placeholder="例如：PI、CRC、研究护士" /></label>
              <div className={`template-match-recommendation ${recommendedTemplate ? `confidence-${recommendedTemplate.confidence}` : ''}`}>
                <div>
                  <span className="template-match-kicker">报告模板匹配</span>
                  {templateMatchLoading ? <strong>正在比对已启用 Word 模板特征…</strong> : recommendedTemplate ? <><strong>系统推荐：{recommendedTemplate.template.name} · {recommendedTemplate.template.version}</strong><p>{recommendedTemplate.reasons[0]}</p></> : <strong>输入访视类型后，系统将在已启用模板中进行匹配</strong>}
                </div>
                {recommendedTemplate && <div className="template-match-recommendation-actions">
                  <span className={`template-match-confidence ${recommendedTemplate.confidence}`}>{templateMatchConfidenceLabel[recommendedTemplate.confidence]}</span>
                  <small>{recommendedTemplate.score} 分{recommendedTemplate.matched_terms.length ? ` · 命中：${recommendedTemplate.matched_terms.join('、')}` : ''}</small>
                  <button type="button" className="button small" disabled={busy || !canCreateVisit || visitDraft.template_id === recommendedTemplate.template.id} onClick={adoptRecommendedTemplate}>{visitDraft.template_id === recommendedTemplate.template.id ? '已采用，可改选' : '采纳该模板'}</button>
                </div>}
              </div>
              <label>报告模板<select required disabled={!selectedSiteId || !canCreateVisit || templates.length === 0} value={visitDraft.template_id || templates[0]?.id || ''} onChange={(event) => { autoMatchedTemplateId.current = ''; setVisitDraft({ ...visitDraft, template_id: event.target.value }) }}>{templates.length === 0 ? <option value="">请先登记模板</option> : templates.map((template) => <option key={template.id} value={template.id}>{template.name} · {template.version}</option>)}</select><small className="template-selection-note">系统推荐仅作辅助，CRA 可按本次访视实际情况改选。</small></label>
              <label className="rule-selection-field">冻结规则包
                <select required disabled={!selectedSiteId || !canCreateVisit || !visitDraft.visit_date.trim() || eligibleRulePacks.length === 0} value={visitDraft.rule_pack_id} onChange={(event) => setVisitDraft({ ...visitDraft, rule_pack_id: event.target.value })}>
                  <option value="">{!visitDraft.visit_date.trim() ? '请先填写访视日期' : eligibleRulePacks.length === 0 ? '该日期没有适用的已启用规则包' : '请选择规则包'}</option>
                  {rulePacks.map((rulePack) => <option key={rulePack.id} value={rulePack.id} disabled={!rulePack.eligibility?.selectable}>{rulePack.name} · {rulePack.version} · {ruleEligibilityLabel[rulePack.eligibility?.status ?? 'visit_date_required']}</option>)}
                </select>
                <small className={selectedRulePack?.eligibility?.expires_soon ? 'rule-eligibility-note warning' : 'rule-eligibility-note'}>{selectedRulePack?.eligibility?.message ?? (!visitDraft.visit_date.trim() ? '填写日期后将自动匹配规则包有效期。' : '只展示对该访视日期适用的已启用规则包。')}</small>
              </label>
              <label>CRA<input disabled={!selectedSiteId || !canCreateVisit} value={visitDraft.cra_name} onChange={(event) => setVisitDraft({ ...visitDraft, cra_name: event.target.value })} /></label>
              {projectControlDraft.blinding_mode === 'blinded_with_separation' && <div className="blinded-visit-note"><strong>盲态职责隔离</strong><span>本访视会冻结“系统不揭盲”边界；请勿录入治疗分组或其他盲态信息。</span></div>}
              <button className="button primary" disabled={busy || !canCreateVisit || !selectedSiteId || templates.length === 0 || eligibleRulePacks.length === 0 || !visitDraft.rule_pack_id}>创建并打开</button>
            </form>}
          </section>

          {selectedProject && <ImportQualityPanel projectId={selectedProject.id} refreshToken={importQualityRefreshToken} />}

          <ImportPanel projectId={selectedProjectId} siteId={selectedSiteId} canManage={canManageMasterData} externalReadOnlyAdapter={selectedExternalReadOnlyAdapter} importProfiles={selectedMasterDataImportProfiles} onImported={() => { setImportQualityRefreshToken((value) => value + 1); void refreshPortfolio() }} onNotice={onNotice} />
        </div>
      </div>
    </div>
  )
}
