"""Questions the raw file couldn't answer at all, that cleaning makes possible."""

from collections.abc import Callable

import duckdb
import pytest

from app.compare.models import Comparison
from app.compare.unlocked import MAX_UNLOCKED
from app.detectors.step_order import recipe_for
from app.questions.models import AnswerDiff, Question
from app.steps.models import CastNumberStep, ParseDateStep, Recipe, SplitColumnStep, Step, TrimStep
from tests.conftest import SAMPLES_DIR, Dataset, load

MakeDataset = Callable[..., Dataset]


def sample(name: str) -> Dataset:
    conn = duckdb.connect(":memory:")
    load(conn, (SAMPLES_DIR / f"{name}.csv").read_bytes())
    return Dataset(conn)


def run(ds: Dataset, *steps: Step) -> Comparison:
    return ds.engine().compare(Recipe(steps=list(steps)))


def unlocked(comparison: Comparison) -> list[AnswerDiff]:
    return [d for d in comparison.diffs if d.unlocked]


def labels(comparison: Comparison) -> list[str]:
    return [d.question.label for d in unlocked(comparison)]


def find(comparison: Comparison, label: str) -> AnswerDiff:
    return next(d for d in comparison.diffs if d.question.label == label)


# --- a column that didn't exist before -----------------------------------------------------


def test_splitting_a_column_unlocks_a_headcount_by_department() -> None:
    ds = sample("Messy_Employee_dataset")
    split = next(
        step
        for step in recipe_for(ds.issues()).steps
        if isinstance(step, SplitColumnStep) and step.column == "Department_Region"
    )

    comparison = run(ds, split)
    headcount = find(comparison, 'How many rows are there for each "Department"?')

    assert 'How many rows are there for each "Region"?' in labels(comparison)
    assert headcount.unlocked
    assert headcount.before.answerable is False
    assert len(headcount.after.groups) == 6
    assert headcount.attribution == [split.id]
    assert headcount.question.origin == "unlocked"


def test_a_created_column_is_only_asked_about_when_it_suits_a_question(
    make_dataset: MakeDataset,
) -> None:
    """Names split off a full-name column are nearly all different: no breakdown."""
    ds = make_dataset("Full_Name\nAnn Lee\nBo Poe\nCy Ray\nDee Sol\n")
    split = SplitColumnStep(column="Full_Name", delimiter=" ", into=["First", "Last"])

    assert labels(run(ds, split)) == []


def test_unlocked_questions_are_capped() -> None:
    ds = sample("Messy_Employee_dataset")
    recipe = recipe_for(ds.issues())

    comparison = ds.engine().compare(recipe)

    assert len(unlocked(comparison)) <= MAX_UNLOCKED


# --- values that couldn't be read before ---------------------------------------------------


def test_prices_written_as_money_unlock_a_total() -> None:
    ds = sample("store_orders")
    cast = CastNumberStep(column="Unit Price")

    comparison = run(ds, cast)

    assert 'What\'s the total "Unit Price"?' in labels(comparison)
    assert 'What\'s the average "Unit Price"?' in labels(comparison)
    assert find(comparison, 'What\'s the total "Unit Price"?').attribution == [cast.id]


def test_a_date_style_a_spreadsheet_cant_read_unlocks_a_trend(make_dataset: MakeDataset) -> None:
    ds = make_dataset("Joined,Name\n15.03.2024,Ann\n18.03.2024,Bo\n02.04.2024,Cy\n11.04.2024,Dee\n")
    parse = ParseDateStep(column="Joined", formats=["%d.%m.%Y"])

    comparison = run(ds, parse)

    assert 'How many rows are there each month, by "Joined"?' in labels(comparison)


def test_an_answer_both_sides_can_give_is_a_change_not_a_new_question() -> None:
    """Some of these dates read before cleaning, so the trend only moved."""
    ds = sample("store_orders")
    recipe = recipe_for(ds.issues())

    comparison = ds.engine().compare(recipe)
    trend = find(comparison, 'How many rows are there each month, by "Order Date"?')

    assert (trend.changed, trend.unlocked) == (True, False)


# --- nothing new ---------------------------------------------------------------------------


@pytest.mark.parametrize("sample_name", ["Messy_Employee_dataset", "store_orders"])
def test_no_new_questions_when_the_recipe_creates_nothing(sample_name: str) -> None:
    ds = sample(sample_name)
    columns = [column.name for column in ds.profile.columns]

    assert labels(run(ds, TrimStep(columns=columns))) == []


def test_an_unlocked_question_is_asked_once(make_dataset: MakeDataset) -> None:
    """A question the raw file already asks doesn't come back as a new one."""
    ds = make_dataset("City,Salary\nParis,100\nRome,200\nParis,300\n")
    cast = CastNumberStep(column="Salary")

    comparison = run(ds, cast)
    asked: list[Question] = [d.question for d in comparison.diffs]

    assert len(asked) == len({q.id for q in asked})
    assert labels(comparison) == []
