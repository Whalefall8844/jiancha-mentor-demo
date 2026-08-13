export interface ControlledLanguageRuleEntry {
  source: string
  target: string
}

const isObjectRecord = (value: unknown): value is Record<string, unknown> => Boolean(value) && !Array.isArray(value) && typeof value === 'object'

const normalizedEntries = (entries: ControlledLanguageRuleEntry[]) => entries
  .map((entry) => ({ source: entry.source.trim(), target: entry.target.trim() }))
  .filter((entry) => entry.source && entry.target && entry.source !== entry.target)

export function readConfiguredTerminology(content: Record<string, unknown> | undefined): ControlledLanguageRuleEntry[] {
  const terminology = isObjectRecord(content?.terminology) ? content.terminology : {}
  return Object.entries(terminology)
    .map(([source, target]) => ({ source: source.trim(), target: String(target ?? '').trim() }))
    .filter((entry) => entry.source && entry.target)
}

export function readPreferredPhraseReplacements(content: Record<string, unknown> | undefined): ControlledLanguageRuleEntry[] {
  const languageRules = isObjectRecord(content?.language_rules) ? content.language_rules : {}
  const phrases = Array.isArray(languageRules.preferred_phrases) ? languageRules.preferred_phrases : []
  return phrases.flatMap((item) => {
    if (!isObjectRecord(item)) return []
    const source = String(item.source ?? '').trim()
    const target = String(item.target ?? '').trim()
    return source && target ? [{ source, target }] : []
  })
}

export function controlledLanguageContentWith(
  content: Record<string, unknown>,
  terminologyEntries: ControlledLanguageRuleEntry[],
  preferredPhraseEntries: ControlledLanguageRuleEntry[],
) {
  const nextContent = { ...content }
  const terminology = Object.fromEntries(normalizedEntries(terminologyEntries).map((entry) => [entry.source, entry.target]))
  if (Object.keys(terminology).length) nextContent.terminology = terminology
  else delete nextContent.terminology

  const languageRules = isObjectRecord(content.language_rules) ? { ...content.language_rules } : {}
  const preferredPhrases = normalizedEntries(preferredPhraseEntries)
  if (preferredPhrases.length) languageRules.preferred_phrases = preferredPhrases
  else delete languageRules.preferred_phrases
  if (Object.keys(languageRules).length) nextContent.language_rules = languageRules
  else delete nextContent.language_rules

  return nextContent
}
