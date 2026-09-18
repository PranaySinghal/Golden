"""Reviewing a file: what was found, what's in the recipe, and acting on a card.

The recipe is the single source of truth. An issue is "applied" when its steps
are in the recipe and "rejected" when the user said no to it; nothing else is
stored, so the two can't drift apart.

Issues and their impact are worked out once per dataset (up to a couple of
seconds on a messy file) and kept on the session until the file is read again.
"""

from dataclasses import dataclass

from app.compare.engine import ComparisonEngine
from app.compare.issue_impact import score_issues
from app.compare.models import Comparison
from app.detectors.models import Issue, Tier
from app.detectors.registry import detect_issues, rank_issues
from app.detectors.step_order import RANK, chosen_steps
from app.errors import AppError
from app.questions.generate import generate_questions
from app.steps import recipe_ops
from app.steps.models import Recipe, Step
from app.steps.recipe_ops import RecipeHistory
from app.store import DatasetSession


class IssueNotFoundError(AppError):
    code = "issue_not_found"
    http_status = 404

    def __init__(self, issue_id: str) -> None:
        self.issue_id = issue_id
        super().__init__("We couldn't find that suggestion. Try reloading the page.")


class ChoiceNotFoundError(AppError):
    code = "choice_not_found"
    http_status = 422

    def __init__(self, choice_id: str) -> None:
        self.choice_id = choice_id
        super().__init__("That answer isn't one of the options. Try reloading the page.")


class ChoiceRequiredError(AppError):
    code = "choice_required"
    http_status = 422

    def __init__(self) -> None:
        super().__init__("Please pick one of the answers first.")


@dataclass(frozen=True)
class IssueState:
    state: str  # "applied" | "available" | "rejected"
    chosen_choice_id: str | None
    step_ids: list[str]


def prepare(session: DatasetSession) -> list[Issue]:
    """Find the issues, score them, and apply the safe ones. Done once per file."""
    if session.issues is None:
        issues = detect_issues(session.conn, session.profile)
        session.questions = generate_questions(session.conn, session.profile)
        session.issues = score_issues(
            session.conn, session.profile, issues, session.questions, session.answer_cache
        )
    if not session.safe_applied:
        session.safe_applied = True
        for issue in session.issues:
            if issue.tier is Tier.SAFE:
                _add_steps(session, issue, list(issue.steps))
        # Applying what's certain isn't a user edit, so there's nothing to undo to.
        session.history = RecipeHistory()
    return session.issues


def issues_of(session: DatasetSession) -> list[Issue]:
    return prepare(session)


def compare_now(session: DatasetSession) -> Comparison:
    """Answer every question before and after, reusing whatever the last pass found.

    The engine lives as long as the file does, so its answers are still there
    when a user changes their mind; `recompute` then only re-asks the questions
    the changed steps can reach.
    """
    prepare(session)
    if session.engine is None:
        session.engine = ComparisonEngine(
            session.conn, session.profile, questions=session.questions
        )
    previous = session.comparison
    if previous is None:
        session.comparison = session.engine.compare(session.recipe)
    else:
        session.comparison = session.engine.recompute(previous, session.recipe)
    return session.comparison


def find_issue(session: DatasetSession, issue_id: str) -> Issue:
    for issue in issues_of(session):
        if issue.id == issue_id:
            return issue
    raise IssueNotFoundError(issue_id)


def state_of(session: DatasetSession, issue: Issue) -> IssueState:
    in_recipe = {step.id for step in session.recipe.steps}
    if issue.tier is Tier.ASK:
        assert issue.ask is not None
        for choice in issue.ask.choices:
            ids = [step.id for step in choice.steps]
            if ids and in_recipe.issuperset(ids):
                return IssueState("applied", choice.id, ids)
            # A choice that means "leave it alone" carries no steps, so the only
            # record that it was answered is the answer itself.
            if not ids and session.answers.get(issue.id) == choice.id:
                return IssueState("applied", choice.id, [])
    else:
        ids = [step.id for step in issue.steps]
        if ids and in_recipe.issuperset(ids):
            return IssueState("applied", None, ids)
    if issue.id in session.rejected:
        return IssueState("rejected", None, [])
    return IssueState("available", None, [])


def accept(session: DatasetSession, issue_id: str, choice_id: str | None = None) -> None:
    """Put an issue's fix in the recipe, replacing an earlier answer to it."""
    issue = find_issue(session, issue_id)
    steps = _steps_for(issue, choice_id)
    _remove_steps(session, issue)
    session.rejected.discard(issue_id)
    if issue.tier is Tier.ASK and choice_id is not None:
        session.answers[issue_id] = choice_id
    _add_steps(session, issue, steps)


def reject(session: DatasetSession, issue_id: str) -> None:
    """Take an issue's fix back out and stop suggesting it."""
    issue = find_issue(session, issue_id)
    _remove_steps(session, issue)
    session.answers.pop(issue_id, None)
    session.rejected.add(issue_id)


def undo(session: DatasetSession) -> bool:
    result = recipe_ops.undo(session.recipe, session.history)
    session.recipe, session.history = result.recipe, result.history
    return result.undone


def set_step_enabled(session: DatasetSession, step_id: str, enabled: bool) -> None:
    edit = recipe_ops.set_enabled(
        session.recipe, session.history, step_id, enabled, session.base_schema
    )
    session.recipe, session.history = edit.recipe, edit.history


def remove_step(session: DatasetSession, step_id: str) -> None:
    edit = recipe_ops.remove_step(session.recipe, session.history, step_id)
    session.recipe, session.history = edit.recipe, edit.history


def recipe_without(session: DatasetSession, step_ids: set[str]) -> Recipe:
    return Recipe(steps=[step for step in session.recipe.steps if step.id not in step_ids])


def recipe_with(session: DatasetSession, steps: list[Step]) -> Recipe:
    recipe = session.recipe
    for step in steps:
        if any(existing.id == step.id for existing in recipe.steps):
            continue
        recipe = Recipe(steps=_placed(list(recipe.steps), step))
    return recipe


def _steps_for(issue: Issue, choice_id: str | None) -> list[Step]:
    if issue.tier is not Tier.ASK:
        return list(issue.steps)
    assert issue.ask is not None
    if choice_id is None:
        raise ChoiceRequiredError
    if not any(choice.id == choice_id for choice in issue.ask.choices):
        raise ChoiceNotFoundError(choice_id)
    return chosen_steps(issue, {issue.id: choice_id})


def _add_steps(session: DatasetSession, issue: Issue, steps: list[Step]) -> None:
    for step in steps:
        position = _position_for(session.recipe, step)
        edit = recipe_ops.add_step(
            session.recipe, session.history, step, session.base_schema, position
        )
        session.recipe, session.history = edit.recipe, edit.history
        session.step_origin[step.id] = issue.id


def _remove_steps(session: DatasetSession, issue: Issue) -> None:
    for step_id in _all_step_ids(issue):
        if any(step.id == step_id for step in session.recipe.steps):
            remove_step(session, step_id)
        session.step_origin.pop(step_id, None)


def _all_step_ids(issue: Issue) -> list[str]:
    steps = list(issue.steps)
    if issue.ask is not None:
        steps += [step for choice in issue.ask.choices for step in choice.steps]
    return [step.id for step in steps]


def _position_for(recipe: Recipe, step: Step) -> int:
    """Keep the recipe in the order steps have to run in (see step_order.RANK)."""
    rank = RANK[step.type]
    for index, existing in enumerate(recipe.steps):
        if RANK[existing.type] > rank:
            return index
    return len(recipe.steps)


def _placed(steps: list[Step], step: Step) -> list[Step]:
    steps.insert(_position_for(Recipe(steps=steps), step), step)
    return steps


def ranked(session: DatasetSession) -> list[Issue]:
    return rank_issues(list(issues_of(session)), session.profile)
