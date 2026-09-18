import type { DatasetSummary, ReingestRequest } from '../../api/client'
import { ColumnTable } from './ColumnTable'
import { describeRows, formatCount } from './format'

interface DatasetOverviewProps {
  dataset: DatasetSummary
  onReread: (request: ReingestRequest) => void
  rereading: boolean
  rereadError: string | null
  onUploadAnother: () => void
  onReview: () => void
}

export function DatasetOverview({
  dataset,
  onReread,
  rereading,
  rereadError,
  onUploadAnother,
  onReview,
}: DatasetOverviewProps) {
  const showSheets = dataset.format === 'xlsx' && dataset.available_sheets.length > 1
  const skipped = dataset.empty_rows_skipped

  return (
    <section className="overview" aria-labelledby="overview-title" aria-busy={rereading}>
      <div className="overview__header">
        <div>
          <h2 id="overview-title" className="overview__filename">
            {dataset.filename}
          </h2>
          <p className="overview__counts">
            {describeRows(dataset.row_count, dataset.column_count)}
            {dataset.sheet_name && <> · sheet “{dataset.sheet_name}”</>}
          </p>
          {skipped > 0 && (
            <p className="muted small">
              {formatCount(skipped)} empty {skipped === 1 ? 'row was' : 'rows were'} skipped.
            </p>
          )}
        </div>
        <button type="button" className="button button--secondary" onClick={onUploadAnother}>
          Upload a different file
        </button>
      </div>

      <div className="overview__options">
        {showSheets && (
          <label className="field">
            <span>Sheet</span>
            <select
              value={dataset.sheet_name ?? ''}
              disabled={rereading}
              onChange={(event) =>
                onReread({ sheet: event.target.value, header: dataset.header_mode })
              }
            >
              {dataset.available_sheets.map((sheet) => (
                <option key={sheet} value={sheet}>
                  {sheet}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={dataset.header_detected}
            disabled={rereading}
            onChange={(event) =>
              onReread({
                sheet: dataset.sheet_name,
                header: event.target.checked ? 'header' : 'data',
              })
            }
          />
          <span>First row has column names</span>
        </label>
        {rereading && (
          <span className="muted small" role="status">
            Reading the file again…
          </span>
        )}
      </div>

      {rereadError && (
        <p className="alert" role="alert">
          {rereadError}
        </p>
      )}

      {dataset.row_count === 0 && (
        <p className="notice">
          This file has column names but no rows yet. Add some data and upload it again.
        </p>
      )}

      <ColumnTable columns={dataset.columns} />

      {dataset.row_count > 0 && (
        <div className="overview__next">
          <button type="button" className="button" onClick={onReview} disabled={rereading}>
            See what needs fixing
          </button>
          <p className="muted small">
            We'll look for blanks, repeated rows, mixed spellings, and numbers or dates stored as
            text.
          </p>
        </div>
      )}
    </section>
  )
}
