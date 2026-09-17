"""Editing a recipe. Every edit returns a new Recipe and remembers the old one for undo."""

from dataclasses import dataclass

from app.steps.apply import StepStatus, plan_recipe
from app.steps.errors import StepNotFoundError, StepValidationError
from app.steps.models import MAX_STEPS, Recipe, Step
from app.steps.schema import StageSchema

HISTORY_LIMIT = 100


@dataclass(frozen=True)
class RecipeHistory:
    """Earlier versions of the recipe, most recent last."""

    past: tuple[Recipe, ...] = ()

    def push(self, recipe: Recipe) -> "RecipeHistory":
        return RecipeHistory((*self.past, recipe)[-HISTORY_LIMIT:])


@dataclass(frozen=True)
class Edit:
    recipe: Recipe
    history: RecipeHistory


@dataclass(frozen=True)
class UndoResult:
    recipe: Recipe
    history: RecipeHistory
    undone: bool


def add_step(
    recipe: Recipe,
    history: RecipeHistory,
    step: Step,
    base: StageSchema,
    position: int | None = None,
) -> Edit:
    if any(existing.id == step.id for existing in recipe.steps):
        raise StepValidationError("That step is already in the recipe.", step.id)
    if len(recipe.steps) >= MAX_STEPS:
        raise StepValidationError(f"A recipe can have at most {MAX_STEPS} steps.", step.id)
    steps = list(recipe.steps)
    steps.insert(len(steps) if position is None else max(0, min(position, len(steps))), step)
    return _commit(recipe, history, Recipe(steps=steps), base, step)


def update_step(recipe: Recipe, history: RecipeHistory, step: Step, base: StageSchema) -> Edit:
    index = _index_of(recipe, step.id)
    steps = list(recipe.steps)
    steps[index] = step
    return _commit(recipe, history, Recipe(steps=steps), base, step)


def remove_step(recipe: Recipe, history: RecipeHistory, step_id: str) -> Edit:
    index = _index_of(recipe, step_id)
    steps = [step for position, step in enumerate(recipe.steps) if position != index]
    return Edit(Recipe(steps=steps), history.push(recipe))


def set_enabled(
    recipe: Recipe, history: RecipeHistory, step_id: str, enabled: bool, base: StageSchema
) -> Edit:
    index = _index_of(recipe, step_id)
    step = recipe.steps[index]
    if step.enabled == enabled:
        return Edit(recipe, history)
    updated = step.model_copy(update={"enabled": enabled})
    steps = list(recipe.steps)
    steps[index] = updated
    if not enabled:
        # Turning a step off never fails; steps that needed it show as blocked.
        return Edit(Recipe(steps=steps), history.push(recipe))
    return _commit(recipe, history, Recipe(steps=steps), base, updated)


def undo(recipe: Recipe, history: RecipeHistory) -> UndoResult:
    if not history.past:
        return UndoResult(recipe, history, undone=False)
    return UndoResult(history.past[-1], RecipeHistory(history.past[:-1]), undone=True)


def _index_of(recipe: Recipe, step_id: str) -> int:
    for index, step in enumerate(recipe.steps):
        if step.id == step_id:
            return index
    raise StepNotFoundError(step_id)


def _commit(
    before: Recipe, history: RecipeHistory, after: Recipe, base: StageSchema, step: Step
) -> Edit:
    """Accept the edit only if the step it touched can actually run."""
    if step.enabled:
        outcome = next(o for o in plan_recipe(after, base).outcomes if o.step_id == step.id)
        if outcome.status is StepStatus.BLOCKED:
            raise StepValidationError(outcome.reason or "This step can't run.", step.id)
    return Edit(after, history.push(before))
