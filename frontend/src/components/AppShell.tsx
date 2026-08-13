import type { DemoState, PageKey } from '../types'
import { reportStatusLabel, workflowStageLabel } from '../api'

interface AppShellProps {
  state: DemoState
  page: PageKey
  onPageChange: (page: PageKey) => void
  onReset: () => void
  children: React.ReactNode
}

const navItems: Array<{ key: PageKey; label: string; code: string }> = [
  { key: 'portfolio', label: '项目组合', code: '01' },
  { key: 'templates', label: '模板库', code: '02' },
  { key: 'overview', label: '项目概览', code: '03' },
  { key: 'quick_note', label: '现场速记', code: '04' },
  { key: 'history_insights', label: '历史洞察', code: '05' },
  { key: 'workbench', label: '监查工作台', code: '06' },
  { key: 'report', label: '报告生成', code: '07' },
  { key: 'review', label: '审核中心', code: '08' },
  { key: 'collaboration', label: '协作中心', code: '09' },
  { key: 'governance', label: '规则与归档', code: '10' },
]

const pageDescriptions: Record<PageKey, string> = {
  portfolio: '项目、中心与访视的统一台账；打开一个访视后继续监查工作',
  templates: '上传、识别并确认监查报告 Word 模板的表格映射',
  overview: '固定信息、访视信息与 15 张表映射进度',
  quick_note: '窄屏可快速记录、离线暂存并同步现场监查工作底稿',
  history_insights: '同一项目历史报告、重复问题与未关闭行动项的只读回看',
  workbench: 'CRA 碎片化记录、建议确认与任务归类',
  report: '基于 UA007 固定模板生成真实 Word 报告',
  review: 'PM / LM 审核意见、退回与批准',
  collaboration: '离线同步、行动项提醒、团队交接与访视时间线',
  governance: '规则包冻结、受控语言、审计证据链与系统外签署交接',
}

const roleLabel = (role: DemoState['current_role']) => role === 'CRA'
  ? 'CRA'
  : role === 'PM_LM'
    ? 'PM / LM'
    : role === 'QA_CLINICAL_OPS'
      ? 'QA / 临床运营审批人'
      : role === 'MEDICAL_DATA_REVIEWER'
        ? '医学监察 / 数据管理'
        : '项目管理员'

export function AppShell({ state, page, onPageChange, onReset, children }: AppShellProps) {
  const confirmed = state.table_tasks.filter((item) => item.status === '已确认' || item.status === '已映射').length
  const workflowStage = state.workflow_stage ?? (state.report_status === 'submitted' ? 'under_review' : state.report_status)

  return (
    <div className="app-frame">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">M</span>
          <div>
            <div className="brand-name">监查 Mentor</div>
            <div className="brand-subtitle">Clinical Operations Workspace</div>
          </div>
        </div>
        <div className="topbar-context">
          <span className="context-project">{state.project.study_id}</span>
          <span className="topbar-divider" />
          <span>{state.visit.visit_type}</span>
          <span className={`workflow-stage stage-${workflowStage}`}>{workflowStageLabel[workflowStage]}</span>
          <span className={`report-status status-${state.report_status}`}>{reportStatusLabel[state.report_status]}</span>
        </div>
      </header>

      <div className="workspace-layout">
        <aside className="sidebar" aria-label="主要功能导航">
          <div className="sidebar-section-label">工作区</div>
          <nav className="navigation-list">
            {navItems.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`nav-item ${page === item.key ? 'is-active' : ''}`}
                onClick={() => onPageChange(item.key)}
              >
                <span className="nav-code">{item.code}</span>
                <span>{item.label}</span>
              </button>
            ))}
          </nav>

          <div className="sidebar-rule" />
          <div className="sidebar-section-label">当前访视</div>
          <dl className="visit-facts">
            <div>
              <dt>中心</dt>
              <dd>{state.project.site_name}</dd>
            </div>
            <div>
              <dt>CRA</dt>
              <dd>{state.visit.cra_name}</dd>
            </div>
            <div>
              <dt>表格映射</dt>
              <dd>{confirmed} / {state.table_tasks.length}</dd>
            </div>
            <div>
              <dt>报告阶段</dt>
              <dd>{workflowStageLabel[workflowStage]}</dd>
            </div>
            <div>
              <dt>当前角色</dt>
              <dd>{roleLabel(state.current_role)}</dd>
            </div>
          </dl>

          <div className="sidebar-footer">
            <p>本地演示数据</p>
            <button type="button" className="button-link subtle" onClick={onReset}>恢复演示初始状态</button>
          </div>
        </aside>

        <main className="main-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">{state.project.study_name}</p>
              <h1>{navItems.find((item) => item.key === page)?.label}</h1>
              <p className="page-description">{pageDescriptions[page]}</p>
            </div>
            <div className="visit-stamp">
              <span>监查日期</span>
              <strong>{state.visit.visit_date}</strong>
            </div>
          </div>
          {children}
        </main>
      </div>
    </div>
  )
}
