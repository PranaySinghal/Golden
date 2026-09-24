import type { IssueView } from '../../api/client'

const SHOWN = 3

interface MainProblemsProps {
  /** Already ranked by the server, most answer-changing first. */
  issues: IssueView[]
  onShow: (issue: IssueView) => void
}

/** The few problems that matter most, each a way straight to its card. */
export function MainProblems({ issues, onShow }: MainProblemsProps) {
  const top = issues.slice(0, SHOWN)
  if (top.length === 0) return null

  return (
    <div className="main-problems">
      <p className="main-problems__label small">Main problems</p>
      <ul className="main-problems__list">
        {top.map((issue) => (
          <li key={issue.id}>
            <button type="button" className="link-button" onClick={() => onShow(issue)}>
              {issue.title}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
