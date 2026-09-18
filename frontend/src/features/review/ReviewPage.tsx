import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  api,
  type DatasetSummary,
  type IssueListResponse,
  type IssueView,
  type RecipeResponse,
  type StepView,
} from '../../api/client'
import { EmptyState, ErrorState, Spinner } from '../../components/states'
import { ColumnTable } from '../upload/ColumnTable'
import { describeRows } from '../upload/format'
import { IssueCard } from './IssueCard'
import { RecipePanel } from './RecipePanel'
import { TIERS, TIER_ORDER } from './copy'

interface ActionError {
  id: string
  where: 'card' | 'panel'
  message: string
}

interface ReviewPageProps {
  dataset: DatasetSummary
  onStartOver: () => void
}

export function ReviewPage({ dataset, onStartOver }: ReviewPageProps) {
  const queryClient = useQueryClient()
  const [showColumns, setShowColumns] = useState(false)
  const [acting, setActing] = useState<string | null>(null)
  const [actionError, setActionError] = useState<ActionError | null>(null)

  const issuesKey = ['issues', dataset.id]
  const issues = useQuery({
    queryKey: issuesKey,
    queryFn: () => api.getIssues(dataset.id),
  })

  /** Every action answers with the new recipe; the list is re-read to follow it. */
  function applyRecipe(recipe: RecipeResponse) {
    queryClient.setQueryData<IssueListResponse>(issuesKey, (current) =>
      current ? { ...current, recipe } : current,
    )
    void queryClient.invalidateQueries({ queryKey: issuesKey })
    void queryClient.invalidateQueries({ queryKey: ['preview', dataset.id] })
  }

  /** A card's failure belongs on that card; a recipe step's has nowhere else to go. */
  function runAction(
    id: string,
    where: ActionError['where'],
    action: () => Promise<RecipeResponse>,
  ): void {
    setActing(id)
    setActionError(null)
    action()
      .then(applyRecipe)
      .catch((error: Error) => setActionError({ id, where, message: error.message }))
      .finally(() => setActing(null))
  }

  const undo = useMutation({
    mutationFn: () => api.undoRecipe(dataset.id),
    onSuccess: applyRecipe,
  })

  if (issues.isPending) {
    return <Spinner label="Looking through your file…" />
  }
  if (issues.isError) {
    return (
      <ErrorState
        message={issues.error.message}
        onRetry={() => void issues.refetch()}
        retrying={issues.isFetching}
      />
    )
  }

  const { issues: found, recipe, needs_decision: decisions } = issues.data
  const list = found ?? []
  const busyWith = (id: string) => acting === id || undo.isPending
  const errorFor = (id: string) =>
    actionError?.where === 'card' && actionError.id === id ? actionError.message : null
  const panelError = actionError?.where === 'panel' ? actionError.message : null

  return (
    <section className="review" aria-labelledby="review-title">
      <header className="review__head">
        <div>
          <h2 id="review-title" className="review__filename">
            {dataset.filename}
          </h2>
          <p className="muted">
            {describeRows(dataset.row_count, dataset.column_count)}
            {decisions > 0 && <> · {decisions} to decide</>}
          </p>
        </div>
        <div className="review__head-actions">
          <button
            type="button"
            className="link-button"
            onClick={() => setShowColumns(!showColumns)}
            aria-expanded={showColumns}
          >
            {showColumns ? 'Hide columns' : 'See the columns'}
          </button>
          <button type="button" className="button button--secondary" onClick={onStartOver}>
            Upload a different file
          </button>
        </div>
      </header>

      {showColumns && <ColumnTable columns={dataset.columns} />}

      <div className="review__layout">
        <div className="review__issues">
          {list.length === 0 ? (
            <EmptyState title="Nothing needs fixing — this file is already tidy.">
              <p className="muted small">
                We looked for blanks, repeated rows, mixed spellings, and numbers or dates stored
                as text.
              </p>
            </EmptyState>
          ) : (
            TIER_ORDER.map((tier) => {
              const forTier = list.filter((issue: IssueView) => issue.tier === tier)
              if (forTier.length === 0) return null
              return (
                <section key={tier} className="group" aria-labelledby={`group-${tier}`}>
                  <h3 id={`group-${tier}`} className="group__title">
                    {TIERS[tier].title}
                    <span className="group__count">{forTier.length}</span>
                  </h3>
                  <p className="muted small">{TIERS[tier].blurb}</p>
                  {forTier.map((issue: IssueView) => (
                    <IssueCard
                      key={issue.id}
                      datasetId={dataset.id}
                      issue={issue}
                      busy={busyWith(issue.id)}
                      error={errorFor(issue.id)}
                      onAccept={(choiceId) =>
                        runAction(issue.id, 'card', () =>
                          api.acceptIssue(dataset.id, issue.id, choiceId),
                        )
                      }
                      onReject={() =>
                        runAction(issue.id, 'card', () => api.rejectIssue(dataset.id, issue.id))
                      }
                    />
                  ))}
                </section>
              )
            })
          )}
        </div>

        <RecipePanel
          recipe={recipe}
          busy={acting !== null || undo.isPending}
          onToggle={(step: StepView, enabled: boolean) =>
            runAction(step.id, 'panel', () => api.setStepEnabled(dataset.id, step.id, enabled))
          }
          onRemove={(step: StepView) =>
            runAction(step.id, 'panel', () => api.removeStep(dataset.id, step.id))
          }
          onUndo={() => undo.mutate()}
        />
      </div>

      {(panelError || undo.error) && (
        <p className="review__error" role="alert">
          {panelError ?? undo.error?.message}
        </p>
      )}
    </section>
  )
}
