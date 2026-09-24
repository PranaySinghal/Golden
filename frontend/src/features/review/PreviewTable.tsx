import { useQuery } from '@tanstack/react-query'

import { api, type PreviewQuery, type PreviewRow } from '../../api/client'
import { ErrorState, Spinner } from '../../components/states'
import { formatCount } from '../upload/format'

interface PreviewTableProps {
  datasetId: string
  query: PreviewQuery
}

const BLANK = '(blank)'

export function PreviewTable({ datasetId, query }: PreviewTableProps) {
  const preview = useQuery({
    queryKey: ['preview', datasetId, query.issueId ?? null, query.choiceId ?? null, query.stepId ?? null],
    queryFn: () => api.getPreview(datasetId, query),
  })

  if (preview.isPending) return <Spinner label="Loading a few example rows…" />
  if (preview.isError) {
    return <ErrorState message={preview.error.message} onRetry={() => void preview.refetch()} />
  }

  const { columns, rows, changed_rows: changed, set_aside_rows: setAside, note } = preview.data
  if (rows.length === 0) {
    return <p className="muted small">{note ?? 'Nothing in this file changes.'}</p>
  }

  return (
    <div className="preview">
      <p className="muted small">
        {summary(changed, setAside)} Showing {rows.length === 1 ? 'one' : `${rows.length}`} of them.
      </p>
      <div className="table-scroll">
        <table className="preview__table">
          <caption className="visually-hidden">Example rows before and after this change</caption>
          <thead>
            <tr>
              <th scope="col">Row</th>
              {columns.map((column) => (
                <th key={column} scope="col" colSpan={2}>
                  {column}
                </th>
              ))}
            </tr>
            <tr>
              <th scope="col" aria-hidden="true" />
              {columns.flatMap((column) => [
                <th key={`${column}-before`} scope="col" className="small muted">
                  Before
                </th>,
                <th key={`${column}-after`} scope="col" className="small muted">
                  After
                </th>,
              ])}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Row key={row.row_id} row={row} columns={columns} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Row({ row, columns }: { row: PreviewRow; columns: string[] }) {
  return (
    <tr className={row.set_aside ? 'preview__row preview__row--aside' : 'preview__row'}>
      <th scope="row" className="muted small">
        {row.row_id}
        {row.set_aside && <span className="preview__tag">set aside</span>}
      </th>
      {columns.flatMap((column) => {
        const cell = row.cells[column]
        return [
          <td key={`${column}-before`}>{show(cell?.before)}</td>,
          <td key={`${column}-after`} className={cell?.changed ? 'preview__changed' : undefined}>
            {show(cell?.after)}
          </td>,
        ]
      })}
    </tr>
  )
}

function show(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === '') return BLANK
  return value
}

function summary(changed: number, setAside: number): string {
  if (setAside > 0 && setAside === changed) {
    return `${formatCount(setAside)} ${setAside === 1 ? 'row is' : 'rows are'} set aside.`
  }
  const rows = `${formatCount(changed)} ${changed === 1 ? 'row changes' : 'rows change'}`
  return setAside > 0 ? `${rows}, ${formatCount(setAside)} of them set aside.` : `${rows}.`
}
