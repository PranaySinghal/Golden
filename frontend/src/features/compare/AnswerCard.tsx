import { useState } from 'react'

import type { AnswerCardView, StepView } from '../../api/client'
import { PreviewTable } from '../review/PreviewTable'
import { BeforeAfterChart } from './BeforeAfterChart'
import { changeDirection, describeChange, formatAnswer, togetherNote, whyLead } from './format'

interface AnswerCardProps {
  datasetId: string
  card: AnswerCardView
  steps: StepView[]
  updating: boolean
  onHighlight: (stepIds: string[]) => void
}

export function AnswerCard({
  datasetId,
  card,
  steps,
  updating,
  onHighlight,
}: AnswerCardProps) {
  const [openStep, setOpenStep] = useState<string | null>(null)
  const [showWhy, setShowWhy] = useState(false)
  const change = describeChange(card)
  const named = (card.why.step_ids ?? [])
    .map((id) => steps.find((step) => step.id === id))
    .filter((step): step is StepView => step !== undefined)

  return (
    <article className="answer" aria-busy={updating}>
      <h4 className="answer__question">{card.label}</h4>

      {card.kind === 'headline' ? (
        <p className="answer__values">
          {card.before.answerable ? (
            <span className="answer__before">{formatAnswer(card.before.value, card.measure)}</span>
          ) : (
            <span className="answer__before answer__before--none">Couldn’t be answered</span>
          )}
          <span aria-hidden="true" className="answer__arrow">
            →
          </span>
          <span className="answer__after">{formatAnswer(card.after.value, card.measure)}</span>
        </p>
      ) : (
        <BeforeAfterChart card={card} />
      )}

      {change && <p className={`answer__change answer__change--${changeDirection(card)}`}>{change}</p>}
      {card.unlocked && (
        <p className="muted small">
          {card.before.note ?? 'The file couldn’t answer this before it was cleaned.'}
        </p>
      )}
      {updating && (
        <p className="muted small" role="status">
          Working this out again…
        </p>
      )}

      {named.length > 0 && (
        <div className="answer__why">
          <button
            type="button"
            className="link-button"
            aria-expanded={showWhy}
            onClick={() => {
              setShowWhy(!showWhy)
              onHighlight(showWhy ? [] : named.map((step) => step.id))
            }}
          >
            {showWhy ? 'Hide why' : 'Why?'}
          </button>
          {showWhy && (
            <div className="answer__reasons">
              <p className="small">{whyLead(card)}:</p>
              <ul className="answer__steps">
                {named.map((step) => (
                  <li key={step.id}>
                    <button
                      type="button"
                      className="link-button"
                      onMouseEnter={() => onHighlight([step.id])}
                      onFocus={() => onHighlight([step.id])}
                      onClick={() => setOpenStep(openStep === step.id ? null : step.id)}
                    >
                      {step.description}
                    </button>
                    {openStep === step.id && (
                      <PreviewTable datasetId={datasetId} query={{ stepId: step.id }} />
                    )}
                  </li>
                ))}
              </ul>
              {togetherNote(card) && <p className="muted small">{togetherNote(card)}</p>}
            </div>
          )}
        </div>
      )}
    </article>
  )
}
