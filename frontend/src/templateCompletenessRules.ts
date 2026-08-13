export type TemplateTaskCompletenessMode = 'mapping_required' | 'all_mappings' | 'none'
export type TemplateFieldCompletenessMode = 'slot_required' | 'all_confirmed_text_slots' | 'none'

export interface TemplateCompletenessRules {
  task_mode: TemplateTaskCompletenessMode
  field_mode: TemplateFieldCompletenessMode
}

export const templateCompletenessMetadataKey = 'template_completeness_rules'

export const blankTemplateCompletenessRules = (): TemplateCompletenessRules => ({
  task_mode: 'mapping_required',
  field_mode: 'slot_required',
})

const taskModes = new Set<TemplateTaskCompletenessMode>(['mapping_required', 'all_mappings', 'none'])
const fieldModes = new Set<TemplateFieldCompletenessMode>(['slot_required', 'all_confirmed_text_slots', 'none'])

export function readTemplateCompletenessRules(metadata: Record<string, unknown> | undefined): TemplateCompletenessRules {
  const raw = metadata?.[templateCompletenessMetadataKey]
  if (!raw || Array.isArray(raw) || typeof raw !== 'object') return blankTemplateCompletenessRules()
  const value = raw as Record<string, unknown>
  return {
    task_mode: taskModes.has(value.task_mode as TemplateTaskCompletenessMode)
      ? value.task_mode as TemplateTaskCompletenessMode
      : 'mapping_required',
    field_mode: fieldModes.has(value.field_mode as TemplateFieldCompletenessMode)
      ? value.field_mode as TemplateFieldCompletenessMode
      : 'slot_required',
  }
}

export function templateCompletenessMetadataWith(
  metadata: Record<string, unknown>,
  rules: TemplateCompletenessRules,
): Record<string, unknown> {
  return {
    ...metadata,
    [templateCompletenessMetadataKey]: {
      task_mode: rules.task_mode,
      field_mode: rules.field_mode,
    },
  }
}

export const templateTaskCompletenessLabels: Record<TemplateTaskCompletenessMode, string> = {
  mapping_required: '仅映射中标记为必填的任务',
  all_mappings: '所有模板映射任务',
  none: '不以模板映射任务作为门禁',
}

export const templateFieldCompletenessLabels: Record<TemplateFieldCompletenessMode, string> = {
  slot_required: '仅填写位中标记为必填的 CRA 确认字段',
  all_confirmed_text_slots: '所有 CRA 确认文本填写位',
  none: '不以报告填写位作为门禁',
}
