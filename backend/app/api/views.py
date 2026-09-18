"""Response models for the review screen, built from a session. No business logic."""

from typing import Literal

from pydantic import BaseModel, Field

from app import review
from app.detectors.models import AskQuestion, DetectorName, Issue, Tier
from app.steps.apply import (
    OutputColumn,
    StepOutcome,
    StepStatus,
    answer_key,
    apply_recipe,
    plan_recipe,
)
from app.steps.copy import columns_of, describe
from app.steps.models import STEP_LABELS
from app.store import DatasetSession

IssueStateName = Literal["applied", "available", "rejected"]


class StepView(BaseModel):
    id: str
    type: str
    label: str
    description: str
    columns: list[str]
    enabled: bool
    status: StepStatus
    reason: str | None = None
    rows_set_aside: int = 0
    cells_changed: int | None = None
    issue_id: str | None = None


class RecipeResponse(BaseModel):
    steps: list[StepView] = Field(default_factory=list)
    # What the cleaned rows look like. Two recipes that make the same rows share
    # this, so the screen knows when an answer can't have changed.
    recipe_key: str = ""
    can_undo: bool = False
    row_count: int = 0
    set_aside_count: int = 0
    columns: list[OutputColumn] = Field(default_factory=list)


class IssueView(BaseModel):
    id: str
    detector: DetectorName
    # "ai" cards carry a chip saying so, and are never applied automatically.
    source: Literal["rules", "ai"] = "rules"
    columns: list[str]
    title: str
    explanation: str
    examples: list[str] = Field(default_factory=list)
    affected_rows: int
    tier: Tier
    impact: float
    ask: AskQuestion | None = None
    state: IssueStateName
    chosen_choice_id: str | None = None
    step_ids: list[str] = Field(default_factory=list)


class IssueListResponse(BaseModel):
    issues: list[IssueView] = Field(default_factory=list)
    counts: dict[Tier, int] = Field(default_factory=dict)
    needs_decision: int = 0
    recipe: RecipeResponse


def recipe_response(session: DatasetSession) -> RecipeResponse:
    """Apply the recipe and describe what each step did, for the recipe panel."""
    result = apply_recipe(
        session.conn, session.recipe, session.base_schema, previous=session.applied
    )
    session.applied = result
    outcomes = {outcome.step_id: outcome for outcome in result.outcomes}
    return RecipeResponse(
        steps=[_step_view(session, step.id, outcomes) for step in session.recipe.steps],
        recipe_key=answer_key(plan_recipe(session.recipe, session.base_schema), session.recipe),
        can_undo=bool(session.history.past),
        row_count=result.row_count,
        set_aside_count=result.set_aside_count,
        columns=result.columns,
    )


def issue_list_response(session: DatasetSession) -> IssueListResponse:
    issues = review.ranked(session)
    views = [issue_view(session, issue) for issue in issues]
    counts = {tier: sum(1 for issue in issues if issue.tier is tier) for tier in Tier}
    return IssueListResponse(
        issues=views,
        counts=counts,
        needs_decision=sum(
            1 for view in views if view.tier is Tier.ASK and view.state == "available"
        ),
        recipe=recipe_response(session),
    )


def issue_view(session: DatasetSession, issue: Issue) -> IssueView:
    state = review.state_of(session, issue)
    return IssueView(
        id=issue.id,
        detector=issue.detector,
        source=issue.source,
        columns=issue.columns,
        title=issue.title,
        explanation=issue.explanation,
        examples=issue.examples,
        affected_rows=issue.affected_rows,
        tier=issue.tier,
        impact=issue.impact,
        ask=issue.ask,
        state=_state_name(state.state),
        chosen_choice_id=state.chosen_choice_id,
        step_ids=state.step_ids,
    )


def _state_name(state: str) -> IssueStateName:
    assert state in ("applied", "available", "rejected")
    return state  # type: ignore[return-value]


def _step_view(session: DatasetSession, step_id: str, outcomes: dict[str, StepOutcome]) -> StepView:
    step = next(step for step in session.recipe.steps if step.id == step_id)
    outcome = outcomes[step_id]
    return StepView(
        id=step.id,
        type=step.type,
        label=STEP_LABELS[step.type],
        description=describe(step),
        columns=columns_of(step),
        enabled=step.enabled,
        status=outcome.status,
        reason=outcome.reason,
        rows_set_aside=outcome.rows_set_aside,
        cells_changed=outcome.cells_changed,
        issue_id=session.step_origin.get(step.id),
    )
