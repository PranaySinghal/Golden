"""The recipe panel: what's in it, turning a step off, removing one, undo."""

from fastapi import APIRouter
from pydantic import BaseModel

from app import review
from app.api.deps import StoreDep
from app.api.views import RecipeResponse, recipe_response

router = APIRouter(prefix="/api/datasets", tags=["recipe"])


class StepUpdate(BaseModel):
    enabled: bool


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


@router.post("/{dataset_id}/recipe/undo", response_model=RecipeResponse, operation_id="undoRecipe")
def undo_recipe(dataset_id: str, store: StoreDep) -> RecipeResponse:
    session = store.get(dataset_id)
    with session.lock:
        review.undo(session)
        return recipe_response(session)
