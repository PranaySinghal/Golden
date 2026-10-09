"""Check whether a saved recipe fits a new file, and apply it if it does."""

import json

import duckdb
from pydantic import BaseModel, ValidationError

from app.profile.models import DatasetProfile, SemanticRole
from app.steps.apply import ApplyResult, StepStatus, apply_recipe, plan_recipe
from app.steps.errors import RecipeFileError, RecipeIncompatibleError
from app.steps.models import (
    STEP_LABELS,
    CastNumberStep,
    ParseDateStep,
    Recipe,
    RecipeFile,
    without_snapshots,
)
from app.steps.schema import StageSchema, base_schema

_DEPENDS_PREFIX = "It depends on an earlier step"


class Compatibility(BaseModel):
    compatible: bool
    problems: list[str]
    warnings: list[str]


def required_columns(recipe: Recipe, base: StageSchema) -> list[str]:
    """Columns from the uploaded file that the recipe's running steps read."""
    required: list[str] = []
    created: set[str] = set()
    for stage in plan_recipe(recipe, base).stages:
        for name in stage.compiled.reads:
            if name not in created and name not in required:
                required.append(name)
        created.update(stage.compiled.creates)
    return required


def check_compatibility(recipe_file: RecipeFile, profile: DatasetProfile) -> Compatibility:
    base = base_schema(profile)
    names = base.names()
    problems: list[str] = []
    warnings: list[str] = []

    missing = [name for name in recipe_file.requires_columns if name not in names]
    for name in missing:
        message = f'This recipe needs a column called "{name}", but this file doesn\'t have one.'
        similar = [candidate for candidate in names if _loose(candidate) == _loose(name)]
        if similar:
            message += f' It has "{similar[0]}", which might be the same column.'
        problems.append(message)

    recipe = recipe_file.recipe
    plan = plan_recipe(recipe, base)
    # How the recipe ran on the file it was saved from, to tell a step's own
    # problem apart from a knock-on effect of an earlier step failing here.
    original = plan_recipe(recipe, StageSchema.all_text(recipe_file.source.columns))
    ran_originally = {o.step_id for o in original.outcomes if o.status is StepStatus.APPLIED}
    earlier_failed = False
    for number, (step, outcome) in enumerate(zip(recipe.steps, plan.outcomes, strict=True), 1):
        if outcome.status is not StepStatus.BLOCKED:
            continue
        reason = outcome.reason or ""
        knock_on = earlier_failed and step.id in ran_originally
        earlier_failed = True
        if knock_on or any(f'"{name}"' in reason for name in missing):
            continue  # already explained by an earlier problem
        label = f'Step {number} ("{STEP_LABELS[step.type]}")'
        if reason.startswith(_DEPENDS_PREFIX):
            warnings.append(f"{label} will be skipped. {reason}")
        else:
            problems.append(f"{label} can't run on this file. {reason}")

    roles = {column.name: column.semantic_role for column in profile.columns}
    applied = {stage.compiled.step_id for stage in plan.stages}
    for step in recipe.steps:
        if step.id not in applied:
            continue
        if isinstance(step, CastNumberStep) and roles.get(step.column) not in (
            SemanticRole.MEASURE,
            None,
        ):
            warnings.append(
                f'"{step.column}" doesn\'t look mostly like numbers in this file, so many '
                "values may end up blank."
            )
        if isinstance(step, ParseDateStep) and roles.get(step.column) not in (
            SemanticRole.DATE,
            None,
        ):
            warnings.append(
                f'"{step.column}" doesn\'t look mostly like dates in this file, so many '
                "values may end up blank."
            )

    return Compatibility(compatible=not problems, problems=problems, warnings=warnings)


def replay_recipe(
    conn: duckdb.DuckDBPyConnection,
    recipe_file: RecipeFile,
    profile: DatasetProfile,
    *,
    lineage: bool = True,
) -> ApplyResult:
    """Apply a saved recipe to a new file, or fail without changing anything."""
    compatibility = check_compatibility(recipe_file, profile)
    if not compatibility.compatible:
        raise RecipeIncompatibleError(compatibility.problems)
    return apply_recipe(conn, recipe_file.recipe, base_schema(profile), lineage=lineage)


def load_recipe_file(data: bytes) -> RecipeFile:
    try:
        raw = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecipeFileError("This isn't a recipe file we can read.") from exc
    if not isinstance(raw, dict) or raw.get("format") != "tidylab.recipe":
        raise RecipeFileError("This file isn't a TidyLab recipe.")
    if raw.get("version") != 1:
        raise RecipeFileError("This recipe was saved by a different version of TidyLab.")
    try:
        recipe_file = RecipeFile.model_validate(raw)
    except ValidationError as exc:
        raise RecipeFileError(f"This recipe file has a problem: {_describe(exc)}") from exc
    # Answers looked up for another file don't come along: a hand-edited id
    # must not point this file at someone else's lookup.
    return recipe_file.model_copy(update={"recipe": without_snapshots(recipe_file.recipe)})


def _describe(error: ValidationError) -> str:
    first = error.errors()[0]
    location = list(first["loc"])
    if len(location) >= 3 and location[:2] == ["recipe", "steps"]:
        where = f"step {int(location[2]) + 1}"
        field = ".".join(str(part) for part in location[4:] if not isinstance(part, int))
    else:
        where = "the file"
        field = ".".join(str(part) for part in location)
    detail = first["msg"].removeprefix("Value error, ")
    return f"{where}: {field + ': ' if field else ''}{detail}."


def _loose(name: str) -> str:
    return " ".join(name.replace("_", " ").replace("-", " ").split()).casefold()
