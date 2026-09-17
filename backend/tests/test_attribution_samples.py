"""What each sample file's cleaning is credited with, pinned to golden files."""

import json
from typing import Any

import duckdb
import pytest

from app.compare.engine import ComparisonEngine
from app.compare.models import Comparison
from app.config import Settings
from app.detectors.step_order import recipe_for
from app.steps.models import Recipe, Step
from tests.conftest import GOLDEN_DIR, SAMPLES_DIR, Dataset, load

SAMPLES = ["Messy_Employee_dataset", "store_orders", "Messy_Employee_dataset_messier"]


def sample(name: str) -> Dataset:
    conn = duckdb.connect(":memory:")
    load(conn, (SAMPLES_DIR / f"{name}.csv").read_bytes())
    return Dataset(conn)


def describe(step: Step) -> str:
    """A step as its type and the columns it works on, so ids stay out of the file."""
    columns = getattr(step, "columns", None) or getattr(step, "column", None)
    if columns is None:
        condition = getattr(step, "condition", None)
        columns = getattr(condition, "column", None) if condition else None
    if isinstance(columns, list):
        return f"{step.type}({', '.join(columns)})"
    return f"{step.type}({columns})" if columns else f"{step.type}()"


def summary(comparison: Comparison, recipe: Recipe) -> list[dict[str, Any]]:
    steps = {step.id: describe(step) for step in recipe.steps}
    return [
        {
            "question": diff.question.label,
            "unlocked": diff.unlocked,
            "method": diff.attribution_method,
            "caused_by": [
                {
                    "steps": [steps.get(step_id, step_id) for step_id in part.step_ids],
                    "together": part.together,
                }
                for part in diff.attribution_detail
            ],
        }
        for diff in comparison.diffs
        if diff.changed
    ]


def run(name: str) -> tuple[Comparison, Recipe]:
    ds = sample(name)
    recipe = recipe_for(ds.issues())
    return ComparisonEngine(ds.conn, ds.profile).compare(recipe), recipe


@pytest.mark.parametrize("name", SAMPLES)
def test_attribution_matches_golden_file(name: str) -> None:
    expected = json.loads((GOLDEN_DIR / "attribution" / f"{name}.json").read_text())
    comparison, recipe = run(name)

    assert summary(comparison, recipe) == expected


@pytest.mark.parametrize("name", SAMPLES)
def test_answers_that_stayed_put_are_not_explained(name: str) -> None:
    comparison, _ = run(name)

    unchanged = [diff for diff in comparison.diffs if not diff.changed]
    assert all(diff.attribution_method == "none" for diff in unchanged)
    assert all(diff.attribution == [] for diff in unchanged)


@pytest.mark.parametrize("name", SAMPLES)
def test_every_credited_step_is_in_the_recipe(name: str) -> None:
    comparison, recipe = run(name)
    ids = {step.id for step in recipe.steps}

    for diff in comparison.diffs:
        assert set(diff.attribution) <= ids
        listed = [step_id for part in diff.attribution_detail for step_id in part.step_ids]
        assert diff.attribution == list(dict.fromkeys(listed))


@pytest.mark.parametrize("name", SAMPLES)
def test_the_cost_of_a_comparison_is_bounded(name: str) -> None:
    ds = sample(name)
    recipe = recipe_for(ds.issues())
    settings = Settings()
    engine = ComparisonEngine(ds.conn, ds.profile, settings=settings)

    comparison = engine.compare(recipe)

    questions = len(comparison.diffs)
    # Both sides of every question, the unlocked ones that didn't make the cut,
    # and at most the attribution budget on top.
    assert comparison.evaluations <= 4 * questions + settings.max_attribution_queries
