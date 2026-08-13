import { useEffect, useState } from 'react'
import { api } from '../api'
import type { ImportQualitySummary } from '../types'

interface ImportQualityPanelProps {
  projectId: string
  refreshToken: number
}

const scopeLabel: Record<string, string> = {
  projects: '项目',
  sites: '中心与固定资料',
  subjects: '受试者编号',
}

export function ImportQualityPanel({ projectId, refreshToken }: ImportQualityPanelProps) {
  const [summary, setSummary] = useState<ImportQualitySummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    const load = async () => {
      try {
        setLoading(true)
        setError('')
        const result = await api.getProjectImportQuality(projectId)
        if (!cancelled) setSummary(result)
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : '导入质量台账加载失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [projectId, refreshToken, reload])

  const totals = summary?.summary
  return <section className="section-block import-quality-panel">
    <div className="section-header compact-header"><div><h2>主数据导入质量台账</h2><p>按当前项目汇总既有预检和确认写入批次，用于人工观察数据准备质量；不触发自动导入。</p></div><div className="import-quality-header-actions"><span className="section-code">QUALITY LEDGER</span><button type="button" className="button quiet small" disabled={loading} onClick={() => setReload((value) => value + 1)}>{loading ? '正在刷新…' : '刷新台账'}</button></div></div>
    {error && <p className="import-quality-error">{error}</p>}
    {!error && !summary && <p className="import-quality-loading">{loading ? '正在汇总导入批次…' : '暂无导入批次。'}</p>}
    {summary && totals && <>
      <div className="import-quality-summary"><div><span>累计批次</span><strong>{totals.total_batches}</strong><small>已确认 {totals.committed_batches} 批</small></div><div><span>预检有效行</span><strong>{totals.valid_rows}</strong><small>总行数 {totals.total_rows}</small></div><div><span>预检通过率</span><strong>{totals.quality_rate}%</strong><small>需处理 {totals.skipped_rows} 行</small></div><div><span>待确认批次</span><strong>{totals.previewed_batches}</strong><small>来源留痕 {totals.source_traced_batches} 批</small></div></div>
      <div className="import-quality-context"><span>最近确认导入：<strong>{summary.last_imported_at || '暂无'}</strong></span><span>该台账按预检结果统计；确认写入后的实际新增与更新见各批次明细。</span></div>
      <div className="import-quality-ledger">
        <div className="data-table-wrap"><table className="data-table"><thead><tr><th>导入对象</th><th>批次</th><th>有效 / 总行</th><th>需处理</th><th>预检通过率</th></tr></thead><tbody>{summary.scope_summary.length === 0 ? <tr><td colSpan={5} className="muted-cell">暂无按对象汇总数据</td></tr> : summary.scope_summary.map((item) => <tr key={item.scope}><td><strong>{scopeLabel[item.scope] ?? item.scope}</strong></td><td className="tabular">{item.batch_count}</td><td className="tabular">{item.valid_rows} / {item.total_rows}</td><td className="tabular">{item.skipped_rows}</td><td className="tabular">{item.quality_rate}%</td></tr>)}</tbody></table></div>
        <div className="import-quality-recent"><div className="import-quality-recent-heading"><strong>最近批次</strong><small>仅展示本项目最近 12 次导入</small></div>{summary.batches.length === 0 ? <p>暂无导入批次。</p> : summary.batches.map((batch) => <article key={batch.id}><div><strong>{batch.file_name}</strong><span>{scopeLabel[batch.scope] ?? batch.scope} · {batch.status === 'committed' ? '已确认写入' : '待确认写入'} · {batch.created_at}</span></div><div><em className={batch.quality_rate < 100 ? 'has-errors' : ''}>{batch.valid_rows} / {batch.total_rows} · {batch.quality_rate}%</em><small>{batch.import_profile_name ? `配置：${batch.import_profile_name}` : '未使用已保存配置'}{batch.source_system ? ` · ${batch.source_system}` : ''}</small></div></article>)}</div>
      </div>
    </>}
  </section>
}
