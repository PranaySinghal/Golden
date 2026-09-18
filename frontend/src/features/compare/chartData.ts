import type { AnswerCardView, GroupChangeView } from '../../api/client'

// Enough groups to see the shape, few enough to read the labels.
export const MAX_BARS = 8

export interface ChartRow {
  label: string
  before: number | null
  after: number | null
  status: GroupChangeView['status']
}

export function chartRows(card: AnswerCardView): ChartRow[] {
  const groups = card.groups ?? []
  // Trends read in time order; everything else reads biggest first.
  const ordered =
    card.kind === 'trend'
      ? [...groups]
      : [...groups].sort((a, b) => (b.after ?? b.before ?? 0) - (a.after ?? a.before ?? 0))
  return ordered.slice(0, MAX_BARS).map((group) => ({
    label: group.label,
    // A count of nothing is a real zero; an average of nothing has no value, so
    // it gets no bar rather than a bar at zero, which would say something false.
    before: barValue(group.before, card),
    after: barValue(group.after, card),
    status: group.status,
  }))
}

function barValue(value: number | null | undefined, card: AnswerCardView): number | null {
  if (value !== null && value !== undefined) return value
  return card.measure === 'count' || card.measure === 'count_distinct' ? 0 : null
}
