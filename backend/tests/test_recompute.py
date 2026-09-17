"""Changing an ask-tier choice: same answers as a fresh comparison, less work."""

from collections.abc import Iterator
from typing import Any

import duckdb
import pytest

from app.compare.engine import ComparisonEngine
from app.compare.models import Comparison
from app.detectors.models import Issue, Tier
from app.detectors.step_order import recipe_for
from app.questions.models import AnswerDiff
from app.steps.models import Recipe
from tests.conftest import SAMPLES_DIR, Dataset, load


@pytest.fixture(scope="module")
def employees() -> Iterator[Dataset]:
    conn = duckdb.connect(":memory:")
    load(conn, (SAMPLES_DIR / "Messy_Employee_dataset.csv").read_bytes())
    yield Dataset(conn)
    conn.close()


def ask_issues(ds: Dataset) -> list[Issue]:
    return [issue for issue in ds.issues() if issue.tier is Tier.ASK]


def recipe_with(ds: Dataset, issue: Issue, choice_id: str) -> Recipe:
    return recipe_for(ds.issues(), answers={issue.id: choice_id})


def fresh(ds: Dataset, recipe: Recipe) -> Comparison:
    return ComparisonEngine(ds.conn, ds.profile).compare(recipe)


def shape(diffs: list[AnswerDiff]) -> list[dict[str, Any]]:
    """What a comparison says, to the precision the app treats as real.

    Adding the same doubles in a different order can move the last bit, and a
    cached answer was added in whatever order produced it, so answers are
    compared the way `same_number` compares them rather than bit for bit.
    """

    def value(number: float | None) -> float | None:
        return None if number is None else round(number, 6)

    return [
        {
            "question": d.question.label,
            "before": value(d.before.value),
            "after": value(d.after.value),
            "groups": [(g.key, value(g.value)) for g in d.after.groups],
            "changed": d.changed,
            "impact": value(d.impact),
            "unlocked": d.unlocked,
            "attribution": d.attribution,
            "method": d.attribution_method,
        }
        for d in diffs
    ]


def question_id(ds: Dataset, label: str) -> str:
    engine = ComparisonEngine(ds.conn, ds.profile)
    return next(q.id for q in engine.questions if q.label == label)


def test_there_are_choices_to_switch_between(employees: Dataset) -> None:
    assert [issue.detector.value for issue in ask_issues(employees)]


def test_every_choice_gives_what_a_fresh_comparison_would(employees: Dataset) -> None:
    engine = ComparisonEngine(employees.conn, employees.profile)
    previous = engine.compare(recipe_for(employees.issues()))

    for issue in ask_issues(employees):
        assert issue.ask is not None
        for choice in issue.ask.choices:
            recipe = recipe_with(employees, issue, choice.id)

            reused = engine.recompute(previous, recipe)

            assert shape(reused.diffs) == shape(fresh(employees, recipe).diffs)
            previous = reused


def test_switching_a_salary_choice_leaves_name_counts_alone(employees: Dataset) -> None:
    placeholders = next(
        issue for issue in ask_issues(employees) if issue.detector.value == "placeholders"
    )
    assert placeholders.ask is not None
    missing, zero = placeholders.ask.choices
    engine = ComparisonEngine(employees.conn, employees.profile)
    previous = engine.compare(recipe_with(employees, placeholders, missing.id))

    changed = engine.recompute(previous, recipe_with(employees, placeholders, zero.id))

    names = question_id(employees, 'How many rows are there for each "First_Name"?')
    salary = question_id(employees, 'What\'s the average "Salary"?')
    assert names not in changed.recomputed
    assert salary in changed.recomputed


def test_recomputing_costs_less_than_starting_over(employees: Dataset) -> None:
    placeholders = next(
        issue for issue in ask_issues(employees) if issue.detector.value == "placeholders"
    )
    assert placeholders.ask is not None
    missing, zero = placeholders.ask.choices
    engine = ComparisonEngine(employees.conn, employees.profile)
    previous = engine.compare(recipe_with(employees, placeholders, missing.id))

    changed = engine.recompute(previous, recipe_with(employees, placeholders, zero.id))

    assert 0 < changed.evaluations < previous.evaluations


def test_switching_back_costs_nothing(employees: Dataset) -> None:
    placeholders = next(
        issue for issue in ask_issues(employees) if issue.detector.value == "placeholders"
    )
    assert placeholders.ask is not None
    missing, zero = placeholders.ask.choices
    engine = ComparisonEngine(employees.conn, employees.profile)
    first = engine.compare(recipe_with(employees, placeholders, missing.id))
    second = engine.recompute(first, recipe_with(employees, placeholders, zero.id))

    back = engine.recompute(second, recipe_with(employees, placeholders, missing.id))

    assert (back.evaluations, back.recomputed) == (0, [])
    assert shape(back.diffs) == shape(first.diffs)
