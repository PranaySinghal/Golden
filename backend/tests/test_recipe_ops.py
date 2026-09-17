import pytest

from app.steps.apply import StepStatus, plan_recipe
from app.steps.errors import StepNotFoundError, StepValidationError
from app.steps.models import (
    CastNumberStep,
    EqualsCondition,
    Recipe,
    SetAsideRowsStep,
    SplitColumnStep,
    TrimStep,
)
from app.steps.recipe_ops import (
    HISTORY_LIMIT,
    RecipeHistory,
    add_step,
    remove_step,
    set_enabled,
    undo,
    update_step,
)
from app.steps.schema import StageSchema

BASE = StageSchema.all_text(["name", "amount", "region"])
SPLIT = SplitColumnStep(column="region", delimiter="-", into=["area", "side"])
USES_SPLIT = SetAsideRowsStep(condition=EqualsCondition(column="side", value="West"))


def build(*steps: object) -> tuple[Recipe, RecipeHistory]:
    recipe, history = Recipe(), RecipeHistory()
    for step in steps:
        edit = add_step(recipe, history, step, BASE)  # type: ignore[arg-type]
        recipe, history = edit.recipe, edit.history
    return recipe, history


def test_add_appends_and_remembers_the_previous_recipe() -> None:
    recipe, history = build(TrimStep(columns=["name"]))

    edit = add_step(recipe, history, SPLIT, BASE)

    assert [s.id for s in edit.recipe.steps] == [recipe.steps[0].id, SPLIT.id]
    assert edit.history.past[-1] == recipe


def test_add_at_a_position() -> None:
    recipe, history = build(TrimStep(columns=["name"]), SPLIT)
    first = TrimStep(columns=["amount"])

    edit = add_step(recipe, history, first, BASE, position=0)

    assert edit.recipe.steps[0].id == first.id


def test_add_rejects_a_step_that_cannot_run() -> None:
    recipe, history = build()

    with pytest.raises(StepValidationError, match='no column called "side"'):
        add_step(recipe, history, USES_SPLIT, BASE)


def test_add_rejects_a_duplicate_id() -> None:
    recipe, history = build(SPLIT)

    with pytest.raises(StepValidationError, match="already in the recipe"):
        add_step(recipe, history, SPLIT, BASE)


def test_update_replaces_in_place_and_is_validated() -> None:
    recipe, history = build(SPLIT, TrimStep(columns=["name"]))
    renamed = SPLIT.model_copy(update={"into": ["zone", "direction"]})

    edit = update_step(recipe, history, renamed, BASE)
    assert edit.recipe.steps[0] == renamed

    broken = SPLIT.model_copy(update={"column": "missing"})
    with pytest.raises(StepValidationError):
        update_step(recipe, history, broken, BASE)


def test_disabling_a_needed_step_is_allowed_and_blocks_dependents() -> None:
    recipe, history = build(SPLIT, USES_SPLIT)

    edit = set_enabled(recipe, history, SPLIT.id, False, BASE)

    outcomes = plan_recipe(edit.recipe, BASE).outcomes
    assert [o.status for o in outcomes] == [StepStatus.DISABLED, StepStatus.BLOCKED]


def test_enabling_a_step_that_cannot_run_is_rejected() -> None:
    recipe, history = build(SPLIT, USES_SPLIT)
    recipe = set_enabled(recipe, history, USES_SPLIT.id, False, BASE).recipe
    recipe = set_enabled(recipe, history, SPLIT.id, False, BASE).recipe

    with pytest.raises(StepValidationError, match="turned off"):
        set_enabled(recipe, history, USES_SPLIT.id, True, BASE)


def test_setting_the_same_enabled_value_is_not_an_edit() -> None:
    recipe, history = build(SPLIT)

    edit = set_enabled(recipe, history, SPLIT.id, True, BASE)

    assert (edit.recipe, edit.history) == (recipe, history)


def test_unknown_step_id() -> None:
    recipe, history = build(SPLIT)

    with pytest.raises(StepNotFoundError):
        remove_step(recipe, history, "000000000000")
    with pytest.raises(StepNotFoundError):
        set_enabled(recipe, history, "000000000000", False, BASE)
    with pytest.raises(StepNotFoundError):
        update_step(recipe, history, TrimStep(columns=["name"]), BASE)


@pytest.mark.parametrize("operation", ["add", "remove", "disable", "update"])
def test_undo_returns_the_exact_previous_recipe(operation: str) -> None:
    recipe, history = build(SPLIT, CastNumberStep(column="amount"))

    match operation:
        case "add":
            edit = add_step(recipe, history, TrimStep(columns=["name"]), BASE)
        case "remove":
            edit = remove_step(recipe, history, SPLIT.id)
        case "disable":
            edit = set_enabled(recipe, history, SPLIT.id, False, BASE)
        case _:
            edit = update_step(recipe, history, SPLIT.model_copy(update={"delimiter": "/"}), BASE)

    undone = undo(edit.recipe, edit.history)

    assert undone.undone
    assert undone.recipe == recipe
    assert undone.history == history


def test_undo_walks_back_through_several_edits() -> None:
    recipe, history = build(SPLIT, TrimStep(columns=["name"]), CastNumberStep(column="amount"))

    for expected_steps in (2, 1, 0):
        result = undo(recipe, history)
        recipe, history = result.recipe, result.history
        assert len(recipe.steps) == expected_steps


def test_undo_with_nothing_to_undo() -> None:
    recipe, history = Recipe(), RecipeHistory()

    result = undo(recipe, history)

    assert (result.undone, result.recipe, result.history) == (False, recipe, history)


def test_history_is_capped() -> None:
    recipe, history = Recipe(), RecipeHistory()
    for _ in range(HISTORY_LIMIT + 5):
        history = history.push(recipe)

    assert len(history.past) == HISTORY_LIMIT
