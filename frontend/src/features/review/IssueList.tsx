import type { IssueView } from '../../api/client'
import { EmptyState } from '../../components/states'
import { IssueCard } from './IssueCard'
import { TIERS, TIER_ORDER } from './copy'

interface IssueListProps {
  datasetId: string
  issues: IssueView[]
  busyWith: (id: string) => boolean
  errorFor: (id: string) => string | null
  onAccept: (issue: IssueView, choiceId?: string) => void
  onReject: (issue: IssueView) => void
  /** Shown once, quietly, when extra suggestions were asked for and didn't arrive. */
  note?: string | null
}

export function IssueList({
  datasetId,
  issues,
  busyWith,
  errorFor,
  onAccept,
  onReject,
  note,
}: IssueListProps) {
  if (issues.length === 0) {
    return (
      <EmptyState title="Nothing needs fixing — this file is already tidy.">
        <p className="muted small">
          We looked for blanks, repeated rows, mixed spellings, and numbers or dates stored as text.
        </p>
      </EmptyState>
    )
  }

  return (
    <>
      {note && (
        <p className="muted small" role="status">
          {note}
        </p>
      )}
      {TIER_ORDER.map((tier) => {
        const forTier = issues.filter((issue) => issue.tier === tier)
        if (forTier.length === 0) return null
        return (
          <section key={tier} className="group" aria-labelledby={`group-${tier}`}>
            <h3 id={`group-${tier}`} className="group__title">
              {TIERS[tier].title}
              <span className={`group__count${tier === 'ask' ? ' group__count--ask' : ''}`}>
                {forTier.length}
              </span>
            </h3>
            <p className="muted small">{TIERS[tier].blurb}</p>
            {forTier.map((issue) => (
              <IssueCard
                key={issue.id}
                datasetId={datasetId}
                issue={issue}
                busy={busyWith(issue.id)}
                error={errorFor(issue.id)}
                onAccept={(choiceId) => onAccept(issue, choiceId)}
                onReject={() => onReject(issue)}
              />
            ))}
          </section>
        )
      })}
    </>
  )
}
