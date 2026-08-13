import { useMemo, useState } from 'react'
import { buildRulePackCitationIndex, filterRulePackCitations, type RulePackCitation, type RulePackSearchDocument, type RulePackSearchScope } from '../rulePackSearch'
import type { RulePack } from '../types'

interface RulePackCitationSearchProps {
  frozenRule?: RulePack
  selectedRule?: RulePack
  rules: RulePack[]
  onNotice: (message: string, tone?: 'success' | 'error') => void
}

const scopeLabel: Record<RulePackSearchScope, string> = {
  frozen: '本访视冻结快照',
  selected: '当前所选规则包',
  project: '项目全部规则包',
}

const scopeDescription: Record<RulePackSearchScope, string> = {
  frozen: '此范围是当前报告与工作台实际冻结的规则依据。',
  selected: '此范围用于查看当前正在配置或审批的项目规则包。',
  project: '此范围跨项目现有规则包检索，仅供配置比对与后续访视准备。',
}

const documentsForScope = (
  scope: RulePackSearchScope,
  frozenRule: RulePack | undefined,
  selectedRule: RulePack | undefined,
  rules: RulePack[],
): RulePackSearchDocument[] => {
  if (scope === 'frozen') return frozenRule ? [{ source: 'frozen', sourceLabel: '本访视冻结快照', rulePack: frozenRule }] : []
  if (scope === 'selected') return selectedRule ? [{ source: 'project', sourceLabel: '当前所选规则包', rulePack: selectedRule }] : []
  return rules.map((rule) => ({ source: 'project', sourceLabel: '项目规则包', rulePack: rule }))
}

export function RulePackCitationSearch({ frozenRule, selectedRule, rules, onNotice }: RulePackCitationSearchProps) {
  const [requestedScope, setRequestedScope] = useState<RulePackSearchScope>('frozen')
  const [query, setQuery] = useState('')
  const [selectedCitationId, setSelectedCitationId] = useState('')

  const activeScope = requestedScope === 'frozen' && !frozenRule
    ? selectedRule ? 'selected' : 'project'
    : requestedScope === 'selected' && !selectedRule
      ? frozenRule ? 'frozen' : 'project'
      : requestedScope
  const documents = useMemo(() => documentsForScope(activeScope, frozenRule, selectedRule, rules), [activeScope, frozenRule, selectedRule, rules])
  const citations = useMemo(() => buildRulePackCitationIndex(documents), [documents])
  const results = useMemo(() => filterRulePackCitations(citations, query), [citations, query])
  const shownResults = results.slice(0, 30)
  const selectedCitation = citations.find((citation) => citation.id === selectedCitationId)

  const selectScope = (scope: RulePackSearchScope) => {
    setRequestedScope(scope)
    setSelectedCitationId('')
  }

  const copyCitation = async (citation: RulePackCitation) => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('当前浏览器不支持剪贴板写入')
      await navigator.clipboard.writeText(citation.citation)
      onNotice('规则引用已复制，可粘贴到工作记录或审核意见中。')
    } catch {
      onNotice('引用文本已在下方显示，请手动复制。', 'error')
    }
  }

  return <section className="section-block rule-citation-search">
    <div className="section-header compact-header">
      <div><h2>规则引用检索</h2><p>按路径和正文定位受控规则；引用始终带有规则包版本，不会代替人工法规判断。</p></div>
      <span className="section-code">CITATIONS</span>
    </div>
    <div className="rule-search-body">
      <div className="rule-search-scope" role="group" aria-label="规则检索范围">
        {(Object.keys(scopeLabel) as RulePackSearchScope[]).map((scope) => {
          const disabled = scope === 'frozen' ? !frozenRule : scope === 'selected' ? !selectedRule : rules.length === 0
          return <button key={scope} type="button" className={`button ${activeScope === scope ? 'primary' : 'quiet'}`} onClick={() => selectScope(scope)} disabled={disabled}>{scopeLabel[scope]}</button>
        })}
      </div>
      <p className="rule-search-description">{scopeDescription[activeScope]}</p>
      <label className="rule-search-input">检索术语、规则路径或配置值<input type="search" value={query} onChange={(event) => { setQuery(event.target.value); setSelectedCitationId('') }} placeholder="例如：知情同意书、system_checks、SOP" /></label>
      {!documents.length && <div className="empty-state"><strong>当前范围没有可检索的规则包</strong><span>请先选择已冻结或项目内的规则包。</span></div>}
      {documents.length > 0 && !query.trim() && <div className="rule-search-empty"><strong>已建立 {citations.length} 条可检索规则段落</strong><span>输入术语、JSON 路径或配置值开始定位；空格分隔的多个词会同时匹配。</span></div>}
      {query.trim() && <div className="rule-search-results">
        <div className="rule-search-result-summary"><strong>匹配 {results.length} 条</strong><span>{results.length > shownResults.length ? `当前展示前 ${shownResults.length} 条` : '按规则包与 JSON 路径定位'}</span></div>
        {shownResults.length === 0 && <div className="empty-state"><strong>未找到匹配规则</strong><span>可尝试术语缩写、配置键名或完整规则名称。</span></div>}
        {shownResults.map((citation) => <article className={`rule-citation-row ${selectedCitationId === citation.id ? 'is-selected' : ''}`} key={citation.id}>
          <button type="button" className="rule-citation-main" onClick={() => setSelectedCitationId(citation.id)} aria-pressed={selectedCitationId === citation.id}>
            <span className="rule-citation-source">{citation.sourceLabel} · {citation.rulePackName} {citation.rulePackVersion}</span>
            <strong>{citation.pathLabel}</strong>
            <code>{citation.path}</code>
            <p>{citation.value}</p>
          </button>
          <button type="button" className="button quiet rule-citation-select" onClick={() => setSelectedCitationId(citation.id)}>选为引用</button>
        </article>)}
      </div>}
      {selectedCitation && <div className="rule-citation-selected">
        <div><strong>已选规则引用</strong><span>将以下文本直接粘贴到工作记录、审核意见或人工核对说明中。</span></div>
        <code>{selectedCitation.citation}</code>
        <button type="button" className="button primary" onClick={() => void copyCitation(selectedCitation)}>复制引用</button>
      </div>}
    </div>
  </section>
}
