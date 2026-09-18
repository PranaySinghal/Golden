import type { RecipeResponse, StepView } from '../../api/client'
import { rowsKept, stepEffect } from './copy'

interface RecipePanelProps {
  recipe: RecipeResponse
  busy: boolean
  onToggle: (step: StepView, enabled: boolean) => void
  onRemove: (step: StepView) => void
  onUndo: () => void
}

export function RecipePanel({ recipe, busy, onToggle, onRemove, onUndo }: RecipePanelProps) {
  const steps = recipe.steps ?? []

  return (
    <aside className="panel" aria-labelledby="recipe-title" aria-busy={busy}>
      <div className="panel__head">
        <h3 id="recipe-title" className="panel__title">
          What we're doing
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
              className={`panel__step${step.status === 'blocked' ? ' panel__step--blocked' : ''}`}
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
    </aside>
  )
}
