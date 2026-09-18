import type { AnswerCardView, Measure } from '../../api/client'
import { formatCount } from '../upload/format'

/** How a number reads depends on what was asked: counts are whole, money isn't. */
export function formatAnswer(value: number | null | undefined, measure: Measure): string {
  if (value === null || value === undefined) return '—'
  if (measure === 'count' || measure === 'count_distinct') return formatCount(Math.round(value))
  if (Number.isInteger(value)) return formatCount(value)
  return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** "2,003.65 lower (2.4%)", said the way a person would say it. */
export function describeChange(card: AnswerCardView): string | null {
  const { change, relative_change: relative, measure } = card
  if (change === null || change === undefined || change === 0) return null
  const direction = change > 0 ? 'higher' : 'lower'
  const size = formatAnswer(Math.abs(change), measure)
  if (relative === null || relative === undefined) return `${size} ${direction}`
  return `${size} ${direction} (${formatPercent(Math.abs(relative))})`
}

function formatPercent(share: number): string {
  if (share >= 10) return `${Math.round(share * 100)}%`
  if (share < 0.001) return 'under 0.1%'
  return `${(share * 100).toFixed(1)}%`
}

export function changeDirection(card: AnswerCardView): 'up' | 'down' | 'flat' {
  if (!card.change) return 'flat'
  return card.change > 0 ? 'up' : 'down'
}

/** What the "why" line says, following how the steps were worked out. */
export function whyLead(card: AnswerCardView): string {
  if (card.why.method === 'estimated') return 'Likely caused by'
  const groups = card.why.groups ?? []
  if (groups.length > 0 && groups[0].together) return 'Caused by these together'
  return groups.length > 1 ? 'Caused by' : 'Caused by'
}

export function togetherNote(card: AnswerCardView): string | null {
  const groups = card.why.groups ?? []
  if (!groups.some((group) => group.together)) return null
  return 'Either one on its own changes nothing — it takes both.'
}
