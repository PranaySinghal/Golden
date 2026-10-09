import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import {
  api,
  type CanvasResponse,
  type ColumnSuggestion,
  type DatasetConnectors,
  type FillPreview,
  type FillRequest,
  type RecipeResponse,
} from '../../api/client'
import { InfoTip } from '../../components/InfoTip'
import { EmptyState, ErrorState, Spinner } from '../../components/states'
import { formatCount } from '../upload/format'

interface CanvasPageProps {
  datasetId: string
  /** Changes whenever the cleaned rows do, so the table here follows the recipe. */
  recipeKey: string
  /** Something else on the page is changing the recipe. */
  busy: boolean
  /** Adding a column answers with the new recipe; the rest of the page follows it. */
  onRecipe: (recipe: RecipeResponse) => void
  onRemove: (stepId: string) => void
}

const AT_THE_END = ''
const BLANK = '(blank)'

export function CanvasPage({ datasetId, recipeKey, busy, onRecipe, onRemove }: CanvasPageProps) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [after, setAfter] = useState(AT_THE_END)
  const [picked, setPicked] = useState('')
  const [useAi, setUseAi] = useState(true)
  // Where a fill has got to: asking to send, then showing a few answers to judge.
  const [fillStage, setFillStage] = useState<'idle' | 'consent' | 'preview'>('idle')

  const canvas = useQuery({
    queryKey: ['canvas', datasetId, recipeKey],
    queryFn: () => api.getCanvas(datasetId),
    placeholderData: keepPreviousData,
  })

  // The built-in ideas answer at once. A model's, when one is set up, take a
  // few seconds and replace them when they arrive; nothing waits on them.
  const quick = useQuery({
    queryKey: ['canvas-ideas', datasetId, 'quick', recipeKey],
    queryFn: () => api.getCanvasSuggestions(datasetId, false),
    placeholderData: keepPreviousData,
  })
  const smart = useQuery({
    queryKey: ['canvas-ideas', datasetId, 'smart', recipeKey],
    queryFn: () => api.getCanvasSuggestions(datasetId, true),
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  })
  const ideas = smart.data ?? quick.data
  const suggestions = ideas?.suggestions ?? []
  const chosen = suggestions.find((suggestion) => suggestion.name === picked) ?? null

  // Which outside services this file may use. Shared with the Connectors panel.
  const connectors = useQuery({
    queryKey: ['connectors', datasetId],
    queryFn: () => api.getDatasetConnectors(datasetId),
  })
  const aiFill = connectors.data?.connectors.find((connector) => connector.id === 'ai_fill')
  const fillPlan = aiFill?.enabled ? (chosen?.fill ?? null) : null
  // The idea's own name and meaning are what the model is told the column is.
  const fillRequest: FillRequest | null =
    chosen && fillPlan && name.trim() === chosen.name
      ? {
          name: chosen.name,
          based_on: fillPlan.based_on,
          instruction: `${chosen.name}. ${chosen.reason}`.slice(0, 200),
          kind: fillPlan.kind,
          choices: fillPlan.choices ?? [],
          context: [],
        }
      : null
  const filling = fillRequest !== null && useAi

  const preview = useMutation({
    mutationFn: async (request: FillRequest): Promise<FillPreview> => {
      // Agreeing to send is also what switches the service on for this file.
      if (!aiFill?.active) {
        const fresh = await api.setConnectorActive(datasetId, 'ai_fill', true)
        queryClient.setQueryData<DatasetConnectors>(['connectors', datasetId], fresh)
      }
      return api.previewAiFill(datasetId, request, true)
    },
    onSuccess: () => setFillStage('preview'),
  })

  const fill = useMutation({
    mutationFn: (request: FillRequest) =>
      api.runConnectorLookup(datasetId, { connector: 'ai_fill', fill: request, consent: true }),
    onSuccess: (fresh: DatasetConnectors) => {
      queryClient.setQueryData(['connectors', datasetId], fresh)
      void queryClient.invalidateQueries({ queryKey: ['canvas', datasetId] })
      resetForm()
      onRecipe(fresh.recipe)
    },
  })

  function resetForm() {
    setName('')
    setText('')
    setPicked('')
    setFillStage('idle')
    preview.reset()
  }

  const add = useMutation({
    mutationFn: () =>
      api.addCanvasColumn(datasetId, {
        name,
        value: text.trim() ? text : null,
        insert_after: after === AT_THE_END ? null : after,
      }),
    onSuccess: (fresh: CanvasResponse) => {
      queryClient.setQueryData(['canvas', datasetId, fresh.recipe.recipe_key], fresh)
      resetForm()
      onRecipe(fresh.recipe)
    },
  })

  function pick(suggestion: ColumnSuggestion | null) {
    setPicked(suggestion?.name ?? '')
    setFillStage('idle')
    setUseAi(true)
    preview.reset()
    fill.reset()
    if (!suggestion) return
    setName(suggestion.name)
    setText(suggestion.placeholder ?? '')
    add.reset()
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return
    // A column a model fills in is shown to the user first; nothing is added yet.
    if (filling) setFillStage('consent')
    else add.mutate()
  }

  if (canvas.isPending) return <Spinner label="Laying out your table…" />
  if (canvas.isError) {
    return (
      <ErrorState
        message={canvas.error.message}
        onRetry={() => void canvas.refetch()}
        retrying={canvas.isFetching}
      />
    )
  }

  const { columns, rows, row_count: rowCount, reasons = {} } = canvas.data
  const working = busy || add.isPending || preview.isPending || fill.isPending

  return (
    <div className="canvas">
      <p className="muted">
        Alter sheet - update values. Each step is undoable and the file downloadable.
      </p>
      {ideas?.about && <p className="canvas__about">{ideas.about}</p>}

      <form className="canvas__form" onSubmit={submit} aria-label="Add a column">
        <label className="canvas__field">
          <span>Ideas for this file</span>
          {quick.isPending && !ideas ? (
            <span className="muted small" role="status">
              Thinking of columns…
            </span>
          ) : quick.isError && !ideas ? (
            <span className="muted small">Ideas couldn’t be loaded. You can still add your own.</span>
          ) : suggestions.length === 0 ? (
            <span className="muted small">No more ideas. You can still add your own.</span>
          ) : (
            <select
              value={picked}
              disabled={working}
              onChange={(event) =>
                pick(suggestions.find((s) => s.name === event.target.value) ?? null)
              }
            >
              <option value="">Pick an idea…</option>
              {suggestions.map((suggestion) => (
                <option key={suggestion.name} value={suggestion.name}>
                  {suggestion.name}
                </option>
              ))}
            </select>
          )}
        </label>
        {chosen && (
          <p className="canvas__reason small">
            {chosen.source === 'ai' && <span className="chip chip--soft">Suggested by AI</span>}
            {chosen.reason}
            {chosen.live_source && (
              <>
                {' '}
                <span className="muted">
                  Could be filled in from: {lowerFirst(chosen.live_source)}. This adds an empty
                  column; see Connectors at the top of the page for what can be looked up.
                </span>
              </>
            )}
          </p>
        )}
        {fillRequest && fillPlan && (
          <label className="checkbox canvas__ai">
            <input
              type="checkbox"
              checked={useAi}
              disabled={working || fillStage !== 'idle'}
              onChange={(event) => setUseAi(event.target.checked)}
            />
            <span>
              Fill it in with AI, from “{fillPlan.based_on}”
              <span className="muted"> (unverified; blank where it isn’t sure)</span>
            </span>
          </label>
        )}
        {ideas?.status === 'failed' && (
          <p className="muted small">
            Extra ideas couldn’t be fetched just now. These ones still work.
          </p>
        )}

        <div className="canvas__inputs">
          <label className="canvas__field">
            <span>Column name</span>
            <input
              type="text"
              value={name}
              maxLength={255}
              disabled={working}
              onChange={(event) => {
                setName(event.target.value)
                add.reset()
              }}
            />
          </label>
          <label className="canvas__field">
            <span>Text to show in every row (optional)</span>
            <input
              type="text"
              value={text}
              maxLength={1000}
              placeholder="Leave empty for a blank column"
              disabled={working}
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          <label className="canvas__field">
            <span>Where it goes</span>
            <select value={after} disabled={working} onChange={(e) => setAfter(e.target.value)}>
              <option value={AT_THE_END}>At the end</option>
              {columns.map((column) => (
                <option key={column.name} value={column.name}>
                  After “{column.name}”
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="button"
            disabled={working || !name.trim() || fillStage !== 'idle'}
          >
            {add.isPending ? 'Adding…' : filling ? 'Add and fill with AI' : 'Add column'}
          </button>
        </div>
        {filling && fillRequest && fillStage === 'consent' && aiFill && (
          <div className="connectors__consent" role="alertdialog" aria-label="Before anything is sent">
            <p className="connectors__name">
              Before anything is sent
              <InfoTip
                label="What is sent, and to whom"
                text={`Service: ${aiFill.service}. What is sent: ${aiFill.sends}`}
              />
            </p>
            <p className="small">
              AI detects “{fillRequest.name}” for each different value in{' '}
              “{fillRequest.based_on}”. You’ll see sample suggestions first and decide whether to
              fill the rest. Values could be unverified.
            </p>
            <div className="card__actions">
              <button
                type="button"
                className="button"
                disabled={preview.isPending}
                onClick={() => preview.mutate(fillRequest)}
              >
                {preview.isPending ? 'Asking…' : 'Send and show a few answers'}
              </button>
              <button
                type="button"
                className="button button--secondary"
                disabled={preview.isPending}
                onClick={() => setFillStage('idle')}
              >
                Cancel
              </button>
            </div>
            {preview.error && (
              <p className="card__error" role="alert">
                {preview.error.message}
              </p>
            )}
          </div>
        )}
        {filling && fillRequest && fillStage === 'preview' && preview.data && (
          <div className="canvas__preview" role="region" aria-label="A few answers to check">
            <p className="connectors__name">A few answers to check</p>
            <table className="preview__table">
              <thead>
                <tr>
                  <th scope="col">{fillRequest.based_on}</th>
                  <th scope="col">{fillRequest.name}</th>
                </tr>
              </thead>
              <tbody>
                {preview.data.rows.map((row) => (
                  <tr key={row.value}>
                    <td>{row.value}</td>
                    <td>{row.answer ?? <span className="muted">({row.reason ?? 'blank'})</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small">
              If these look right, fill in the rest. Nothing has been added to your table yet.
            </p>
            <div className="card__actions">
              <button
                type="button"
                className="button"
                disabled={fill.isPending}
                onClick={() => fill.mutate(fillRequest)}
              >
                {fill.isPending
                  ? 'Filling in…'
                  : `Fill all ${formatCount(preview.data.total_values)} values`}
              </button>
              <button
                type="button"
                className="button button--secondary"
                disabled={fill.isPending}
                onClick={() => setFillStage('idle')}
              >
                Cancel
              </button>
            </div>
            {fill.error && (
              <p className="card__error" role="alert">
                {fill.error.message}
              </p>
            )}
          </div>
        )}
        {add.error && (
          <p className="card__error" role="alert">
            {add.error.message}
          </p>
        )}
      </form>

      {columns.length === 0 ? (
        <EmptyState title="This table has no columns yet." />
      ) : (
        <div className="preview">
          <p className="muted small">
            {rows.length === 0
              ? 'There are no rows to show.'
              : `Showing the first ${formatCount(rows.length)} of ${formatCount(rowCount)} rows.`}
          </p>
          <div className="table-scroll">
            <table className="preview__table">
              <caption className="visually-hidden">Your table, with the columns you added</caption>
              <thead>
                <tr>
                  {columns.map((column) => (
                    <th
                      key={column.name}
                      scope="col"
                      className={column.step_id ? 'canvas__added' : undefined}
                    >
                      {column.name}
                      {column.label && (
                        <InfoTip label={`About the column ${column.name}`} text={column.label} />
                      )}
                      {column.step_id && (
                        <>
                          <span className="preview__tag">added</span>
                          <button
                            type="button"
                            className="link-button small"
                            disabled={working}
                            aria-label={`Remove the column ${column.name}`}
                            onClick={() => onRemove(column.step_id as string)}
                          >
                            Remove
                          </button>
                        </>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={index}>
                    {row.map((value, position) => (
                      <td
                        key={columns[position]?.name ?? position}
                        className={columns[position]?.step_id ? 'canvas__added' : undefined}
                      >
                        {value ?? (
                          <span className="muted">
                            {/* A looked-up cell that is empty says why. */}
                            {reasonFor(reasons, columns[position]?.name, index) ?? BLANK}
                          </span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function reasonFor(
  reasons: Record<string, (string | null)[]>,
  column: string | undefined,
  row: number,
): string | null {
  const reason = column ? reasons[column]?.[row] : null
  return reason ? `(${reason})` : null
}

function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1)
}
