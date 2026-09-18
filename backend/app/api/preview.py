"""A few rows as they are now and as a suggestion would leave them."""

from typing import Annotated

from fastapi import APIRouter, Query

from app import review
from app.api.deps import StoreDep
from app.detectors.models import Issue, Tier
from app.errors import AppError
from app.preview import DEFAULT_ROWS, Preview, preview
from app.steps.models import Step
from app.store import DatasetSession

router = APIRouter(prefix="/api/datasets", tags=["preview"])

MAX_ROWS = 20


class PreviewTargetError(AppError):
    code = "preview_target_required"
    http_status = 422

    def __init__(self) -> None:
        super().__init__("There's nothing to preview here.")


@router.get("/{dataset_id}/preview", response_model=Preview, operation_id="getPreview")
def get_preview(
    dataset_id: str,
    store: StoreDep,
    issue_id: Annotated[str | None, Query()] = None,
    choice_id: Annotated[str | None, Query()] = None,
    step_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = DEFAULT_ROWS,
) -> Preview:
    session = store.get(dataset_id)
    with session.lock:
        if step_id is not None:
            steps = [step for step in session.recipe.steps if step.id == step_id]
        elif issue_id is not None:
            steps = _issue_steps(session, issue_id, choice_id)
        else:
            raise PreviewTargetError
        if not steps:
            return Preview(columns=[], note="This suggestion doesn't change any values.")
        step_ids = {step.id for step in steps}
        return preview(
            session.conn,
            session.base_schema,
            review.recipe_without(session, step_ids),
            review.recipe_with(session, steps),
            step_ids,
            limit,
        )


def _issue_steps(session: DatasetSession, issue_id: str, choice_id: str | None) -> list[Step]:
    """The steps a card would add: its own, or the answer being considered."""
    issue = review.find_issue(session, issue_id)
    if issue.tier is not Tier.ASK:
        return list(issue.steps)
    return list(_chosen(session, issue, choice_id))


def _chosen(session: DatasetSession, issue: Issue, choice_id: str | None) -> list[Step]:
    assert issue.ask is not None
    wanted = choice_id or session.answers.get(issue.id)
    for choice in issue.ask.choices:
        if choice.id == wanted or (wanted is None and choice.recommended):
            return list(choice.steps)
    if choice_id is not None:
        raise review.ChoiceNotFoundError(choice_id)
    return []
