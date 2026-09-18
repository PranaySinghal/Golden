"""What was found in a file, and acting on one card: accept, answer, or turn down."""

from fastapi import APIRouter
from pydantic import BaseModel

from app import review
from app.api.deps import StoreDep
from app.api.views import IssueListResponse, RecipeResponse, issue_list_response, recipe_response

router = APIRouter(prefix="/api/datasets", tags=["issues"])


class AcceptRequest(BaseModel):
    # Required for a question with choices; ignored otherwise.
    choice_id: str | None = None


@router.get("/{dataset_id}/issues", response_model=IssueListResponse, operation_id="getIssues")
def get_issues(dataset_id: str, store: StoreDep) -> IssueListResponse:
    session = store.get(dataset_id)
    with session.lock:
        return issue_list_response(session)


@router.post(
    "/{dataset_id}/issues/{issue_id}/accept",
    response_model=RecipeResponse,
    operation_id="acceptIssue",
)
def accept_issue(
    dataset_id: str, issue_id: str, body: AcceptRequest, store: StoreDep
) -> RecipeResponse:
    session = store.get(dataset_id)
    with session.lock:
        review.accept(session, issue_id, body.choice_id)
        return recipe_response(session)


@router.post(
    "/{dataset_id}/issues/{issue_id}/reject",
    response_model=RecipeResponse,
    operation_id="rejectIssue",
)
def reject_issue(dataset_id: str, issue_id: str, store: StoreDep) -> RecipeResponse:
    session = store.get(dataset_id)
    with session.lock:
        review.reject(session, issue_id)
        return recipe_response(session)
