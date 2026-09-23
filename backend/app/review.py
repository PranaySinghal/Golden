"""Reviewing a file: what was found, what's in the recipe, and acting on a card.

The recipe is the single source of truth. An issue is "applied" when the recipe
already does its work and "rejected" when the user said no to it; nothing else
is stored, so the two can't drift apart.

"Already does its work" is a question about the work, not about step objects
(`steps/identity.py`): a recipe replayed from another file carries steps that
mean the same thing under different ids, and sometimes different things under
the same id. Matching on what a step does is what lets a replayed recipe and a
freshly detected issue recognise each other.

Issues and their impact are worked out once per dataset (up to a couple of
seconds on a messy file) and kept on the session until the file is read again.
"""

from dataclasses import dataclass

from app.ai.enhance import Enhancement, enhance, tell_story
from app.ai.provider import Provider
from app.compare.engine import ComparisonEngine
from app.compare.issue_impact import score_issues
from app.compare.models import Comparison
from app.config import Settings
from app.detectors.models import Issue, Tier
from app.detectors.registry import detect_issues, rank_issues
from app.detectors.step_order import RANK, chosen_steps
from app.errors import AppError
from app.questions.generate import generate_questions
from app.steps import recipe_ops
from app.steps.identity import matched_ids, work_key
from app.steps.models import Recipe, Step
from app.steps.recipe_ops import RecipeHistory
from app.store import DatasetSession
from app.story import Story


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
    _claim_existing_steps(session)
    if not session.safe_applied:
        session.safe_applied = True
        for issue in session.issues:
            if issue.tier is Tier.SAFE:
                _add_steps(session, issue, list(issue.steps))
        # Applying what's certain isn't a user edit, so there's nothing to undo to.
        session.history = RecipeHistory()
    return session.issues


def _claim_existing_steps(session: DatasetSession) -> None:
    """Point steps the recipe already holds at the cards that explain them.

    A replayed recipe arrives before anything has been detected, so its steps
    start with no card behind them: the panel would show them with nothing to
    click through to, and an answered question would look unanswered. Detection
    has just run, so now we can say which card each one belongs to.
    """
    for issue in session.issues or []:
        state = state_of(session, issue)
        for step_id in state.step_ids:
            session.step_origin.setdefault(step_id, issue.id)
        if state.state == "applied" and state.chosen_choice_id is not None:
            session.answers.setdefault(issue.id, state.chosen_choice_id)


def issues_of(session: DatasetSession) -> list[Issue]:
    return prepare(session)


def ai_enhancement(
    session: DatasetSession, settings: Settings, provider: Provider | None = None
) -> Enhancement:
    """Ask a model for more, once per file, and keep what survived checking.

    The extra issues join the session's list, so accepting, previewing and
    undoing them all work through the paths that already exist.

    The story is the exception to "once": it describes the answers rather than
    the file, so it's asked again whenever they move, and carried on the result
    so the screen still gets everything from one place.
    """
    if session.enhancement is None:
        issues = prepare(session)
        result = enhance(
            session.conn, session.profile, issues, session.questions or [], settings, provider
        )
        session.enhancement = result
        if result.added:
            known = {issue.id for issue in issues}
            session.issues = [*issues, *(i for i in result.added if i.id not in known)]
    return session.enhancement.model_copy(update={"story": ai_story(session, settings, provider)})


def ai_story(
    session: DatasetSession, settings: Settings, provider: Provider | None = None
) -> Story | None:
    """A model's story for the rows as they stand now, asked once per recipe."""
    if not settings.llm_enabled:
        return None
    comparison = compare_now(session)
    if comparison.recipe_key not in session.stories:
        session.stories[comparison.recipe_key] = tell_story(
            comparison.diffs, comparison.recipe_key, settings, provider
        )
    return session.stories[comparison.recipe_key]


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
    if issue.tier is Tier.ASK:
        assert issue.ask is not None
        # The answer on record wins. Without this, a choice whose steps are a
        # subset of another's could match first and show the wrong one picked.
        answered = session.answers.get(issue.id)
        ordered = sorted(issue.ask.choices, key=lambda choice: choice.id != answered)
        for choice in ordered:
            ids = matched_ids(session.recipe, choice.steps)
            if ids:
                return IssueState("applied", choice.id, ids)
            # A choice that means "leave it alone" carries no steps, so the only
            # record that it was answered is the answer itself.
            if ids == [] and answered == choice.id:
                return IssueState("applied", choice.id, [])
    else:
        ids = matched_ids(session.recipe, issue.steps)
        if ids:
            return IssueState("applied", None, ids)
    if issue.id in session.rejected:
        return IssueState("rejected", None, [])
    return IssueState("available", None, [])


def recipe_ids_for(session: DatasetSession, issue: Issue) -> list[str]:
    """Every recipe step belonging to this issue.

    Steps doing work the issue proposes, plus any carrying one of its own ids: a
    replayed recipe can hold an older version of a step under the same id, and
    that step is still this issue's to replace.
    """
    found: list[str] = []
    for steps in _proposals(issue):
        found.extend(matched_ids(session.recipe, steps) or [])
    own = set(_all_step_ids(issue))
    found.extend(step.id for step in session.recipe.steps if step.id in own)
    return list(dict.fromkeys(found))


def _proposals(issue: Issue) -> list[list[Step]]:
    """Each set of steps this issue could put in the recipe."""
    if issue.ask is None:
        return [list(issue.steps)]
    return [list(issue.steps), *(list(choice.steps) for choice in issue.ask.choices)]


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


def matching_step_ids(session: DatasetSession, steps: list[Step]) -> set[str]:
    """Recipe steps already doing the work of `steps`, whatever ids they carry."""
    return set(matched_ids(session.recipe, steps) or [])


def recipe_without(session: DatasetSession, step_ids: set[str]) -> Recipe:
    return Recipe(steps=[step for step in session.recipe.steps if step.id not in step_ids])


def recipe_with(session: DatasetSession, steps: list[Step]) -> Recipe:
    recipe = session.recipe
    for step in steps:
        if _existing_step_id(recipe, step) is not None:
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
    """Put an issue's steps in the recipe, leaving alone what's already there.

    A replayed recipe can already hold the same work (under any id) or the same
    id (holding different work — a step whose parameters changed since it was
    saved). In both cases the recipe wins: it is what the user asked to re-use,
    and adding a near-identical step beside it would change what runs without
    anyone choosing that.
    """
    for step in steps:
        existing = _existing_step_id(session.recipe, step)
        if existing is not None:
            session.step_origin.setdefault(existing, issue.id)
            continue
        position = _position_for(session.recipe, step)
        edit = recipe_ops.add_step(
            session.recipe, session.history, step, session.base_schema, position
        )
        session.recipe, session.history = edit.recipe, edit.history
        session.step_origin[step.id] = issue.id


def _existing_step_id(recipe: Recipe, step: Step) -> str | None:
    """The recipe's step doing this work, or holding this id, if there is one."""
    wanted = work_key(step)
    for existing in recipe.steps:
        if existing.id == step.id or work_key(existing) == wanted:
            return existing.id
    return None


def _remove_steps(session: DatasetSession, issue: Issue) -> None:
    """Take this issue's steps back out, leaving another issue's work alone."""
    for step_id in recipe_ids_for(session, issue):
        owner = session.step_origin.get(step_id)
        if owner is not None and owner != issue.id:
            continue
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
