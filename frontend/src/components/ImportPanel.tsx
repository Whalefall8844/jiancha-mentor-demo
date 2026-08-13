import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { api } from '../api'
import { externalReadOnlySystemLabel, type ExternalReadOnlyAdapterConfig } from '../externalReadOnlyAdapter'
import { masterDataImportCadenceLabel, masterDataImportScheduleStatus, masterDataImportScopeCopy, type MasterDataImportProfile } from '../masterDataImportProfiles'
import type { ImportBatch } from '../types'

type ImportScope = 'projects' | 'sites' | 'subjects'

interface ImportPanelProps {
  projectId: string
  siteId: string
  canManage: boolean
  externalReadOnlyAdapter?: ExternalReadOnlyAdapterConfig
  importProfiles?: MasterDataImportProfile[]
  onImported: () => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

const scopeCopy = masterDataImportScopeCopy

export function ImportPanel({ projectId, siteId, canManage, externalReadOnlyAdapter, importProfiles = [], onImported, onNotice }: ImportPanelProps) {
  const [scope, setScope] = useState<ImportScope>('sites')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportBatch | null>(null)
  const [busy, setBusy] = useState(false)
  const [sourceReference, setSourceReference] = useState('')
  const [sourceExportedAt, setSourceExportedAt] = useState('')
  const [selectedProfileId, setSelectedProfileId] = useState('')
  const copy = useMemo(() => scopeCopy[scope], [scope])
  const selectedProfile = importProfiles.find((profile) => profile.id === selectedProfileId)

  useEffect(() => {
    setSourceReference(externalReadOnlyAdapter?.default_export_reference ?? '')
    setSourceExportedAt('')
  }, [externalReadOnlyAdapter?.enabled, externalReadOnlyAdapter?.default_export_reference, externalReadOnlyAdapter?.system])

  useEffect(() => {
    if (selectedProfileId && !importProfiles.some((profile) => profile.id === selectedProfileId)) setSelectedProfileId('')
  }, [importProfiles, selectedProfileId])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!canManage) {
      onNotice('批量导入与主数据维护由项目管理员完成。', 'error')
      return
    }
    if (!file) {
      onNotice('请先选择 CSV 或 Excel 文件。', 'error')
      return
    }
    try {
      setBusy(true)
      const source = externalReadOnlyAdapter?.enabled
        ? {
          system: externalReadOnlyAdapter.system,
          reference: sourceReference.trim() || externalReadOnlyAdapter.default_export_reference.trim(),
          exported_at: sourceExportedAt.trim(),
        }
        : undefined
      const result = await api.previewMasterDataImport(scope, file, projectId, siteId, source, selectedProfile
        ? { id: selectedProfile.id, name: selectedProfile.name, column_mapping: selectedProfile.column_mapping }
        : undefined)
      setPreview(result)
      const { created, updated, valid, skipped } = result.preview_summary
      onNotice(`预检完成：可写入 ${valid} 行（新增 ${created}，更新 ${updated}）${skipped ? `，${skipped} 行需处理` : ''}。`, skipped ? 'error' : 'success')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '导入失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const commit = async () => {
    if (!preview || !canManage) return
    try {
      setBusy(true)
      const result = await api.commitMasterDataImport(preview.id)
      setPreview(result)
      onImported()
      const { created = 0, updated = 0, skipped = 0 } = result.committed_summary
      onNotice(`已确认写入${copy.label}：新增 ${created}，更新 ${updated}${skipped ? `，跳过 ${skipped}` : ''}。`, skipped ? 'error' : 'success')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '确认写入失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const downloadErrorReport = async () => {
    if (!preview) return
    try {
      setBusy(true)
      const fileName = await api.downloadImportErrorReport(preview.id)
      onNotice(`已下载错误行报告：${fileName}`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '错误行报告下载失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="section-block import-panel">
      <div className="section-header"><div><h2>批量导入主数据</h2><p>支持 `.csv`、`.tsv`、`.xlsx`、`.xlsm`；系统只写入当前授权范围的演示数据。</p></div><span className="section-code">IMPORT</span></div>
      <form className="import-form" onSubmit={submit}>
        <div className="import-scope-list" role="radiogroup" aria-label="导入类型">
          {(Object.keys(scopeCopy) as ImportScope[]).map((item) => <label key={item} className={scope === item ? 'is-selected' : ''}><input type="radio" name="import-scope" value={item} disabled={!canManage} checked={scope === item} onChange={() => { setScope(item); setPreview(null) }} /><strong>{scopeCopy[item].label}</strong><span>{scopeCopy[item].description}</span></label>)}
        </div>
        {importProfiles.length > 0 && <div className="import-profile-select-row">
          <label>复用已保存配置<select disabled={!canManage || busy} value={selectedProfileId} onChange={(event) => {
            const profile = importProfiles.find((item) => item.id === event.target.value)
            setSelectedProfileId(event.target.value)
            if (profile) {
              setScope(profile.scope)
              setPreview(null)
            }
          }}><option value="">不使用已保存配置（按当前选择导入）</option>{importProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {scopeCopy[profile.scope].label}</option>)}</select></label>
          {selectedProfile && <div className="import-profile-selected-note"><strong>{Object.keys(selectedProfile.column_mapping).length ? `将使用 ${Object.keys(selectedProfile.column_mapping).length} 个字段预映射` : '将使用系统内置列名识别'}</strong><span>{masterDataImportCadenceLabel[selectedProfile.cadence]} · {masterDataImportScheduleStatus(selectedProfile.next_expected_date).label}{selectedProfile.note ? ` · ${selectedProfile.note}` : ''}</span></div>}
        </div>}
        <div className="import-upload-row">
          <label className="file-field">选择文件<input type="file" disabled={!canManage} accept=".csv,.tsv,.xlsx,.xlsm" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><small>{file ? file.name : '尚未选择文件'}</small></label>
          <div className="import-guide"><strong>推荐列名</strong><code>{copy.columns}</code></div>
          <button type="submit" className="button secondary" disabled={busy || !file || !canManage}>{busy ? '正在预检…' : `预检${copy.label}`}</button>
        </div>
        {externalReadOnlyAdapter?.enabled && <div className="external-import-source">
          <div><strong>{externalReadOnlySystemLabel(externalReadOnlyAdapter.system)} 手工导出来源</strong><small>{externalReadOnlyAdapter.display_name || '未命名来源'}；仅写入本次导入批次和后续审计记录，不连接或回写外部系统。</small></div>
          <label>导出标识<input disabled={!canManage || busy} value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} placeholder="例如：CTMS-MD-20260812" /></label>
          <label>导出时间<input type="datetime-local" disabled={!canManage || busy} value={sourceExportedAt} onChange={(event) => setSourceExportedAt(event.target.value)} /></label>
        </div>}
      </form>
      {!canManage && <p className="import-readonly">当前角色仅可查看导入字段说明；预检和确认写入由项目管理员执行。</p>}
      {preview && <div className="import-preview">
        <div className="import-preview-header"><div><strong>{preview.status === 'committed' ? '本批次已写入' : '预检结果：等待确认写入'}</strong><span>{preview.file_name} · 批次 {preview.id.slice(0, 8)}{preview.import_profile_name ? ` · 配置 ${preview.import_profile_name}` : ''}{preview.source_system ? ` · 来源 ${preview.source_system}${preview.source_reference ? ` / ${preview.source_reference}` : ''}${preview.source_exported_at ? ` / ${preview.source_exported_at}` : ''}` : ''}</span></div><div className="import-preview-actions">{preview.preview_summary.skipped > 0 && <button type="button" className="button quiet" disabled={busy} onClick={() => void downloadErrorReport()}>下载错误行 CSV</button>}{preview.status === 'previewed' && <button type="button" className="button primary" disabled={busy || preview.preview_summary.valid === 0 || !canManage} onClick={() => void commit()}>{busy ? '正在写入…' : `确认写入 ${preview.preview_summary.valid} 条有效行`}</button>}</div></div>
        <div className="import-preview-summary"><div><span>总行数</span><strong>{preview.preview_summary.total}</strong></div><div><span>新增</span><strong>{preview.preview_summary.created}</strong></div><div><span>更新</span><strong>{preview.preview_summary.updated}</strong></div><div><span>需处理</span><strong>{preview.preview_summary.skipped}</strong></div></div>
        <div className="data-table-wrap import-preview-table"><table className="data-table"><thead><tr><th>行</th><th>预检操作</th><th>对象</th><th>说明</th></tr></thead><tbody>{preview.rows.map((row) => <tr key={row.id}><td className="tabular">{row.row_number}</td><td><span className={`import-action ${row.action}`}>{row.action === 'create' ? '新增' : row.action === 'update' ? '更新' : '跳过'}</span></td><td>{row.entity_type}</td><td className={row.error_message ? 'import-error' : 'muted-cell'}>{row.error_message || '已通过预检'}</td></tr>)}</tbody></table></div>
      </div>}
    </section>
  )
}
