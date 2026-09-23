"""Score each issue by how much fixing it changes the answers.

For each issue, compare two recipes over the raw data: one with only the issues
it depends on (like reading a column as numbers), and one that also applies
this issue's fix. For ask-tier issues every choice is tried, and the choice
that moves answers most sets the score. Answers are read straight from each
recipe's steps, so the user's cleaned table is never touched.

Cost: about (issues x choices x relevant questions) aggregate queries; questions
unrelated to an issue's columns are skipped unless the fix removes rows.
"""

import duckdb

from app.compare.after import AfterReading
from app.compare.compare import AnswerCache, compare
from app.compare.retired import still_asked
from app.detectors.models import Issue, Tier
from app.detectors.registry import rank_issues
from app.detectors.step_order import recipe_for
from app.profile.models import DatasetProfile
from app.questions.models import Question
from app.steps.apply import fingerprint, plan_recipe
from app.steps.schema import base_schema

ROW_REMOVING_STEPS = {"dedupe", "set_aside_rows"}
# Issues that move no answer still sort by how many rows they touch, below any
# issue that does move one.
ROWS_ONLY_WEIGHT = 0.01


def _touches(question: Question, issue: Issue) -> bool:
    steps = list(issue.steps)
    if issue.ask is not None:
        steps += [s for choice in issue.ask.choices for s in choice.steps]
    if any(step.type in ROW_REMOVING_STEPS for step in steps) or not issue.columns:
        return True
    return bool(question.columns & set(issue.columns))


def score_issues(
    conn: duckdb.DuckDBPyConnection,
    profile: DatasetProfile,
    issues: list[Issue],
    questions: list[Question],
    cache: AnswerCache | None = None,
) -> list[Issue]:
    base = base_schema(profile)
    cache = {} if cache is None else cache
    order = {q.id: index for index, q in enumerate(questions)}
    scored = []
    for issue in issues:
        relevant = [q for q in questions if _touches(q, issue)]
        baseline_recipe = recipe_for(issues, accepted=set(issue.requires))
        baseline_plan = plan_recipe(baseline_recipe, base)
        baseline_key = fingerprint(baseline_plan, baseline_recipe)
        baseline = AfterReading.from_plan(baseline_plan)

        choices: list[str | None] = [None]
        if issue.tier is Tier.ASK and issue.ask is not None:
            choices = [choice.id for choice in issue.ask.choices]

        best = 0.0
        moved: set[str] = set()
        for choice in choices:
            answers = {issue.id: choice} if choice else {}
            recipe = recipe_for(issues, accepted={issue.id}, answers=answers)
            plan = plan_recipe(recipe, base)
            key = fingerprint(plan, recipe)
            if key == baseline_key:
                continue  # e.g. "Keep them": nothing to compare
            diffs = compare(
                conn,
                still_asked(relevant, plan),
                baseline,
                AfterReading.from_plan(plan),
                key,
                cache,
                before_key=baseline_key,
            )
            for diff in diffs:
                if diff.changed:
                    moved.add(diff.question.id)
                best = max(best, diff.impact)

        share = issue.affected_rows / profile.row_count if profile.row_count else 0.0
        impact = best if best > 0 else ROWS_ONLY_WEIGHT * share
        scored.append(
            issue.model_copy(
                update={
                    "impact": round(min(1.0, impact), 6),
                    "moves_answers": sorted(moved, key=lambda q: order.get(q, 0)),
                }
            )
        )
    return rank_issues(scored, profile)
