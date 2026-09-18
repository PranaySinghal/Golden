import { useState } from 'react'

import type { IssueView } from '../../api/client'
import { PreviewTable } from './PreviewTable'
import { affected } from './copy'

interface IssueCardProps {
  datasetId: string
  issue: IssueView
  busy: boolean
  error: string | null
  onAccept: (choiceId?: string) => void
  onReject: () => void
}

export function IssueCard({
  datasetId,
  issue,
  busy,
  error,
  onAccept,
  onReject,
}: IssueCardProps) {
  const [open, setOpen] = useState(false)
  const [considering, setConsidering] = useState<string | null>(null)
  const applied = issue.state === 'applied'
  const rejected = issue.state === 'rejected'
  const choices = issue.ask?.choices ?? []
  const chosen = choices.find((choice) => choice.id === issue.chosen_choice_id)
  const previewChoice = considering ?? issue.chosen_choice_id ?? undefined

  return (
    <article className={`card${applied ? ' card--applied' : ''}`} aria-busy={busy}>
      <div className="card__head">
        <h4 className="card__title">{issue.title}</h4>
        {applied && <span className="chip chip--done">Done</span>}
        {rejected && <span className="chip">Not doing this</span>}
      </div>
      <p className="card__explanation">{issue.explanation}</p>
      {issue.examples.length > 0 && (
        <p className="muted small">
          For example: {issue.examples.slice(0, 3).map((value) => `“${value}”`).join(', ')}
        </p>
      )}
      {issue.affected_rows > 0 && <p className="muted small">{affected(issue.affected_rows)}</p>}

      {issue.ask && !applied && (
        <fieldset className="choices" disabled={busy}>
          <legend className="choices__prompt">{issue.ask.prompt}</legend>
          {choices.map((choice) => (
            <label key={choice.id} className="choices__option">
              <input
                type="radio"
                name={`choice-${issue.id}`}
                value={choice.id}
                checked={considering === choice.id}
                onChange={() => setConsidering(choice.id)}
              />
              <span>
                <span className="choices__label">
                  {choice.label}
                  {choice.recommended && <span className="chip chip--soft">Suggested</span>}
                </span>
                <span className="muted small">{choice.description}</span>
              </span>
            </label>
          ))}
        </fieldset>
      )}

      {issue.ask && applied && chosen && (
        <p className="card__answer">
          Your answer: <strong>{chosen.label}</strong>
        </p>
      )}

      {error && (
        <p className="card__error" role="alert">
          {error}
        </p>
      )}

      <div className="card__actions">
        {!applied && issue.ask && (
          <button
            type="button"
            className="button"
            disabled={busy || considering === null}
            onClick={() => onAccept(considering ?? undefined)}
          >
            {busy ? 'Applying…' : 'Use this answer'}
          </button>
        )}
        {!applied && !issue.ask && (
          <button type="button" className="button" disabled={busy} onClick={() => onAccept()}>
            {busy ? 'Applying…' : 'Accept'}
          </button>
        )}
        {applied && (
          <button
            type="button"
            className="button button--secondary"
            disabled={busy}
            onClick={onReject}
          >
            {issue.ask ? 'Change my answer' : 'Undo this'}
          </button>
        )}
        {!applied && !rejected && (
          <button type="button" className="link-button" disabled={busy} onClick={onReject}>
            Not this one
          </button>
        )}
        <button type="button" className="link-button" onClick={() => setOpen(!open)}>
          {open ? 'Hide examples' : 'Show me'}
        </button>
      </div>

      {open && (
        <PreviewTable
          datasetId={datasetId}
          query={{ issueId: issue.id, choiceId: previewChoice }}
        />
      )}
    </article>
  )
}
