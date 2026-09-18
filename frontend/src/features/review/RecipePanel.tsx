import { useState } from 'react'

import { api, type RecipeResponse, type StepView } from '../../api/client'
import { rowsKept, stepEffect } from './copy'

interface RecipePanelProps {
  datasetId: string
  recipe: RecipeResponse
  busy: boolean
  highlighted: string[]
  onToggle: (step: StepView, enabled: boolean) => void
  onRemove: (step: StepView) => void
  onUndo: () => void
}

type Format = 'csv' | 'recipe'

export function RecipePanel({
  datasetId,
  recipe,
  busy,
  highlighted,
  onToggle,
  onRemove,
  onUndo,
}: RecipePanelProps) {
  const steps = recipe.steps ?? []
  const [downloading, setDownloading] = useState<Format | null>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  function save(format: Format) {
    setDownloading(format)
    setDownloadError(null)
    api
      .exportDataset(datasetId, format)
      .then(({ blob, filename }) => saveToDisk(blob, filename))
      .catch((error: Error) => setDownloadError(error.message))
      .finally(() => setDownloading(null))
  }

  return (
    <aside className="panel" aria-labelledby="recipe-title" aria-busy={busy}>
      <div className="panel__head">
        <h3 id="recipe-title" className="panel__title">
          What we&apos;re doing
        </h3>
        <p className="muted small">{rowsKept(recipe.row_count, recipe.set_aside_count)}</p>
      </div>

      {steps.length === 0 ? (
        <p className="muted small">
          Nothing yet. Accept a suggestion and it will show up here, in the order it runs.
        </p>
      ) : (
        <ol className="panel__steps">
          {steps.map((step) => (
            <li
              key={step.id}
              className={[
                'panel__step',
                step.status === 'blocked' ? 'panel__step--blocked' : '',
                highlighted.includes(step.id) ? 'panel__step--lit' : '',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              <label className="panel__toggle">
                <input
                  type="checkbox"
                  checked={step.enabled}
                  disabled={busy}
                  onChange={(event) => onToggle(step, event.target.checked)}
                />
                <span className="visually-hidden">Use this step</span>
              </label>
              <div className="panel__body">
                <p className="panel__description">{step.description}</p>
                <p className="muted small">{stepEffect(step)}</p>
              </div>
              <button
                type="button"
                className="link-button"
                disabled={busy}
                onClick={() => onRemove(step)}
                aria-label={`Remove: ${step.description}`}
              >
                Remove
              </button>
            </li>
          ))}
        </ol>
      )}

      <button
        type="button"
        className="button button--secondary"
        disabled={busy || !recipe.can_undo}
        onClick={onUndo}
      >
        Undo last change
      </button>

      <div className="panel__downloads">
        <button
          type="button"
          className="button"
          disabled={downloading !== null}
          onClick={() => save('csv')}
        >
          {downloading === 'csv' ? 'Preparing…' : 'Download cleaned file'}
        </button>
        <button
          type="button"
          className="link-button"
          disabled={downloading !== null}
          onClick={() => save('recipe')}
        >
          {downloading === 'recipe' ? 'Preparing…' : 'Download the steps'}
        </button>
        <p className="muted small">
          The cleaned file opens in a spreadsheet. The steps can be used again on next month&apos;s
          file.
        </p>
        {downloadError && (
          <p className="card__error" role="alert">
            {downloadError}
          </p>
        )}
      </div>
    </aside>
  )
}

/** Hand the file to the browser under the name the server chose. */
function saveToDisk(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
