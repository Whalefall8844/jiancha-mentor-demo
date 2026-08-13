import type { ConfirmedItem, DemoState, ReviewComment } from './types'

export interface ReportPreviewParagraph {
  id: string
  targetKey: string
  sequence: number
  targetTable: number
  fieldKey: string
  taskTitle: string
  text: string
  confirmedFieldId: string
}

const reportText = (field: ConfirmedItem) => field.report_text?.trim() || field.value?.trim() || field.text.trim()

export function buildReportPreviewParagraphs(state: DemoState): ReportPreviewParagraph[] {
  const tasksByTable = new Map(
    state.table_tasks.map((task) => [task.table_index ?? task.index, task]),
  )
  return state.confirmed_items
    .map((field) => ({ field, text: reportText(field) }))
    .filter(({ text }) => Boolean(text))
    .sort((left, right) => {
      const tableDiff = left.field.target_table - right.field.target_table
      if (tableDiff) return tableDiff
      const timeDiff = (left.field.confirmed_at || '').localeCompare(right.field.confirmed_at || '')
      return timeDiff || left.field.id.localeCompare(right.field.id)
    })
    .map(({ field, text }, index) => {
      const task = tasksByTable.get(field.target_table)
      return {
        id: field.id,
        targetKey: `paragraph_${field.id}`,
        sequence: index + 1,
        targetTable: field.target_table,
        fieldKey: field.field_key ?? '',
        taskTitle: task?.title ?? `表 ${field.target_table} 报告文字`,
        text,
        confirmedFieldId: field.id,
      }
    })
}

export function reviewTargetLabel(comment: Pick<ReviewComment, 'target_key'>, state: DemoState) {
  const target = comment.target_key ?? ''
  if (!target) return '整份报告'
  if (target.startsWith('paragraph_')) {
    const paragraph = buildReportPreviewParagraphs(state).find((item) => item.targetKey === target)
    return paragraph ? `段落 ${paragraph.sequence} · 表 ${paragraph.targetTable} · ${paragraph.taskTitle}` : '报告预览段落'
  }
  if (target.startsWith('table_')) {
    const index = Number(target.replace('table_', ''))
    const task = state.table_tasks.find((entry) => (entry.table_index ?? entry.index) === index)
    return task ? `表 ${index} · ${task.title}` : `表 ${index}`
  }
  if (target.startsWith('field_')) {
    const field = state.confirmed_items.find((entry) => entry.id === target.replace('field_', ''))
    return field ? `已确认字段 · 表 ${field.target_table}` : '已确认字段'
  }
  return target
}

export function reviewCommentLabel(comment: Pick<ReviewComment, 'action' | 'comment_type'>) {
  if (comment.comment_type === 'specialist_comment') return '专项批注'
  if (comment.comment_type === 'specialist_concurrence') return '专项阅知 / 无补充意见'
  if (comment.action === 'returned') return '退回 CRA'
  if (comment.action === 'approved') return '批准报告'
  return 'PM / LM 审核建议'
}
