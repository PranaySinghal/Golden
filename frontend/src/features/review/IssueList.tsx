import { useState } from 'react'

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
  /** A card that has to be on screen (a link elsewhere points at it), even if folded away. */
  reveal?: string | null
}

/** In one section, this many cards of the same kind are shown before the rest fold away. */
export const SAME_KIND_SHOWN = 3

interface Shown {
  issue: IssueView
  /** Set on the last visible card of a kind that has more folded behind it. */
  more?: { key: string; hidden: number }
}

/**
 * A wide file can raise the same kind of card for sixty columns. Within a
 * section, the first few of each kind stay in their ranked places and the rest
 * fold behind a "show more" on the last one, so one kind can't bury the others.
 */
function foldSameKind(tier: string, issues: IssueView[], open: Set<string>): Shown[] {
  const perKind = new Map<string, number>()
  for (const issue of issues) perKind.set(issue.detector, (perKind.get(issue.detector) ?? 0) + 1)
  const seen = new Map<string, number>()
  const shown: Shown[] = []
  for (const issue of issues) {
    const key = `${tier}:${issue.detector}`
    const position = (seen.get(issue.detector) ?? 0) + 1
    seen.set(issue.detector, position)
    const total = perKind.get(issue.detector) ?? 0
    if (open.has(key) || position < SAME_KIND_SHOWN || total <= SAME_KIND_SHOWN) {
      shown.push({ issue })
    } else if (position === SAME_KIND_SHOWN) {
      shown.push({ issue, more: { key, hidden: total - SAME_KIND_SHOWN } })
    }
  }
  return shown
}

export function IssueList({
  datasetId,
  issues,
  busyWith,
  errorFor,
  onAccept,
  onReject,
  note,
  reveal,
}: IssueListProps) {
  const [opened, setOpened] = useState<Set<string>>(new Set())
  // A card something else links to is shown along with the rest of its kind.
  const wanted = issues.find((issue) => issue.id === reveal)
  const open = wanted ? new Set([...opened, `${wanted.tier}:${wanted.detector}`]) : opened

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
            {foldSameKind(tier, forTier, open).map(({ issue, more }) => (
              <div key={issue.id}>
                <IssueCard
                  datasetId={datasetId}
                  issue={issue}
                  busy={busyWith(issue.id)}
                  error={errorFor(issue.id)}
                  onAccept={(choiceId) => onAccept(issue, choiceId)}
                  onReject={() => onReject(issue)}
                />
                {more && (
                  <button
                    type="button"
                    className="group__more link-button"
                    onClick={() => setOpened(new Set([...opened, more.key]))}
                  >
                    Show {more.hidden} more like {more.hidden === 1 ? 'this' : 'these'}
                  </button>
                )}
              </div>
            ))}
          </section>
        )
      })}
    </>
  )
}
