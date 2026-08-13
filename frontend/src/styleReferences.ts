import type { HistoryReportItem } from './types'

export interface ControlledStyleReference {
  revision_id: string
  visit_id: string
  visit_code: string
  visit_date: string
  visit_type: string
  site_code: string
  site_name: string
  version_number: string
  purpose: 'writing_style_only'
  note: string
}

const stringValue = (value: unknown) => typeof value === 'string' ? value.trim() : ''

export function readControlledStyleReferences(content: Record<string, unknown> | undefined): ControlledStyleReference[] {
  const raw = content?.approved_style_references
  if (!Array.isArray(raw)) return []

  const references = raw.flatMap((item) => {
    if (!item || Array.isArray(item) || typeof item !== 'object') return []
    const value = item as Record<string, unknown>
    const revisionId = stringValue(value.revision_id)
    if (!revisionId) return []
    return [{
      revision_id: revisionId,
      visit_id: stringValue(value.visit_id),
      visit_code: stringValue(value.visit_code),
      visit_date: stringValue(value.visit_date),
      visit_type: stringValue(value.visit_type),
      site_code: stringValue(value.site_code),
      site_name: stringValue(value.site_name),
      version_number: stringValue(value.version_number),
      purpose: 'writing_style_only' as const,
      note: stringValue(value.note),
    }]
  })

  return references.filter((item, index) => references.findIndex((candidate) => candidate.revision_id === item.revision_id) === index)
}

export function styleReferenceFromReport(report: HistoryReportItem): ControlledStyleReference {
  return {
    revision_id: report.id,
    visit_id: report.visit_id,
    visit_code: report.visit_code,
    visit_date: report.visit_date,
    visit_type: report.visit_type,
    site_code: report.site_code,
    site_name: report.site_name,
    version_number: report.version_number,
    purpose: 'writing_style_only',
    note: '',
  }
}

export function controlledStyleReferenceLabel(reference: ControlledStyleReference) {
  const site = reference.site_code || reference.site_name || '来源中心未记录'
  const visit = reference.visit_code || reference.visit_id || '来源访视未记录'
  const version = reference.version_number || '版本未记录'
  return `${site} · ${visit} · ${reference.visit_date || '日期未记录'} · ${version}`
}

export function styleReferenceContentWith(
  content: Record<string, unknown>,
  references: ControlledStyleReference[],
): Record<string, unknown> {
  const next = { ...content }
  if (references.length) next.approved_style_references = references.map((reference) => ({ ...reference }))
  else delete next.approved_style_references
  return next
}
