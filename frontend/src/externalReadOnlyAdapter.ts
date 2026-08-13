export type ExternalReadOnlySystem = 'CTMS' | 'eTMF' | 'CTMS_eTMF'

export interface ExternalReadOnlyAdapterConfig {
  enabled: boolean
  system: ExternalReadOnlySystem
  display_name: string
  default_export_reference: string
  note: string
}

export const externalReadOnlyAdapterMetadataKey = 'external_readonly_adapter_sandbox'

export const blankExternalReadOnlyAdapter = (): ExternalReadOnlyAdapterConfig => ({
  enabled: false,
  system: 'CTMS',
  display_name: '',
  default_export_reference: '',
  note: '',
})

export function readExternalReadOnlyAdapter(metadata: Record<string, string> | undefined): ExternalReadOnlyAdapterConfig {
  const raw = metadata?.[externalReadOnlyAdapterMetadataKey]
  if (!raw) return blankExternalReadOnlyAdapter()
  try {
    const value: unknown = JSON.parse(raw)
    if (!value || Array.isArray(value) || typeof value !== 'object') return blankExternalReadOnlyAdapter()
    const config = value as Record<string, unknown>
    const system = config.system === 'eTMF' || config.system === 'CTMS_eTMF' ? config.system : 'CTMS'
    return {
      enabled: Boolean(config.enabled),
      system,
      display_name: String(config.display_name ?? '').trim(),
      default_export_reference: String(config.default_export_reference ?? '').trim(),
      note: String(config.note ?? '').trim(),
    }
  } catch {
    return blankExternalReadOnlyAdapter()
  }
}

export function externalReadOnlySystemLabel(system: ExternalReadOnlySystem) {
  return system === 'eTMF' ? 'eTMF' : system === 'CTMS_eTMF' ? 'CTMS + eTMF' : 'CTMS'
}

export function externalReadOnlyAdapterMetadataWith(
  metadata: Record<string, string>,
  config: ExternalReadOnlyAdapterConfig,
): Record<string, string> {
  return {
    ...metadata,
    [externalReadOnlyAdapterMetadataKey]: JSON.stringify({
      enabled: config.enabled,
      system: config.system,
      display_name: config.display_name.trim(),
      default_export_reference: config.default_export_reference.trim(),
      note: config.note.trim(),
    }),
  }
}
