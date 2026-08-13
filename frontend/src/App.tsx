import { useEffect, useState } from 'react'
import { api } from './api'
import { AppShell } from './components/AppShell'
import { CollaborationPage } from './components/CollaborationPage'
import { GovernancePage } from './components/GovernancePage'
import { HistoryInsightsPage } from './components/HistoryInsightsPage'
import { OverviewPage } from './components/OverviewPage'
import { PortfolioPage } from './components/PortfolioPage'
import { QuickNotePage } from './components/QuickNotePage'
import { ReportPage } from './components/ReportPage'
import { ReviewPage } from './components/ReviewPage'
import { TemplatesPage } from './components/TemplatesPage'
import { WorkbenchPage } from './components/WorkbenchPage'
import type { DemoState, PageKey } from './types'

interface Notice {
  message: string
  tone: 'success' | 'error'
}

export default function App() {
  const [state, setState] = useState<DemoState | null>(null)
  const [page, setPage] = useState<PageKey>('portfolio')
  const [notice, setNotice] = useState<Notice | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const notify = (message: string, tone: 'success' | 'error' = 'success') => {
    setNotice({ message, tone })
    window.setTimeout(() => setNotice(null), 3600)
  }

  const load = async () => {
    try {
      setLoadError(null)
      setState(await api.getState())
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : '无法连接本地后端')
    }
  }

  useEffect(() => { void load() }, [])

  const reset = async () => {
    try {
      setState(await api.reset())
      setPage('portfolio')
      notify('已恢复本地演示初始状态。')
    } catch (error) {
      notify(error instanceof Error ? error.message : '恢复失败', 'error')
    }
  }

  if (loadError) {
    return <div className="connection-state"><div><h1>无法连接本地服务</h1><p>{loadError}</p><button type="button" className="button primary" onClick={() => void load()}>重新连接</button></div></div>
  }

  if (!state) {
    return <div className="connection-state"><div><p className="eyebrow">MONITORING MENTOR</p><h1>正在载入监查工作区</h1><p>连接本地演示数据…</p></div></div>
  }

  const commonProps = { state, onStateChange: setState, onNotice: notify }
  const openHistoricalVisit = async (visitId: string) => {
    try {
      setState(await api.getState(visitId))
      setPage('overview')
      notify('已打开来源访视，可继续查看其工作底稿与报告状态。')
    } catch (error) {
      notify(error instanceof Error ? error.message : '打开来源访视失败', 'error')
    }
  }
  const pageContent = {
    portfolio: <PortfolioPage {...commonProps} onOpenWorkspace={() => setPage('overview')} />,
    templates: <TemplatesPage currentRole={state.current_role} onNotice={notify} />,
    overview: <OverviewPage {...commonProps} />,
    quick_note: <QuickNotePage {...commonProps} />,
    history_insights: <HistoryInsightsPage state={state} onOpenVisit={(visitId) => void openHistoricalVisit(visitId)} onNotice={notify} />,
    workbench: <WorkbenchPage {...commonProps} />,
    report: <ReportPage {...commonProps} />,
    review: <ReviewPage {...commonProps} />,
    collaboration: <CollaborationPage {...commonProps} />,
    governance: <GovernancePage state={state} onNotice={notify} />,
  }[page]

  return (
    <>
      <AppShell state={state} page={page} onPageChange={setPage} onReset={() => void reset()}>{pageContent}</AppShell>
      {notice && <div className={`toast ${notice.tone}`} role="status">{notice.message}</div>}
    </>
  )
}
