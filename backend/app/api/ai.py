"""What a model added to the review, if one was asked at all."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import review
from app.ai.wording import RewordedCopy
from app.api.deps import ProviderDep, SettingsDep, StoreDep
from app.api.views import IssueView, issue_view
from app.story import Story

router = APIRouter(prefix="/api/datasets", tags=["ai"])


class AiResponse(BaseModel):
    # "off" means no model service is configured, which is a complete state:
    # the app works entirely without one.
    status: Literal["off", "ready", "failed"]
    added: list[IssueView] = Field(default_factory=list)
    issue_copy: dict[str, RewordedCopy] = Field(default_factory=dict)
    question_labels: dict[str, str] = Field(default_factory=dict)
    story: Story | None = None
    # Only set when a service was asked and couldn't answer.
    note: str | None = None


@router.get("/{dataset_id}/ai", response_model=AiResponse, operation_id="getAiSuggestions")
def get_ai_suggestions(
    dataset_id: str, store: StoreDep, settings: SettingsDep, provider: ProviderDep
) -> AiResponse:
    session = store.get(dataset_id)
    with session.lock:
        result = review.ai_enhancement(session, settings, provider)
        return AiResponse(
            status=result.status,
            added=[issue_view(session, issue) for issue in result.added],
            issue_copy=result.issue_copy,
            question_labels=result.question_labels,
            story=result.story,
            note=result.note,
        )
