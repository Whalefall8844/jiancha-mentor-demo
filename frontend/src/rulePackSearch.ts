import type { RulePack } from './types'

export type RulePackSearchScope = 'frozen' | 'selected' | 'project'

export interface RulePackSearchDocument {
  source: 'frozen' | 'project'
  sourceLabel: string
  rulePack: RulePack
}

export interface RulePackCitation {
  id: string
  source: RulePackSearchDocument['source']
  sourceLabel: string
  rulePackId: string
  rulePackName: string
  rulePackVersion: string
  path: string
  pathLabel: string
  value: string
  citation: string
  searchableText: string
}

const isObjectRecord = (value: unknown): value is Record<string, unknown> => Boolean(value) && !Array.isArray(value) && typeof value === 'object'

const pathSegment = (path: string, key: string) => /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key)
  ? `${path}.${key}`
  : `${path}[${JSON.stringify(key)}]`

const labelSegment = (label: string, key: string) => label ? `${label} › ${key}` : key

const citationText = (item: Omit<RulePackCitation, 'citation' | 'searchableText'>) => `【${item.sourceLabel}｜${item.rulePackName} ${item.rulePackVersion}｜${item.path}】${item.value}`

export function buildRulePackCitationIndex(documents: RulePackSearchDocument[]) {
  const citations: RulePackCitation[] = []

  const visitValue = (
    document: RulePackSearchDocument,
    value: unknown,
    path: string,
    pathLabel: string,
  ) => {
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      const base = {
        id: `${document.source}:${document.rulePack.id}:${path}`,
        source: document.source,
        sourceLabel: document.sourceLabel,
        rulePackId: document.rulePack.id,
        rulePackName: document.rulePack.name,
        rulePackVersion: document.rulePack.version,
        path,
        pathLabel,
        value: String(value),
      }
      citations.push({
        ...base,
        citation: citationText(base),
        searchableText: `${base.path} ${base.pathLabel} ${base.value}`.toLocaleLowerCase(),
      })
      return
    }
    if (Array.isArray(value)) {
      value.forEach((entry, index) => visitValue(document, entry, `${path}[${index}]`, `${pathLabel} › 第 ${index + 1} 项`))
      return
    }
    if (isObjectRecord(value)) {
      Object.entries(value).forEach(([key, entry]) => visitValue(document, entry, pathSegment(path, key), labelSegment(pathLabel, key)))
    }
  }

  documents.forEach((document) => visitValue(document, document.rulePack.content ?? {}, '$', '规则内容'))
  return citations
}

export function filterRulePackCitations(citations: RulePackCitation[], query: string) {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return []
  return citations.filter((citation) => terms.every((term) => citation.searchableText.includes(term)))
}
