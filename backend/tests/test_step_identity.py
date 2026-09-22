"""Matching steps by what they do, not by which object does it."""

import pytest

from app.steps.identity import matched_ids, work_key
from app.steps.models import (
    CastNumberStep,
    NullPlaceholdersStep,
    Recipe,
    Step,
    TrimStep,
)


def test_the_same_work_under_a_different_id_matches() -> None:
    one = TrimStep(columns=["Name"])
    other = TrimStep(columns=["Name"])

    assert one.id != other.id
    assert work_key(one) == work_key(other)


def test_a_step_switched_off_still_does_the_same_work() -> None:
    on = TrimStep(columns=["Name"])
    off = on.model_copy(update={"enabled": False})

    assert work_key(on) == work_key(off)


@pytest.mark.parametrize(
    "other",
    [
        TrimStep(columns=["Other"]),
        TrimStep(columns=["Name"], collapse_inner_spaces=True),
        TrimStep(columns=["Name", "Other"]),
        CastNumberStep(column="Name"),
    ],
    ids=["column", "option", "more columns", "kind"],
)
def test_different_work_does_not_match(other: Step) -> None:
    assert work_key(TrimStep(columns=["Name"])) != work_key(other)


def test_the_recipes_own_ids_come_back() -> None:
    mine = TrimStep(columns=["Name"])
    theirs = TrimStep(columns=["Name"])
    recipe = Recipe(steps=[theirs])

    assert matched_ids(recipe, [mine]) == [theirs.id]


def test_order_in_the_recipe_does_not_matter() -> None:
    trim = TrimStep(columns=["Name"])
    cast = CastNumberStep(column="Salary")
    recipe = Recipe(steps=[cast, trim])

    assert matched_ids(recipe, [TrimStep(columns=["Name"])]) == [trim.id]


def test_one_missing_step_means_no_match_at_all() -> None:
    recipe = Recipe(steps=[TrimStep(columns=["Name"])])

    found = matched_ids(recipe, [TrimStep(columns=["Name"]), CastNumberStep(column="Salary")])

    assert found is None


def test_no_steps_matches_with_nothing_to_show() -> None:
    # Not the same answer as None: a choice meaning "leave it alone" carries no
    # steps and is still a choice that can have been taken.
    assert matched_ids(Recipe(steps=[TrimStep(columns=["Name"])]), []) == []


def test_two_identical_proposals_need_two_steps_in_the_recipe() -> None:
    recipe = Recipe(steps=[TrimStep(columns=["Name"])])
    twice = [TrimStep(columns=["Name"]), TrimStep(columns=["Name"])]

    assert matched_ids(recipe, twice) is None

    recipe = Recipe(steps=[TrimStep(columns=["Name"]), TrimStep(columns=["Name"])])
    found = matched_ids(recipe, twice)
    assert found is not None
    assert len(set(found)) == 2


def test_parameters_are_part_of_the_work() -> None:
    saved = NullPlaceholdersStep(columns=["Salary"], placeholders=["N/A"])
    wider = NullPlaceholdersStep(columns=["Salary"], placeholders=["N/A", "-"])

    assert matched_ids(Recipe(steps=[saved]), [wider]) is None
