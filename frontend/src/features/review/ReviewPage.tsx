import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  api,
  type AiResponse,
  type DatasetSummary,
  type IssueListResponse,
  type IssueView,
  type RecipeResponse,
  type ReingestRequest,
  type StepView,
} from '../../api/client'
import { ErrorState, Spinner } from '../../components/states'
import { CanvasPage } from '../canvas/CanvasPage'
import { ComparePage } from '../compare/ComparePage'
import { FileOptionsPanel } from '../upload/FileOptionsPanel'
import { describeRows } from '../upload/format'
import { IssueList } from './IssueList'
import { issueAnchor } from './anchors'
import { MainProblems } from './MainProblems'
import { RecipeOutcome } from './RecipeOutcome'
import { RecipePanel } from './RecipePanel'

type Tab = 'review' | 'changed' | 'canvas'

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
  /** A re-read replaces the file behind the same id; the fresh summary goes up. */
  onDataset: (dataset: DatasetSummary) => void
  onStartOver: () => void
}

export function ReviewPage({ dataset, onDataset, onStartOver }: ReviewPageProps) {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('review')
  const [showColumns, setShowColumns] = useState(false)
  const [acting, setActing] = useState<string | null>(null)
  const [actionError, setActionError] = useState<ActionError | null>(null)
  const [highlighted, setHighlighted] = useState<string[]>([])
  const [recipeOpen, setRecipeOpen] = useState(true)
  // A card a link points at, which the list must show even if its kind is folded away.
  const [revealed, setRevealed] = useState<string | null>(null)
  // What came of steps saved from another file and attached to the upload.
  const outcome = dataset.recipe_outcome ?? null

  const issuesKey = ['issues', dataset.id]
  const issues = useQuery({
    queryKey: issuesKey,
    queryFn: () => api.getIssues(dataset.id),
  })

  // Asked for after the rule-based review is already on screen. Whatever comes
  // back is extra; nothing here waits on it. Keyed on the recipe because the
  // story describes the answers, which move; the server still works out the
  // suggestions and wording only once. The previous reply stays on screen while
  // a new one is fetched, so improved wording doesn't flicker back to templates.
  const recipeKey = issues.data?.recipe.recipe_key
  const ai = useQuery({
    queryKey: ['ai', dataset.id, recipeKey],
    queryFn: () => api.getAiSuggestions(dataset.id),
    enabled: issues.isSuccess,
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  })

  /** Every action answers with the new recipe; the list is re-read to follow it. */
  function applyRecipe(recipe: RecipeResponse) {
    queryClient.setQueryData<IssueListResponse>(issuesKey, (current) =>
      current ? { ...current, recipe } : current,
    )
    void queryClient.invalidateQueries({ queryKey: issuesKey })
    void queryClient.invalidateQueries({ queryKey: ['preview', dataset.id] })
    // What can be looked up, and what a lookup filled in, both follow the recipe.
    void queryClient.invalidateQueries({ queryKey: ['connectors', dataset.id] })
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

  const reread = useMutation({
    mutationFn: (request: ReingestRequest) => api.reingestDataset(dataset.id, request),
    onSuccess: (fresh) => {
      // Reading the file again keeps the id but replaces the whole session
      // behind it: new profile, empty recipe, issues and comparison thrown away
      // (backend app/store.py). Every key here is built on that id, so nothing
      // cached under it survives. removeQueries rather than invalidateQueries,
      // because the model's reply never goes stale on its own and an empty
      // recipe can land on a recipe_key this session has already cached — both
      // would otherwise be served straight back.
      queryClient.removeQueries({ queryKey: ['issues', fresh.id] })
      queryClient.removeQueries({ queryKey: ['ai', fresh.id] })
      queryClient.removeQueries({ queryKey: ['compare', fresh.id] })
      queryClient.removeQueries({ queryKey: ['preview', fresh.id] })
      queryClient.removeQueries({ queryKey: ['canvas', fresh.id] })
      queryClient.removeQueries({ queryKey: ['canvas-ideas', fresh.id] })
      queryClient.removeQueries({ queryKey: ['connectors', fresh.id] })
      queryClient.setQueryData(['dataset', fresh.id], fresh)
      // These all point at ids in the recipe that no longer exists.
      setTab('review')
      setHighlighted([])
      setActionError(null)
      setActing(null)
      onDataset(fresh)
    },
  })

  const decisions = issues.data?.needs_decision ?? 0
  const list = withAiHelp(issues.data?.issues ?? [], ai.data)
  const steps = issues.data?.recipe.steps ?? []
  const aiFailed = ai.data?.status === 'failed'
  const busyWith = (id: string) => acting === id || undo.isPending
  const errorFor = (id: string) =>
    actionError?.where === 'card' && actionError.id === id ? actionError.message : null
  const panelError = actionError?.where === 'panel' ? actionError.message : null
  /** Take the reader to a problem's card, from the tab it lives on. */
  function showIssue(issue: IssueView) {
    setTab('review')
    setRevealed(issue.id)
    // The card may only be drawn once the review tab is showing again.
    window.requestAnimationFrame(() => {
      const card = document.getElementById(issueAnchor(issue.id))
      if (!card) return
      card.scrollIntoView({ behavior: 'smooth', block: 'center' })
      card.classList.add('card--lit')
      window.setTimeout(() => card.classList.remove('card--lit'), 1600)
    })
  }

  const accept = (issue: IssueView, choiceId?: string) =>
    runAction(issue.id, 'card', () => api.acceptIssue(dataset.id, issue.id, choiceId))

  return (
    <section className="review" aria-labelledby="review-title">
      <header className="review__head">
        <div>
          <h1 id="review-title" className="review__filename">
            {dataset.filename}
          </h1>
          <p className="muted">
            {describeRows(dataset.row_count, dataset.column_count)}
            {dataset.sheet_name && <> · sheet “{dataset.sheet_name}”</>}
            {decisions > 0 && <> · {decisions} to decide</>}
          </p>
          <p className="review__about">{dataset.description}</p>
          {issues.data && <MainProblems issues={list} onShow={showIssue} />}
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

      {outcome && <RecipeOutcome outcome={outcome} />}

      {showColumns && (
        <FileOptionsPanel
          dataset={dataset}
          onReread={(request) => reread.mutate(request)}
          rereading={reread.isPending}
          rereadError={reread.error?.message ?? null}
          stepCount={steps.length}
        />
      )}

      {dataset.row_count === 0 && (
        <p className="notice">
          This file has column names but no rows yet. Add some data and upload it again.
        </p>
      )}

      {issues.isError ? (
        <ErrorState
          message={issues.error.message}
          onRetry={() => void issues.refetch()}
          retrying={issues.isFetching}
        />
      ) : !issues.data ? (
        <Spinner label="Looking through your file…" />
      ) : (
        <>
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
        <button
          type="button"
          role="tab"
          id="tab-canvas"
          aria-selected={tab === 'canvas'}
          aria-controls="panel-canvas"
          className={`tabs__tab${tab === 'canvas' ? ' tabs__tab--on' : ''}`}
          onClick={() => setTab('canvas')}
        >
          Canvas
        </button>
      </div>

      <div className="review__layout">
        <div
          className="review__issues"
          role="tabpanel"
          id={`panel-${tab}`}
          aria-labelledby={`tab-${tab}`}
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
              reveal={revealed}
            />
          ) : tab === 'canvas' ? (
            <CanvasPage
              datasetId={dataset.id}
              recipeKey={issues.data.recipe.recipe_key}
              busy={acting !== null || undo.isPending}
              onRecipe={applyRecipe}
              onRemove={(stepId) =>
                runAction(stepId, 'panel', () => api.removeStep(dataset.id, stepId))
              }
            />
          ) : (
            <ComparePage
              datasetId={dataset.id}
              recipeKey={issues.data.recipe.recipe_key}
              steps={steps}
              issues={list}
              choosing={acting}
              onChoose={(issueId, choiceId) => {
                const issue = list.find((candidate) => candidate.id === issueId)
                if (issue) accept(issue, choiceId)
              }}
              questionLabels={ai.data?.question_labels ?? {}}
              aiStory={ai.data?.story ?? null}
              onHighlight={(stepIds) => {
                setHighlighted(stepIds)
                // "Why?" points at steps in the recipe; show them if they're hidden.
                if (stepIds.length > 0) setRecipeOpen(true)
              }}
              onBackToReview={() => setTab('review')}
            />
          )}
        </div>

        <RecipePanel
          datasetId={dataset.id}
          recipe={issues.data.recipe}
          busy={acting !== null || undo.isPending}
          highlighted={highlighted}
          open={recipeOpen}
          onOpenChange={setRecipeOpen}
          onToggle={(step: StepView, enabled: boolean) =>
            runAction(step.id, 'panel', () => api.setStepEnabled(dataset.id, step.id, enabled))
          }
          onRemove={(step: StepView) =>
            runAction(step.id, 'panel', () => api.removeStep(dataset.id, step.id))
          }
          onUndo={() => undo.mutate()}
        />
      </div>
        </>
      )}

      {(panelError || undo.error) && (
        <p className="review__error" role="alert">
          {panelError ?? undo.error?.message}
        </p>
      )}
    </section>
  )
}
