import type { RecipeOutcome as Outcome } from '../../api/client'
import { REUSE_REFUSED, reusedSteps } from './copy'

interface RecipeOutcomeProps {
  outcome: Outcome
}

/** What came of steps saved from another file, whether they ran or not. */
export function RecipeOutcome({ outcome }: RecipeOutcomeProps) {
  if (!outcome.applied) {
    return (
      <div className="alert" role="alert">
        <p>{REUSE_REFUSED}</p>
        <ul>
          {outcome.problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      </div>
    )
  }
  return (
    <div className="notice" role="status">
      <p>{reusedSteps(outcome.steps_applied, outcome.source_filename)}</p>
      {outcome.warnings.length > 0 && (
        <ul>
          {outcome.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
