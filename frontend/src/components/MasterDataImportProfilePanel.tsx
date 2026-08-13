import { useEffect, useState } from 'react'
import { api } from '../api'
import {
  blankMasterDataImportProfile,
  masterDataImportCadenceLabel,
  masterDataImportProfileFields,
  masterDataImportProfilesMetadataWith,
  masterDataImportScheduleStatus,
  masterDataImportScopeCopy,
  readMasterDataImportProfiles,
  type MasterDataImportProfile,
  type MasterDataImportScope,
} from '../masterDataImportProfiles'
import type { ProjectSummary } from '../types'

interface MasterDataImportProfilePanelProps {
  project: ProjectSummary
  canManage: boolean
  onChanged: () => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

export function MasterDataImportProfilePanel({ project, canManage, onChanged, onNotice }: MasterDataImportProfilePanelProps) {
  const [profiles, setProfiles] = useState<MasterDataImportProfile[]>(() => readMasterDataImportProfiles(project.metadata))
  const [draft, setDraft] = useState<MasterDataImportProfile | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setProfiles(readMasterDataImportProfiles(project.metadata))
    setDraft(null)
  }, [project.id, project.metadata])

  const save = async () => {
    if (!draft || !canManage) return
    const normalized: MasterDataImportProfile = {
      ...draft,
      name: draft.name.trim() || `${masterDataImportScopeCopy[draft.scope].label}导入配置`,
      note: draft.note.trim(),
      next_expected_date: draft.next_expected_date.trim(),
      column_mapping: Object.fromEntries(Object.entries(draft.column_mapping).filter(([key, value]) => key.trim() && value.trim())),
    }
    const exists = profiles.some((profile) => profile.id === normalized.id)
    const next = exists ? profiles.map((profile) => profile.id === normalized.id ? normalized : profile) : [...profiles, normalized]
    try {
      setSaving(true)
      await api.patchProject(project.id, { metadata: masterDataImportProfilesMetadataWith(project.metadata, next) })
      setProfiles(next)
      setDraft(null)
      onChanged()
      onNotice(`已保存导入配置“${normalized.name}”；后续导入可直接复用字段预映射和计划提示。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '导入配置保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (profile: MasterDataImportProfile) => {
    if (!canManage) return
    const next = profiles.filter((item) => item.id !== profile.id)
    try {
      setSaving(true)
      await api.patchProject(project.id, { metadata: masterDataImportProfilesMetadataWith(project.metadata, next) })
      setProfiles(next)
      if (draft?.id === profile.id) setDraft(null)
      onChanged()
      onNotice(`已移除导入配置“${profile.name}”；既有导入批次与主数据不会被改写。`)
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '移除导入配置失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  const changeMapping = (fieldKey: string, value: string) => setDraft((current) => current
    ? { ...current, column_mapping: { ...current.column_mapping, [fieldKey]: value } }
    : current)

  return <section className="section-block master-data-import-profile-panel">
    <div className="section-header compact-header"><div><h2>主数据导入配置与计划</h2><p>保存常用文件字段预映射、导入对象和人工计划。每次实际写入仍先经过预检，再由项目管理员确认。</p></div><span className="section-code">IMPORT PROFILE</span></div>
    <div className="import-profile-content">
      <div className="import-profile-ledger">
        {profiles.length === 0 ? <p className="import-profile-empty">尚无已保存配置。可先建立一个中心固定资料或受试者编号导入配置。</p> : profiles.map((profile) => {
          const schedule = masterDataImportScheduleStatus(profile.next_expected_date)
          const mappingCount = Object.keys(profile.column_mapping).length
          return <article key={profile.id} className="import-profile-card">
            <div className="import-profile-card-heading"><div><strong>{profile.name}</strong><span>{masterDataImportScopeCopy[profile.scope].label} · {masterDataImportCadenceLabel[profile.cadence]}</span></div><em className={`import-profile-schedule ${schedule.tone}`}>{schedule.label}</em></div>
            <p>{mappingCount ? `已预映射 ${mappingCount} 个文件字段` : '未指定自定义列名，导入时使用系统常用列名识别'}{profile.note ? ` · ${profile.note}` : ''}</p>
            {canManage && <div className="import-profile-card-actions"><button type="button" className="button quiet small" disabled={saving} onClick={() => setDraft({ ...profile, column_mapping: { ...profile.column_mapping } })}>编辑</button><button type="button" className="button quiet small" disabled={saving} onClick={() => void remove(profile)}>移除</button></div>}
          </article>
        })}
      </div>
      <div className="import-profile-editor">
        {!canManage && <p className="import-profile-readonly">当前角色可查看已保存配置；维护配置与确认导入由项目管理员完成。</p>}
        {canManage && !draft && <button type="button" className="button quiet small" disabled={saving} onClick={() => setDraft(blankMasterDataImportProfile())}>新建导入配置</button>}
        {canManage && draft && <form className="import-profile-form" onSubmit={(event) => { event.preventDefault(); void save() }}>
          <div className="import-profile-form-heading"><strong>{profiles.some((profile) => profile.id === draft.id) ? '编辑导入配置' : '新建导入配置'}</strong><button type="button" className="button quiet small" disabled={saving} onClick={() => setDraft(null)}>取消</button></div>
          <div className="import-profile-form-grid">
            <label>配置名称<input autoFocus disabled={saving} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="例如：每月中心主数据导入" /></label>
            <label>导入对象<select disabled={saving} value={draft.scope} onChange={(event) => {
              const scope = event.target.value as MasterDataImportScope
              setDraft({ ...draft, scope, column_mapping: {} })
            }}><option value="projects">项目</option><option value="sites">中心与固定资料</option><option value="subjects">受试者编号</option></select></label>
            <label>计划频率<select disabled={saving} value={draft.cadence} onChange={(event) => setDraft({ ...draft, cadence: event.target.value as MasterDataImportProfile['cadence'] })}><option value="manual">按需手工导入</option><option value="weekly">每周提示</option><option value="monthly">每月提示</option></select></label>
            <label>下次计划导入<input type="date" disabled={saving} value={draft.next_expected_date} onChange={(event) => setDraft({ ...draft, next_expected_date: event.target.value })} /></label>
          </div>
          <div className="import-profile-mapping"><div><strong>文件字段预映射</strong><small>左侧为系统字段；填入外部 Excel/CSV 的实际表头即可复用。留空时仍会使用系统内置的中英文常用列名识别。</small></div><div className="import-profile-mapping-grid">{masterDataImportProfileFields[draft.scope].map((field) => <label key={field.key}><span>{field.label}</span><input disabled={saving} value={draft.column_mapping[field.key] ?? ''} onChange={(event) => changeMapping(field.key, event.target.value)} placeholder={field.placeholder} /></label>)}</div></div>
          <label className="import-profile-note">使用说明<textarea disabled={saving} value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} placeholder="例如：使用申办方每周导出的中心主数据表；伦理日期以 YYYY-MM-DD 形式提供" /></label>
          <button className="button primary" disabled={saving}>{saving ? '正在保存…' : '保存导入配置'}</button>
        </form>}
      </div>
    </div>
  </section>
}
