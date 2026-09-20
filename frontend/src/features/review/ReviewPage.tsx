import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  api,
  type AiResponse,
  type DatasetSummary,
  type IssueListResponse,
  type IssueView,
  type RecipeResponse,
  type StepView,
} from '../../api/client'
import { ErrorState, Spinner } from '../../components/states'
import { ComparePage } from '../compare/ComparePage'
import { ColumnTable } from '../upload/ColumnTable'
import { describeRows } from '../upload/format'
import { IssueList } from './IssueList'
import { RecipePanel } from './RecipePanel'

type Tab = 'review' | 'changed'

/** Cards a model added, and wording it improved, folded into the rule-based list. */
function withAiHelp(issues: IssueView[], ai: AiResponse | undefined): IssueView[] {
  if (!ai) return issues
  const byId = new Map(issues.map((issue) => [issue.id, issue]))
  for (const added of ai.added ?? []) {
    if (!byId.has(added.id)) byId.set(added.id, added)
  }
  return [...byId.values()].map((issue) => {
    const better = ai.issue_copy?.[issue.id]
    return better ? { ...issue, title: better.title, explanation: better.explanation } : issue
  })
}

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
  const [tab, setTab] = useState<Tab>('review')
  const [showColumns, setShowColumns] = useState(false)
  const [acting, setActing] = useState<string | null>(null)
  const [actionError, setActionError] = useState<ActionError | null>(null)
  const [highlighted, setHighlighted] = useState<string[]>([])

  const issuesKey = ['issues', dataset.id]
  const issues = useQuery({
    queryKey: issuesKey,
    queryFn: () => api.getIssues(dataset.id),
  })

  // Asked for once, after the rule-based review is already on screen. Whatever
  // comes back is extra; nothing here waits on it.
  const ai = useQuery({
    queryKey: ['ai', dataset.id],
    queryFn: () => api.getAiSuggestions(dataset.id),
    enabled: issues.isSuccess,
    staleTime: Infinity,
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
  const list = withAiHelp(found ?? [], ai.data)
  const steps = recipe.steps ?? []
  const aiFailed = ai.data?.status === 'failed'
  const busyWith = (id: string) => acting === id || undo.isPending
  const errorFor = (id: string) =>
    actionError?.where === 'card' && actionError.id === id ? actionError.message : null
  const panelError = actionError?.where === 'panel' ? actionError.message : null
  const accept = (issue: IssueView, choiceId?: string) =>
    runAction(issue.id, 'card', () => api.acceptIssue(dataset.id, issue.id, choiceId))

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

      <div className="tabs" role="tablist" aria-label="What to look at">
        <button
          type="button"
          role="tab"
          id="tab-review"
          aria-selected={tab === 'review'}
          aria-controls="panel-review"
          className={`tabs__tab${tab === 'review' ? ' tabs__tab--on' : ''}`}
          onClick={() => setTab('review')}
        >
          Review
          {list.length > 0 && <span className="group__count">{list.length}</span>}
        </button>
        <button
          type="button"
          role="tab"
          id="tab-changed"
          aria-selected={tab === 'changed'}
          aria-controls="panel-changed"
          className={`tabs__tab${tab === 'changed' ? ' tabs__tab--on' : ''}`}
          onClick={() => setTab('changed')}
        >
          What changed
        </button>
      </div>

      <div className="review__layout">
        <div
          className="review__issues"
          role="tabpanel"
          id={tab === 'review' ? 'panel-review' : 'panel-changed'}
          aria-labelledby={tab === 'review' ? 'tab-review' : 'tab-changed'}
        >
          {tab === 'review' ? (
            <IssueList
              datasetId={dataset.id}
              issues={list}
              busyWith={busyWith}
              errorFor={errorFor}
              onAccept={accept}
              onReject={(issue) =>
                runAction(issue.id, 'card', () => api.rejectIssue(dataset.id, issue.id))
              }
              note={aiFailed ? (ai.data?.note ?? null) : null}
            />
          ) : (
            <ComparePage
              datasetId={dataset.id}
              recipeKey={recipe.recipe_key}
              steps={steps}
              issues={list}
              choosing={acting}
              onChoose={(issueId, choiceId) => {
                const issue = list.find((candidate) => candidate.id === issueId)
                if (issue) accept(issue, choiceId)
              }}
              questionLabels={ai.data?.question_labels ?? {}}
              onHighlight={setHighlighted}
              onBackToReview={() => setTab('review')}
            />
          )}
        </div>

        <RecipePanel
          datasetId={dataset.id}
          recipe={recipe}
          busy={acting !== null || undo.isPending}
          highlighted={highlighted}
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
