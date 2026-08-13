import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../api'
import type { ControlledDocument, ControlledDocumentType, FrozenMasterData, SiteMasterVersion, SiteSummary, UserRole } from '../types'

interface ControlledDataPanelProps {
  projectId: string
  site?: SiteSummary
  visitDate: string
  currentRole: UserRole
  onChanged: () => void
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

const documentTypeLabel: Record<ControlledDocumentType, string> = {
  protocol: '研究方案',
  icf: '知情同意书',
  ethics: '伦理批准文件',
  other: '其他受控文件',
}

const statusLabel: Record<string, string> = {
  active: '有效',
  superseded: '已替代',
  inactive: '已停用',
}

const emptyProfile = {
  version_label: '',
  pi_name: '',
  site_address: '',
  site_team: '',
  key_roles_text: '',
  effective_from: '',
  effective_to: '',
}

const emptyDocument = {
  document_type: 'protocol' as ControlledDocumentType,
  scope: 'site',
  title: '',
  version: '',
  version_date: '',
  effective_from: '',
  effective_to: '',
  source_reference: '',
  notes: '',
  file: null as File | null,
}

export function ControlledDataPanel({ projectId, site, visitDate, currentRole, onChanged, onNotice }: ControlledDataPanelProps) {
  const [profiles, setProfiles] = useState<SiteMasterVersion[]>([])
  const [documents, setDocuments] = useState<ControlledDocument[]>([])
  const [frozen, setFrozen] = useState<FrozenMasterData | null>(null)
  const [profileDraft, setProfileDraft] = useState(emptyProfile)
  const [documentDraft, setDocumentDraft] = useState(emptyDocument)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)

  const canManage = currentRole === 'PROJECT_ADMIN'

  const load = async () => {
    if (!projectId || !site) {
      setProfiles([])
      setDocuments([])
      setFrozen(null)
      return
    }
    try {
      setLoading(true)
      const [profileResponse, documentResponse] = await Promise.all([
        api.listSiteMasterVersions(site.id),
        api.listControlledDocuments(projectId, site.id),
      ])
      setProfiles(profileResponse.items)
      setDocuments(documentResponse.items)
      if (visitDate) {
        const preview = await api.previewFrozenMasterData(projectId, site.id, visitDate)
        setFrozen(preview.master_data)
      } else {
        setFrozen(null)
      }
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '无法读取受控资料台账', 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [projectId, site?.id, visitDate])

  const createProfile = async (event: FormEvent) => {
    event.preventDefault()
    if (!site || !canManage) return
    try {
      setBusy(true)
      await api.createSiteMasterVersion(site.id, {
        version_label: profileDraft.version_label,
        pi_name: profileDraft.pi_name,
        site_address: profileDraft.site_address,
        site_team: profileDraft.site_team,
        key_roles: profileDraft.key_roles_text ? { '中心关键角色': profileDraft.key_roles_text } : {},
        effective_from: profileDraft.effective_from,
        effective_to: profileDraft.effective_to,
        created_by: '项目管理员',
      })
      setProfileDraft({ ...emptyProfile, pi_name: site.pi_name })
      await load()
      onChanged()
      onNotice('中心资料版本已登记；后续新访视将按有效日期冻结。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '中心资料版本保存失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const createDocument = async (event: FormEvent) => {
    event.preventDefault()
    if (!site || !canManage) return
    try {
      setBusy(true)
      await api.createControlledDocument(projectId, {
        document_type: documentDraft.document_type,
        title: documentDraft.title,
        site_id: documentDraft.scope === 'site' ? site.id : '',
        version: documentDraft.version,
        version_date: documentDraft.version_date,
        effective_from: documentDraft.effective_from,
        effective_to: documentDraft.effective_to,
        source_reference: documentDraft.source_reference,
        notes: documentDraft.notes,
        file: documentDraft.file,
      })
      setDocumentDraft(emptyDocument)
      await load()
      onChanged()
      onNotice('受控文件已登记，并可用于后续访视快照。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '受控文件登记失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const supersedeProfile = async (item: SiteMasterVersion) => {
    try {
      setBusy(true)
      await api.updateSiteMasterVersion(item.id, { status: 'superseded' })
      await load()
      onChanged()
      onNotice('中心资料版本已标记为已替代。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '状态更新失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const supersedeDocument = async (item: ControlledDocument) => {
    try {
      setBusy(true)
      await api.updateControlledDocument(item.id, { status: 'superseded' })
      await load()
      onChanged()
      onNotice('受控文件已标记为已替代。')
    } catch (error) {
      onNotice(error instanceof Error ? error.message : '状态更新失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  if (!projectId || !site) return null

  const frozenDocuments = frozen ? Object.values(frozen.documents) : []

  return (
    <section className="section-block controlled-data-panel">
      <div className="section-header">
        <div>
          <h2>固定资料版本与受控文件</h2>
          <p>项目管理员维护有效区间；CRA 新建访视时，系统按访视日期冻结中心 PI、方案、ICF 与伦理文件版本。</p>
        </div>
        <span className="section-code">CONTROLLED DATA</span>
      </div>

      {visitDate && frozen && (
        <div className="frozen-master-preview">
          <div className="frozen-master-heading"><strong>拟冻结版本预览</strong><span>{visitDate}</span></div>
          <div className="frozen-master-facts">
            <div><span>中心资料</span><strong>{frozen.site_profile.version_label || '历史中心资料'}</strong><small>PI：{frozen.site_profile.pi_name || '未填写'}</small></div>
            {frozenDocuments.map((document) => <div key={`${document.document_type}-${document.id ?? document.title}`}><span>{documentTypeLabel[document.document_type]}</span><strong>{document.display || '未登记'}</strong><small>{document.effective_from || '未限定起始日'} 至 {document.effective_to || '持续有效'}</small></div>)}
          </div>
        </div>
      )}

      <div className="controlled-ledger-grid">
        <div className="controlled-ledger-column">
          <div className="controlled-ledger-header"><strong>中心资料版本</strong><small>{profiles.length} 条</small></div>
          {profiles.length === 0 ? <p className="controlled-empty">尚未登记版本，将暂以中心历史字段作为新访视的兼容回退。</p> : <div className="controlled-list">{profiles.map((item) => <article className="controlled-record" key={item.id}><div><strong>{item.version_label}</strong><span className={`controlled-status ${item.status}`}>{statusLabel[item.status] ?? item.status}</span></div><p>PI：{item.pi_name || '未填写'} · {item.site_team || '未填写中心团队'}</p><small>{item.effective_from || '未限定起始日'} 至 {item.effective_to || '持续有效'} · {item.created_by || '项目管理员'}</small>{canManage && item.status === 'active' && <button type="button" className="button-link danger" disabled={busy} onClick={() => void supersedeProfile(item)}>标记已替代</button>}</article>)}</div>}
        </div>

        <div className="controlled-ledger-column">
          <div className="controlled-ledger-header"><strong>受控文件台账</strong><small>{documents.length} 条</small></div>
          {documents.length === 0 ? <p className="controlled-empty">尚未登记项目或本中心受控文件。</p> : <div className="controlled-list">{documents.map((item) => <article className="controlled-record" key={item.id}><div><strong>{documentTypeLabel[item.document_type]} · {item.version || item.title}</strong><span className={`controlled-status ${item.status}`}>{statusLabel[item.status] ?? item.status}</span></div><p>{item.site_id ? '中心级文件' : '项目级文件'} · {item.title}</p><small>{item.effective_from || '未限定起始日'} 至 {item.effective_to || '持续有效'}{item.content_hash ? ` · SHA-256 ${item.content_hash.slice(0, 10)}…` : ''}</small><div className="controlled-record-actions">{item.stored_path && <button type="button" className="button-link" onClick={() => void api.downloadControlledDocument(item.id, item.source_file_name || item.title)}>下载源文件</button>}{canManage && item.status === 'active' && <button type="button" className="button-link danger" disabled={busy} onClick={() => void supersedeDocument(item)}>标记已替代</button>}</div></article>)}</div>}
        </div>
      </div>

      {canManage ? <div className="controlled-forms">
        <form className="controlled-form" onSubmit={createProfile}>
          <div className="controlled-form-heading"><strong>登记中心资料版本</strong><small>PI、中心团队和关键角色可以随版本生效。</small></div>
          <div className="compact-form"><label>版本标识<input required value={profileDraft.version_label} onChange={(event) => setProfileDraft({ ...profileDraft, version_label: event.target.value })} placeholder="例如：中心资料 V2.0" /></label><label>中心 PI<input value={profileDraft.pi_name} onChange={(event) => setProfileDraft({ ...profileDraft, pi_name: event.target.value })} /></label><label>中心地址<input value={profileDraft.site_address} onChange={(event) => setProfileDraft({ ...profileDraft, site_address: event.target.value })} /></label><label>中心团队<input value={profileDraft.site_team} onChange={(event) => setProfileDraft({ ...profileDraft, site_team: event.target.value })} /></label><label>关键角色 / 联系人<input value={profileDraft.key_roles_text} onChange={(event) => setProfileDraft({ ...profileDraft, key_roles_text: event.target.value })} /></label><label>生效起始日<input value={profileDraft.effective_from} onChange={(event) => setProfileDraft({ ...profileDraft, effective_from: event.target.value })} placeholder="YYYY-MM-DD" /></label><label>生效截止日<input value={profileDraft.effective_to} onChange={(event) => setProfileDraft({ ...profileDraft, effective_to: event.target.value })} placeholder="YYYY-MM-DD" /></label><button className="button secondary" disabled={busy}>{busy ? '正在保存…' : '登记中心资料'}</button></div>
        </form>

        <form className="controlled-form" onSubmit={createDocument}>
          <div className="controlled-form-heading"><strong>登记受控文件</strong><small>可上传源文件，也可登记 eTMF / CTMS 中的来源编号。</small></div>
          <div className="compact-form"><label>文件类型<select value={documentDraft.document_type} onChange={(event) => setDocumentDraft({ ...documentDraft, document_type: event.target.value as ControlledDocumentType })}>{(Object.keys(documentTypeLabel) as ControlledDocumentType[]).map((type) => <option key={type} value={type}>{documentTypeLabel[type]}</option>)}</select></label><label>适用范围<select value={documentDraft.scope} onChange={(event) => setDocumentDraft({ ...documentDraft, scope: event.target.value })}><option value="site">当前中心</option><option value="project">整个项目</option></select></label><label>文件名称<input required value={documentDraft.title} onChange={(event) => setDocumentDraft({ ...documentDraft, title: event.target.value })} placeholder="例如：研究方案" /></label><label>版本<input value={documentDraft.version} onChange={(event) => setDocumentDraft({ ...documentDraft, version: event.target.value })} placeholder="例如：V2.0" /></label><label>版本日期<input value={documentDraft.version_date} onChange={(event) => setDocumentDraft({ ...documentDraft, version_date: event.target.value })} placeholder="YYYY-MM-DD" /></label><label>生效起始日<input value={documentDraft.effective_from} onChange={(event) => setDocumentDraft({ ...documentDraft, effective_from: event.target.value })} placeholder="YYYY-MM-DD" /></label><label>生效截止日<input value={documentDraft.effective_to} onChange={(event) => setDocumentDraft({ ...documentDraft, effective_to: event.target.value })} placeholder="YYYY-MM-DD" /></label><label>来源编号 / 链接<input value={documentDraft.source_reference} onChange={(event) => setDocumentDraft({ ...documentDraft, source_reference: event.target.value })} /></label><label>源文件<input type="file" onChange={(event) => setDocumentDraft({ ...documentDraft, file: event.target.files?.[0] ?? null })} /><small>{documentDraft.file ? documentDraft.file.name : '可选；上传后保存 SHA-256'}</small></label><label>备注<input value={documentDraft.notes} onChange={(event) => setDocumentDraft({ ...documentDraft, notes: event.target.value })} /></label><button className="button secondary" disabled={busy}>{busy ? '正在保存…' : '登记受控文件'}</button></div>
        </form>
      </div> : <p className="controlled-readonly">当前为 {currentRole === 'CRA' ? 'CRA' : '审核'} 角色：可查看拟冻结资料，版本维护由项目管理员完成。</p>}
      {loading && <p className="controlled-loading">正在刷新版本台账…</p>}
    </section>
  )
}
