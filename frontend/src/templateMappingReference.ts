import type { TemplateMapping } from './types'

export interface TemplateMappingReferenceRow {
  target: TemplateMapping
  source: TemplateMapping | null
}

export function buildTemplateMappingReferenceRows(
  targetMappings: TemplateMapping[],
  sourceMappings: TemplateMapping[],
): TemplateMappingReferenceRow[] {
  const sourceByTable = new Map<number, TemplateMapping>()
  sourceMappings.forEach((mapping) => {
    if (!sourceByTable.has(mapping.table_index)) sourceByTable.set(mapping.table_index, mapping)
  })

  return [...targetMappings]
    .sort((left, right) => left.table_index - right.table_index)
    .map((target) => ({
      target,
      source: sourceByTable.get(target.table_index) ?? null,
    }))
}

export function templateMappingReferenceLabel(mapping: TemplateMapping) {
  const fieldKey = mapping.field_key.trim() || '未设置字段键'
  const description = mapping.target_description.trim() || '未命名监查区域'
  return [fieldKey, description].join(' · ')
}
