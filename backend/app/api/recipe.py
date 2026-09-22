"""The recipe panel: what's in it, turning a step off, removing one, undo, replay."""

from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

from app import review
from app.api.deps import StoreDep
from app.api.limits import read_within_limit
from app.api.views import RecipeOutcomeView, RecipeResponse, recipe_outcome_view, recipe_response
from app.config import MAX_RECIPE_BYTES
from app.errors import FileTooLargeError
from app.saved_recipe import RecipeOutcome, apply_saved_recipe

router = APIRouter(prefix="/api/datasets", tags=["recipe"])


class StepUpdate(BaseModel):
    enabled: bool


class RecipeReplayResponse(BaseModel):
    outcome: RecipeOutcomeView
    # Always the recipe as it now stands — unchanged when the steps were
    # refused — so the panel updates from this the way it does from any action.
    recipe: RecipeResponse


@router.get("/{dataset_id}/recipe", response_model=RecipeResponse, operation_id="getRecipe")
def get_recipe(dataset_id: str, store: StoreDep) -> RecipeResponse:
    session = store.get(dataset_id)
    with session.lock:
        # The recipe always includes the fixes that are certain, even if the page
        # asks for it before it asks what was found.
        review.prepare(session)
        return recipe_response(session)


@router.patch(
    "/{dataset_id}/recipe/steps/{step_id}",
    response_model=RecipeResponse,
    operation_id="updateStep",
)
def update_step(dataset_id: str, step_id: str, body: StepUpdate, store: StoreDep) -> RecipeResponse:
    session = store.get(dataset_id)
    with session.lock:
        review.set_step_enabled(session, step_id, body.enabled)
        return recipe_response(session)


@router.delete(
    "/{dataset_id}/recipe/steps/{step_id}",
    response_model=RecipeResponse,
    operation_id="removeStep",
)
def remove_step(dataset_id: str, step_id: str, store: StoreDep) -> RecipeResponse:
    session = store.get(dataset_id)
    with session.lock:
        review.remove_step(session, step_id)
        return recipe_response(session)


@router.post(
    "/{dataset_id}/recipe/replay",
    response_model=RecipeReplayResponse,
    operation_id="replayRecipe",
)
def replay_recipe_file(
    dataset_id: str,
    store: StoreDep,
    recipe: Annotated[UploadFile, File(description="Steps saved from an earlier file.")],
) -> RecipeReplayResponse:
    """Re-use steps saved from another file, replacing whatever is in the panel.

    Steps that can't be read or don't fit this file are reported rather than
    raised: the answer to "can I re-use these?" is no and here's why, which is a
    result the reader needs, not a failed request.
    """
    session = store.get(dataset_id)
    with session.lock:
        try:
            data = read_within_limit(recipe.file, MAX_RECIPE_BYTES)
        except FileTooLargeError as error:
            outcome = RecipeOutcome(applied=False, problems=[error.message])
        else:
            outcome = apply_saved_recipe(session, data)
        return RecipeReplayResponse(
            outcome=recipe_outcome_view(outcome), recipe=recipe_response(session)
        )


@router.post("/{dataset_id}/recipe/undo", response_model=RecipeResponse, operation_id="undoRecipe")
def undo_recipe(dataset_id: str, store: StoreDep) -> RecipeResponse:
    session = store.get(dataset_id)
    with session.lock:
        review.undo(session)
        return recipe_response(session)
