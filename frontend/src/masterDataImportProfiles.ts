export type MasterDataImportScope = 'projects' | 'sites' | 'subjects'
export type MasterDataImportCadence = 'manual' | 'weekly' | 'monthly'

export interface MasterDataImportProfile {
  id: string
  name: string
  scope: MasterDataImportScope
  column_mapping: Record<string, string>
  cadence: MasterDataImportCadence
  next_expected_date: string
  note: string
}

export const masterDataImportProfileMetadataKey = 'master_data_import_profiles'

export const masterDataImportScopeCopy: Record<MasterDataImportScope, { label: string; description: string; columns: string }> = {
  projects: { label: '项目', description: '新建或更新项目主数据及批件 / SOP 信息。', columns: 'project_code, project_name, sponsor, approval_number, sop_version' },
  sites: { label: '中心与固定资料', description: '导入 PI、伦理日期、方案及 ICF 版本；可在表中指定 project_code。', columns: 'project_code, site_code, site_name, pi_name, ethics_date, protocol_version, icf_version' },
  subjects: { label: '受试者编号', description: '仅保存受试者编号与状态，不导入直接身份信息。', columns: 'project_code, site_code, subject_code, enrollment_status' },
}

export const masterDataImportProfileFields: Record<MasterDataImportScope, Array<{ key: string; label: string; placeholder: string }>> = {
  projects: [
    { key: 'project_code', label: '项目编号', placeholder: '例如：Study No.' },
    { key: 'project_name', label: '项目名称', placeholder: '例如：Study Name' },
    { key: 'sponsor', label: '申办方', placeholder: '例如：Sponsor Name' },
    { key: 'approval_number', label: '批准文号', placeholder: '例如：NMPA No.' },
    { key: 'sop_version', label: 'SOP 版本', placeholder: '例如：Monitoring SOP' },
  ],
  sites: [
    { key: 'project_code', label: '项目编号', placeholder: '例如：Study No.' },
    { key: 'site_code', label: '中心编号', placeholder: '例如：Site No.' },
    { key: 'site_name', label: '中心名称', placeholder: '例如：Site Name' },
    { key: 'pi_name', label: '中心 PI', placeholder: '例如：Principal Investigator' },
    { key: 'ethics_date', label: '伦理日期', placeholder: '例如：EC Approval Date' },
    { key: 'protocol_version', label: '方案版本', placeholder: '例如：Protocol Version' },
    { key: 'icf_version', label: 'ICF 版本', placeholder: '例如：ICF Version' },
  ],
  subjects: [
    { key: 'project_code', label: '项目编号', placeholder: '例如：Study No.' },
    { key: 'site_code', label: '中心编号', placeholder: '例如：Site No.' },
    { key: 'subject_code', label: '受试者编号', placeholder: '例如：Subject No.' },
    { key: 'enrollment_status', label: '筛选 / 入组状态', placeholder: '例如：Subject Status' },
  ],
}

export const masterDataImportCadenceLabel: Record<MasterDataImportCadence, string> = {
  manual: '按需手工导入',
  weekly: '每周提示',
  monthly: '每月提示',
}

const profileId = () => `import-profile-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

const cleanColumnMapping = (value: unknown): Record<string, string> => {
  if (!value || Array.isArray(value) || typeof value !== 'object') return {}
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .map(([key, source]) => [String(key).trim(), String(source ?? '').trim()] as const)
    .filter(([key, source]) => Boolean(key && source)))
}

export const blankMasterDataImportProfile = (scope: MasterDataImportScope = 'sites'): MasterDataImportProfile => ({
  id: profileId(),
  name: '',
  scope,
  column_mapping: {},
  cadence: 'manual',
  next_expected_date: '',
  note: '',
})

const normalizeProfile = (value: unknown): MasterDataImportProfile | null => {
  if (!value || Array.isArray(value) || typeof value !== 'object') return null
  const profile = value as Record<string, unknown>
  const scope: MasterDataImportScope = profile.scope === 'projects' || profile.scope === 'subjects' ? profile.scope : 'sites'
  const cadence: MasterDataImportCadence = profile.cadence === 'weekly' || profile.cadence === 'monthly' ? profile.cadence : 'manual'
  const id = String(profile.id ?? '').trim()
  if (!id) return null
  return {
    id,
    name: String(profile.name ?? '').trim() || `${masterDataImportScopeCopy[scope].label}导入配置`,
    scope,
    column_mapping: cleanColumnMapping(profile.column_mapping),
    cadence,
    next_expected_date: String(profile.next_expected_date ?? '').trim(),
    note: String(profile.note ?? '').trim(),
  }
}

export function readMasterDataImportProfiles(metadata: Record<string, string> | undefined): MasterDataImportProfile[] {
  const raw = metadata?.[masterDataImportProfileMetadataKey]
  if (!raw) return []
  try {
    const value: unknown = JSON.parse(raw)
    if (!Array.isArray(value)) return []
    return value.map(normalizeProfile).filter((profile): profile is MasterDataImportProfile => profile !== null)
  } catch {
    return []
  }
}

export function masterDataImportProfilesMetadataWith(
  metadata: Record<string, string>,
  profiles: MasterDataImportProfile[],
): Record<string, string> {
  return {
    ...metadata,
    [masterDataImportProfileMetadataKey]: JSON.stringify(profiles.map((profile) => ({
      id: profile.id,
      name: profile.name.trim(),
      scope: profile.scope,
      column_mapping: cleanColumnMapping(profile.column_mapping),
      cadence: profile.cadence,
      next_expected_date: profile.next_expected_date.trim(),
      note: profile.note.trim(),
    }))),
  }
}

export function masterDataImportScheduleStatus(nextExpectedDate: string, today = new Date().toISOString().slice(0, 10)) {
  if (!nextExpectedDate) return { tone: 'none' as const, label: '未设置下次计划' }
  if (nextExpectedDate < today) return { tone: 'overdue' as const, label: `计划已到期：${nextExpectedDate}` }
  if (nextExpectedDate === today) return { tone: 'due' as const, label: `计划今日导入：${nextExpectedDate}` }
  return { tone: 'upcoming' as const, label: `下次计划：${nextExpectedDate}` }
}
