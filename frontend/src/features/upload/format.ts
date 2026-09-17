import type { ColumnProfile, SemanticRole } from '../../api/client'

// The words users see for each kind of column. No data jargon.
export const ROLE_LABELS: Record<SemanticRole, string> = {
  identifier: 'ID',
  category: 'Category',
  measure: 'Number',
  date: 'Date',
  contact: 'Contact info',
  text: 'Text',
}

export function formatCount(value: number): string {
  return value.toLocaleString('en-US')
}

/** A share from 0 to 1 as a percent that never hides a remainder (no "100%" for 99.6%). */
export function formatShare(share: number): string {
  if (share <= 0) return '0%'
  if (share >= 1) return '100%'
  const percent = share * 100
  if (percent < 1) return '<1%'
  if (percent > 99) return '>99%'
  return `${Math.round(percent)}%`
}

export function formatBytes(bytes: number): string {
  const mb = bytes / (1024 * 1024)
  if (mb >= 1) return `${Number.isInteger(mb) ? mb : mb.toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/** The lowest and highest value, or one value when they're equal. */
export function formatRange(column: ColumnProfile): string[] | null {
  const { min_value: min, max_value: max } = column
  if (min == null && max == null) return null
  if (min === max) return [min ?? '']
  return [min ?? '?', max ?? '?']
}

export function describeRows(rows: number, columns: number): string {
  const rowWord = rows === 1 ? 'row' : 'rows'
  const columnWord = columns === 1 ? 'column' : 'columns'
  return `${formatCount(rows)} ${rowWord} · ${formatCount(columns)} ${columnWord}`
}
