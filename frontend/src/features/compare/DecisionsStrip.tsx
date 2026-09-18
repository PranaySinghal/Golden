import type { IssueView } from '../../api/client'

interface DecisionsStripProps {
  issues: IssueView[]
  busy: string | null
  onChoose: (issueId: string, choiceId: string) => void
}

/** The questions already answered, so a different answer can be tried from here. */
export function DecisionsStrip({ issues, busy, onChoose }: DecisionsStripProps) {
  const answered = issues.filter((issue) => issue.ask && issue.state === 'applied')
  if (answered.length === 0) return null

  return (
    <section className="decisions" aria-labelledby="decisions-title">
      <h3 id="decisions-title" className="decisions__title">
        Your decisions
      </h3>
      <ul className="decisions__list">
        {answered.map((issue) => (
          <li key={issue.id} className="decisions__item">
            <span className="decisions__prompt">{issue.ask?.prompt}</span>
            <span className="decisions__choices" role="group" aria-label={issue.ask?.prompt}>
              {issue.ask?.choices.map((choice) => {
                const chosen = choice.id === issue.chosen_choice_id
                return (
                  <button
                    key={choice.id}
                    type="button"
                    className={`decisions__choice${chosen ? ' decisions__choice--on' : ''}`}
                    aria-pressed={chosen}
                    disabled={busy === issue.id || chosen}
                    onClick={() => onChoose(issue.id, choice.id)}
                  >
                    {choice.label}
                  </button>
                )
              })}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
