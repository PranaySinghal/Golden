import type { DatasetSummary, ReingestRequest } from '../../api/client'
import { ColumnTable } from './ColumnTable'
import { formatCount } from './format'

interface FileOptionsPanelProps {
  dataset: DatasetSummary
  onReread: (request: ReingestRequest) => void
  rereading: boolean
  rereadError: string | null
  /** How much work a re-read would throw away. Zero means nothing to warn about. */
  stepCount: number
}

export function FileOptionsPanel({
  dataset,
  onReread,
  rereading,
  rereadError,
  stepCount,
}: FileOptionsPanelProps) {
  const showSheets = dataset.format === 'xlsx' && dataset.available_sheets.length > 1
  const skipped = dataset.empty_rows_skipped

  // Reading the file again starts the whole session over on the server, so ask
  // first once there is something to lose.
  function reread(request: ReingestRequest) {
    if (stepCount > 0) {
      const fixes = stepCount === 1 ? 'the one fix' : `all ${formatCount(stepCount)} fixes`
      const agreed = window.confirm(
        `Reading the file again starts from scratch, so ${fixes} so far will be cleared. Carry on?`,
      )
      if (!agreed) return
    }
    onReread(request)
  }

  return (
    <section className="file-options" aria-label="How this file was read" aria-busy={rereading}>
      <div className="file-options__controls">
        {showSheets && (
          <label className="field">
            <span>Sheet</span>
            <select
              value={dataset.sheet_name ?? ''}
              disabled={rereading}
              onChange={(event) => reread({ sheet: event.target.value, header: dataset.header_mode })}
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
              reread({
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

      <p className="muted small file-options__warning">
        Changing either of these reads the file again from scratch — anything you have accepted so
        far is cleared.
      </p>

      {skipped > 0 && (
        <p className="muted small">
          {formatCount(skipped)} empty {skipped === 1 ? 'row was' : 'rows were'} skipped.
        </p>
      )}

      {rereadError && (
        <p className="alert" role="alert">
          {rereadError}
        </p>
      )}

      <ColumnTable columns={dataset.columns} />
    </section>
  )
}
