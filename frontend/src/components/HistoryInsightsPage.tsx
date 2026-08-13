import { useEffect, useMemo, useState } from 'react'
import { api, reportStatusLabel } from '../api'
import type { DemoState, HistoryOpenAction, HistoryReportItem, ProjectHistoryInsights, RepeatedHistoryFinding } from '../types'

interface HistoryInsightsPageProps {
  state: DemoState
  onOpenVisit: (visitId: string) => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

type ScopeMode = 'site' | 'project'

const categoryLabel = (category: string) => {
  if (category === 'sae') return 'SAE'
  if (category === 'ae') return 'AE'
  if (category === 'deviation') return '方案偏离'
  return category || '监查发现'
}

const actionStatusLabel: Record<HistoryOpenAction['status'], string> = {
  open: '待跟进',
  in_progress: '跟进中',
}

const reportLabel = (report: HistoryReportItem) => `${report.revision_type === 'formal' ? '正式' : '工作'} · ${reportStatusLabel[report.revision_status] ?? report.revision_status}`

const sourceSummary = (finding: RepeatedHistoryFinding) => {
  const latest = finding.source_visits[0]
  if (!latest) return '暂无来源访视'
  return `${latest.site_code} · ${latest.visit_code} · ${latest.visit_date}`
}

export function HistoryInsightsPage({ state, onOpenVisit, onNotice }: HistoryInsightsPageProps) {
  const projectId = state.visit.project_id ?? ''
  const currentSiteId = state.visit.site_id ?? ''
  const [scopeMode, setScopeMode] = useState<ScopeMode>('site')
  const [insights, setInsights] = useState<ProjectHistoryInsights | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expandedFindingKeys, setExpandedFindingKeys] = useState<string[]>([])

  const scopeSiteId = scopeMode === 'site' ? currentSiteId : ''

  const loadInsights = async () => {
    if (!projectId) {
      setInsights(null)
      return
    }
    try {
      setLoading(true)
      setError('')
      setInsights(await api.getProjectHistoryInsights(projectId, scopeSiteId))
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : '历史洞察加载失败'
      setError(message)
      onNotice(message, 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadInsights() }, [projectId, scopeSiteId])

  const scopeTitle = useMemo(() => {
    if (scopeMode === 'project') return '项目全部中心'
    return state.project.site_name || '当前中心'
  }, [scopeMode, state.project.site_name])

  const toggleFinding = (key: string) => {
    setExpandedFindingKeys((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])
  }

  return (
    <div className="history-insights-stack">
      <section className="section-block history-insights-brief">
        <div>
          <p className="eyebrow">PROJECT HISTORY / READ ONLY</p>
          <h2>历史洞察</h2>
          <p>聚合已留存的项目访视、报告、发现和行动项，帮助本次监查前回看既往问题。所有数据均为只读，不会自动改变发现、严重程度或历史报告。</p>
        </div>
        <div className="history-scope-switch" aria-label="历史洞察范围">
          <button type="button" className={scopeMode === 'site' ? 'is-active' : ''} onClick={() => setScopeMode('site')}>当前中心</button>
          <button type="button" className={scopeMode === 'project' ? 'is-active' : ''} onClick={() => setScopeMode('project')}>项目全部中心</button>
        </div>
      </section>

      <section className="section-block history-insights-context">
        <div className="section-header compact-header">
          <div><h2>{scopeTitle}</h2><p>统计截至 {insights?.scope.as_of ?? '—'}；重复问题仅按“类别 + 规范化后的相同事实描述”精确匹配。</p></div>
          <button type="button" className="button quiet small" disabled={loading} onClick={() => void loadInsights()}>{loading ? '正在刷新…' : '刷新'}</button>
        </div>
        {error && <p className="history-error">{error}</p>}
        <dl className="history-metrics">
          <div><dt>范围访视</dt><dd>{insights?.scope.visit_count ?? '—'}</dd></div>
          <div><dt>正式报告</dt><dd>{insights?.scope.formal_report_count ?? '—'}</dd></div>
          <div><dt>重复问题</dt><dd>{insights?.scope.repeated_finding_count ?? '—'}</dd></div>
          <div><dt>未关闭行动项</dt><dd>{insights?.scope.open_action_count ?? '—'}</dd></div>
          <div className={insights?.scope.overdue_action_count ? 'is-overdue' : ''}><dt>其中逾期</dt><dd>{insights?.scope.overdue_action_count ?? '—'}</dd></div>
        </dl>
      </section>

      <section className="section-block history-section">
        <div className="section-header compact-header"><div><h2>重复问题</h2><p>仅显示在当前范围出现至少两次的相同问题；这是复核提示，不代表系统对根因或风险做出判断。</p></div><span className="section-code">REPEAT</span></div>
        {!loading && (insights?.repeated_findings.length ?? 0) === 0 && <div className="empty-state inline"><span>当前范围尚未发现可按精确事实匹配的重复问题。</span></div>}
        <div className="history-finding-list">
          {insights?.repeated_findings.map((finding) => {
            const expanded = expandedFindingKeys.includes(finding.key)
            return <article key={finding.key} className="history-finding-row">
              <div className="history-finding-summary">
                <div><span className="history-category">{categoryLabel(finding.category)}</span><strong>{finding.description}</strong><p>最近来源：{sourceSummary(finding)} · {finding.site_count} 个中心 / {finding.count} 次记录</p></div>
                <button type="button" className="button quiet small" onClick={() => toggleFinding(finding.key)}>{expanded ? '收起来源' : `查看 ${finding.count} 条来源`}</button>
              </div>
              {expanded && <div className="history-source-list">
                {finding.source_visits.map((source) => <div key={source.finding_id} className="history-source-row"><div><strong>{source.site_code} · {source.visit_code}</strong><span>{source.visit_date} · {source.status || '已留存'}</span></div><button type="button" className="text-action" onClick={() => onOpenVisit(source.visit_id)}>打开访视</button></div>)}
              </div>}
            </article>
          })}
        </div>
      </section>

      <section className="section-block history-section">
        <div className="section-header compact-header"><div><h2>未关闭行动项</h2><p>按逾期、计划完成日和来源访视排序。需要带入本次跟进时，请在来源或当前访视的行动项流程中由 CRA 执行。</p></div><span className="section-code">ACTION</span></div>
        {!loading && (insights?.open_actions.length ?? 0) === 0 && <div className="empty-state inline"><span>当前范围没有未关闭行动项。</span></div>}
        <div className="history-action-list">
          {insights?.open_actions.map((action) => <article key={action.id} className={`history-action-row ${action.is_overdue ? 'is-overdue' : ''}`}>
            <div><span className="history-action-status">{action.is_overdue ? '已逾期' : actionStatusLabel[action.status]}</span><strong>{action.title}</strong><p>{action.description}</p><small>{action.site_code} · {action.visit_code} · {action.visit_date} · 责任人：{action.owner || '待指定'}{action.due_date ? ` · 计划完成：${action.due_date}` : ' · 未填计划完成日'}</small></div>
            <button type="button" className="button quiet small" onClick={() => onOpenVisit(action.visit_id)}>打开访视</button>
          </article>)}
        </div>
      </section>

      <section className="section-block history-section">
        <div className="section-header compact-header"><div><h2>报告台账</h2><p>工作修订与正式提交版本均保留；此处仅用于定位来源，不替代系统外签署或归档流程。</p></div><span className="section-code">REPORT</span></div>
        {!loading && (insights?.reports.length ?? 0) === 0 && <div className="empty-state inline"><span>当前范围尚无已生成报告修订。</span></div>}
        <div className="history-report-list">
          {insights?.reports.map((report) => <article key={report.id} className="history-report-row"><div><strong>{report.site_code} · {report.visit_code}</strong><span>{report.visit_type} · {report.visit_date} · {report.version_number} · {reportLabel(report)}</span><small>{report.file_name || '尚未写入文件名'}{report.generated_at ? ` · 生成：${report.generated_at}` : ''}</small></div><button type="button" className="button quiet small" onClick={() => onOpenVisit(report.visit_id)}>打开访视</button></article>)}
        </div>
      </section>
    </div>
  )
}
