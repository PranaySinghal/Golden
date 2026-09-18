import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api, type AnswerCardView, type IssueView, type StepView } from '../../api/client'
import { EmptyState, ErrorState, Spinner } from '../../components/states'
import { AnswerCard } from './AnswerCard'
import { DecisionsStrip } from './DecisionsStrip'

interface ComparePageProps {
  datasetId: string
  recipeKey: string
  steps: StepView[]
  issues: IssueView[]
  choosing: string | null
  onChoose: (issueId: string, choiceId: string) => void
  onHighlight: (stepIds: string[]) => void
  onBackToReview: () => void
}

export function ComparePage({
  datasetId,
  recipeKey,
  steps,
  issues,
  choosing,
  onChoose,
  onHighlight,
  onBackToReview,
}: ComparePageProps) {
  const [showRules, setShowRules] = useState(false)

  // Keyed on what the cleaned rows look like: going back to an earlier answer
  // is the same key, so the answer is already here and nothing is asked again.
  const comparison = useQuery({
    queryKey: ['compare', datasetId, recipeKey],
    queryFn: () => api.getComparison(datasetId),
    placeholderData: keepPreviousData,
  })

  if (comparison.isPending) return <Spinner label="Working out what changed…" />
  if (comparison.isError) {
    return (
      <ErrorState
        message={comparison.error.message}
        onRetry={() => void comparison.refetch()}
        retrying={comparison.isFetching}
      />
    )
  }

  const { cards, unlocked, unchanged, before_rules: rules, has_steps: hasSteps } = comparison.data
  const changed = cards ?? []
  const nowAskable = unlocked ?? []
  const same = unchanged ?? []
  const updating = comparison.isFetching

  const explainer = (
    <p className="compare__summary">
      {summary(changed.length, same.length + changed.length + nowAskable.length)}{' '}
      <button
        type="button"
        className="link-button"
        aria-expanded={showRules}
        onClick={() => setShowRules(!showRules)}
      >
        What does “before” mean?
      </button>
    </p>
  )

  return (
    <section className="compare" aria-labelledby="compare-title" aria-busy={updating}>
      <h2 id="compare-title" className="visually-hidden">
        What changed
      </h2>

      <DecisionsStrip issues={issues} busy={choosing} onChoose={onChoose} />
      {explainer}
      {showRules && (
        <div className="rules">
          <p className="small">
            “Before” is how a typical spreadsheet reads your file, as it was uploaded:
          </p>
          <ul className="rules__list small">
            {(rules ?? []).map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
        </div>
      )}

      {!hasSteps && (
        <EmptyState title="Nothing has been cleaned yet.">
          <p className="muted small">
            Accept a suggestion and you’ll see what it does to your answers.
          </p>
          <button type="button" className="button" onClick={onBackToReview}>
            Back to the review
          </button>
        </EmptyState>
      )}

      {hasSteps && changed.length === 0 && (
        <EmptyState title="Your answers came out the same either way.">
          <p className="muted small">
            We asked {same.length} {same.length === 1 ? 'question' : 'questions'} of your file
            before and after cleaning, and every answer matched. Cleaning tidied the values without
            moving the numbers.
          </p>
        </EmptyState>
      )}

      {changed.length > 0 && (
        <div className="compare__cards">
          {changed.map((card: AnswerCardView) => (
            <AnswerCard
              key={card.question_id}
              datasetId={datasetId}
              card={card}
              steps={steps}
              updating={updating}
              onHighlight={onHighlight}
            />
          ))}
        </div>
      )}

      {nowAskable.length > 0 && (
        <section className="group" aria-labelledby="unlocked-title">
          <h3 id="unlocked-title" className="group__title">
            Now you can ask
            <span className="group__count">{nowAskable.length}</span>
          </h3>
          <p className="muted small">Your file couldn’t answer these at all until it was cleaned.</p>
          <div className="compare__cards">
            {nowAskable.map((card: AnswerCardView) => (
              <AnswerCard
                key={card.question_id}
                datasetId={datasetId}
                card={card}
                steps={steps}
                updating={updating}
                onHighlight={onHighlight}
              />
            ))}
          </div>
        </section>
      )}

      {same.length > 0 && changed.length > 0 && (
        <details className="same">
          <summary>
            {same.length} {same.length === 1 ? 'answer' : 'answers'} came out the same
          </summary>
          <ul className="same__list muted small">
            {same.map((label: string) => (
              <li key={label}>{label}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}

function summary(changed: number, asked: number): string {
  if (asked === 0) return 'Nothing to compare yet.'
  // The count lives in the empty state below when nothing moved, so it isn't said twice.
  if (changed === 0) return 'We compared every answer, before and after cleaning.'
  const answers = changed === 1 ? 'answer' : 'answers'
  return `Cleaning changed ${changed} of your ${asked} ${answers}.`
}
