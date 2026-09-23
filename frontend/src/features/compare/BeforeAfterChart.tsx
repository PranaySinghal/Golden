import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import type { AnswerCardView } from '../../api/client'
import { type ChartRow, chartRows } from './chartData'
import { formatAnswer } from './format'

const BAR_SIZE = 22

export function BeforeAfterChart({ card }: { card: AnswerCardView }) {
  const rows = chartRows(card)
  if (rows.length === 0) return null

  return (
    <div className="chart">
      <ChartTable card={card} rows={rows} />
      <ResponsiveContainer width="100%" height={Math.max(180, rows.length * 34 + 40)}>
        <BarChart data={rows} layout="vertical" barGap={-BAR_SIZE} margin={{ left: 8, right: 16 }}>
          <CartesianGrid horizontal={false} stroke="var(--border)" />
          <XAxis type="number" tick={{ fontSize: 12, fill: 'var(--muted)' }} />
          <YAxis
            type="category"
            dataKey="label"
            width={110}
            tick={{ fontSize: 12, fill: 'var(--muted)' }}
          />
          <Tooltip
            cursor={{ fill: 'var(--surface-muted)' }}
            content={({ payload }) => <ChartTip card={card} row={payload?.[0]?.payload} />}
          />
          {/* The old answer sits behind the new one, like a shadow of where it was. */}
          <Bar dataKey="before" fill="var(--muted)" fillOpacity={0.25} barSize={BAR_SIZE} />
          <Bar dataKey="after" fill="var(--accent)" barSize={BAR_SIZE} />
        </BarChart>
      </ResponsiveContainer>
      <ChartNotes card={card} rows={rows} />
    </div>
  )
}

function ChartTip({ card, row }: { card: AnswerCardView; row?: ChartRow }) {
  if (!row) return null
  return (
    <div className="chart__tip">
      <strong>{row.label}</strong>
      <div>
        {formatAnswer(row.before, card.measure)} → {formatAnswer(row.after, card.measure)}
      </div>
    </div>
  )
}

/** The same numbers as a table, for anyone who can't see the bars. */
function ChartTable({ card, rows }: { card: AnswerCardView; rows: ChartRow[] }) {
  return (
    <table className="visually-hidden">
      <caption>{card.label}</caption>
      <thead>
        <tr>
          <th scope="col">Group</th>
          <th scope="col">Before cleaning</th>
          <th scope="col">After cleaning</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.label}>
            <th scope="row">{row.label}</th>
            <td>{formatAnswer(row.before, card.measure)}</td>
            <td>{formatAnswer(row.after, card.measure)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ChartNotes({ card, rows }: { card: AnswerCardView; rows: ChartRow[] }) {
  const merged = card.merged ?? []
  const appeared = rows.filter((row) => row.status === 'appeared').map((row) => row.label)
  const gone = rows.filter((row) => row.status === 'disappeared').map((row) => row.label)
  const hidden = (card.groups?.length ?? 0) - rows.length
  const allNew = appeared.length === rows.length && rows.length > 0

  return (
    <div className="chart__notes muted small">
      <ul className="chart__summary">
        {/* Naming every group is noise when the whole breakdown is new. */}
        {allNew && <li>None of these groups existed before cleaning.</li>}
        {!allNew && appeared.length > 0 && <li>{newGroups(appeared)}</li>}
        {gone.length > 0 && <li>{emptyGroups(gone)}</li>}
        {hidden > 0 && <li>{hidden} smaller groups aren’t shown.</li>}
      </ul>
      {merged.length > 0 && <MergedNotes merged={merged} />}
    </div>
  )
}

/** One line per merged spelling can run to a dozen, so they wait behind a toggle. */
function MergedNotes({ merged }: { merged: NonNullable<AnswerCardView['merged']> }) {
  const [open, setOpen] = useState(false)
  const one = merged.length === 1
  return (
    <div className="chart__merged">
      <button
        type="button"
        className="link-button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open
          ? `Hide the ${one ? 'spelling' : 'spellings'}`
          : one
            ? 'Show the spelling now counted together'
            : `Show the ${merged.length} spellings now counted together`}
      </button>
      {open && (
        <ul className="chart__merged-list">
          {merged.map((note) => (
            <li key={note.label}>
              “{note.label}” is now counted with “{note.into}”.
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function newGroups(labels: string[]): string {
  const one = labels.length === 1
  return `${list(labels)} ${one ? 'wasn’t a group' : 'weren’t groups'} before cleaning.`
}

function emptyGroups(labels: string[]): string {
  const one = labels.length === 1
  return `${list(labels)} ${one ? 'has' : 'have'} no rows left after cleaning.`
}

function list(labels: string[]): string {
  const quoted = labels.map((label) => `“${label}”`)
  if (quoted.length === 1) return quoted[0]
  return `${quoted.slice(0, -1).join(', ')} and ${quoted[quoted.length - 1]}`
}
