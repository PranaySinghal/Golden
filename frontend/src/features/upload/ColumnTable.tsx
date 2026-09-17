import type { ColumnProfile } from '../../api/client'
import { InfoTip } from '../../components/InfoTip'
import { ROLE_LABELS, formatCount, formatRange, formatShare } from './format'

const MAX_EXAMPLES = 3

export function ColumnTable({ columns }: { columns: ColumnProfile[] }) {
  return (
    <div className="table-scroll">
      <table className="column-table">
        <caption className="visually-hidden">What each column holds</caption>
        <thead>
          <tr>
            <th scope="col">Column</th>
            <th scope="col">Kind</th>
            <th scope="col" className="numeric">
              Filled in
            </th>
            <th scope="col" className="numeric">
              Different values
            </th>
            <th scope="col">Range</th>
            <th scope="col">Examples</th>
          </tr>
        </thead>
        <tbody>
          {columns.map((column) => (
            <ColumnRow key={column.position} column={column} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ColumnRow({ column }: { column: ColumnProfile }) {
  const kind = ROLE_LABELS[column.semantic_role]
  const range = formatRange(column)
  const examples = column.sample_values.slice(0, MAX_EXAMPLES)
  const allBlank = column.non_blank_count === 0

  return (
    <tr>
      <th scope="row" className="column-table__name">
        {column.name}
      </th>
      <td>
        <span className="kind">
          {allBlank ? 'Empty' : kind}
          <InfoTip label={`Why ${column.name} is ${allBlank ? 'empty' : kind}`} text={column.role_note} />
        </span>
      </td>
      <td className="numeric">{formatShare(column.fill_rate)}</td>
      <td className="numeric">{formatCount(column.distinct_count)}</td>
      <td>
        {range ? (
          <span className="range">
            {range.map((end, index) => (
              <span key={index}>{index > 0 ? `– ${end}` : end}</span>
            ))}
          </span>
        ) : (
          <span className="muted">—</span>
        )}
      </td>
      <td className="column-table__examples">
        {examples.length > 0 ? (
          examples.map((value, index) => (
            <span key={index} className="chip">
              {value}
            </span>
          ))
        ) : (
          <span className="muted">No values</span>
        )}
      </td>
    </tr>
  )
}
