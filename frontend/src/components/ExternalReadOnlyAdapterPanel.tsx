import { useEffect, useState } from 'react'
import { api } from '../api'
import { externalReadOnlyAdapterMetadataWith, externalReadOnlySystemLabel, readExternalReadOnlyAdapter, type ExternalReadOnlyAdapterConfig } from '../externalReadOnlyAdapter'
import type { ProjectSummary } from '../types'

interface ExternalReadOnlyAdapterPanelProps {
  project: ProjectSummary
  canManage: boolean
  onChanged: () => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

export function ExternalReadOnlyAdapterPanel({ project, canManage, onChanged, onNotice }: ExternalReadOnlyAdapterPanelProps) {
  const [draft, setDraft] = useState<ExternalReadOnlyAdapterConfig>(() => readExternalReadOnlyAdapter(project.metadata))
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setDraft(readExternalReadOnlyAdapter(project.metadata))
  }, [project.id, project.metadata])

  const save = async () => {
    if (!canManage) return
    try {
      setSaving(true)
      await api.patchProject(project.id, {
        metadata: externalReadOnlyAdapterMetadataWith(project.metadata, draft),
      })
      onChanged()
      onNotice(draft.enabled
        ? `已配置 ${externalReadOnlySystemLabel(draft.system)} 只读导入沙箱；后续仍需手工上传导出文件并确认写入。`
        : '已停用外部只读导入沙箱；既有导入批次和主数据不会被改写。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '外部只读适配配置保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  return <section className="section-block external-readonly-adapter-panel">
    <div className="section-header compact-header"><div><h2>CTMS / eTMF 只读适配沙箱</h2><p>用于记录手工导出来源并复用主数据预检；本地 Demo 不保存账号、不连接、轮询或写回外部系统。</p></div><span className="section-code">READ ONLY</span></div>
    <div className="external-readonly-adapter-content">
      <div className={`external-readonly-adapter-status ${draft.enabled ? 'is-enabled' : ''}`}><strong>{draft.enabled ? `${externalReadOnlySystemLabel(draft.system)} 手工导出已启用` : '未启用外部导出来源'}</strong><span>{draft.enabled ? `${draft.display_name || '未命名来源'}：文件仍须由管理员手工上传、预检并确认写入。` : '可先配置一个演示来源；未启用时，仍可使用普通 Excel / CSV 导入。'}</span></div>
      <div className="external-readonly-adapter-form">
        <label className="external-readonly-toggle"><input type="checkbox" checked={draft.enabled} disabled={!canManage || saving} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} /><span>本项目使用只读导出沙箱</span></label>
        <label>来源系统<select value={draft.system} disabled={!canManage || saving} onChange={(event) => setDraft({ ...draft, system: event.target.value as ExternalReadOnlyAdapterConfig['system'] })}><option value="CTMS">CTMS</option><option value="eTMF">eTMF</option><option value="CTMS_eTMF">CTMS + eTMF</option></select></label>
        <label>来源名称<input value={draft.display_name} disabled={!canManage || saving} onChange={(event) => setDraft({ ...draft, display_name: event.target.value })} placeholder="例如：申办方 CTMS 每周中心主数据导出" /></label>
        <label>默认导出标识<input value={draft.default_export_reference} disabled={!canManage || saving} onChange={(event) => setDraft({ ...draft, default_export_reference: event.target.value })} placeholder="例如：CTMS-MD-20260812" /></label>
        <label className="external-readonly-note">说明<textarea value={draft.note} disabled={!canManage || saving} onChange={(event) => setDraft({ ...draft, note: event.target.value })} placeholder="例如：仅允许导入中心、受试者编号和受控文件版本清单" /></label>
        <button type="button" className="button quiet small" disabled={!canManage || saving} onClick={() => void save()}>{saving ? '正在保存…' : '保存只读来源配置'}</button>
      </div>
    </div>
  </section>
}
