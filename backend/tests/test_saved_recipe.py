"""Re-using steps saved from one file on another one."""

from collections.abc import Iterator

import pytest

from app import review
from app.config import Settings
from app.saved_recipe import apply_saved_recipe
from app.steps.export import build_recipe_file, recipe_file_bytes
from app.steps.models import (
    CastNumberStep,
    NullPlaceholdersStep,
    ParseDateStep,
    Recipe,
    SplitColumnStep,
    TrimStep,
    new_step_id,
)
from app.store import DatasetSession, DatasetStore
from tests.conftest import SAMPLES_DIR

EMPLOYEE = (SAMPLES_DIR / "Messy_Employee_dataset.csv").read_bytes()
MESSIER = (SAMPLES_DIR / "Messy_Employee_dataset_messier.csv").read_bytes()
ORDERS = (SAMPLES_DIR / "store_orders.csv").read_bytes()


@pytest.fixture
def store() -> Iterator[DatasetStore]:
    made = DatasetStore(Settings())
    yield made
    made.close_all()


def employee_steps() -> Recipe:
    return Recipe(
        steps=[
            NullPlaceholdersStep(columns=["Salary"], placeholders=["N/A"]),
            CastNumberStep(column="Salary"),
            SplitColumnStep(
                column="Department_Region", delimiter="-", into=["Department", "Region"]
            ),
            ParseDateStep(column="Join_Date", formats=["%m/%d/%Y"]),
        ]
    )


def saved_from(session: DatasetSession, recipe: Recipe) -> bytes:
    return recipe_file_bytes(build_recipe_file(recipe, session.base_schema, session.filename))


def work_tables(session: DatasetSession) -> list[str]:
    rows = session.conn.execute(
        "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'work'"
    ).fetchall()
    return [str(row[0]) for row in rows]


def test_saved_steps_run_on_next_months_file(store: DatasetStore) -> None:
    saved = employee_steps()
    first = store.create("employees.csv", EMPLOYEE)
    data = saved_from(first, saved)
    second = store.create("employees-later.csv", MESSIER)

    outcome = apply_saved_recipe(second, data)

    assert outcome.applied
    assert outcome.steps_applied == 4
    assert outcome.source_filename == "employees.csv"
    assert outcome.problems == []
    assert [step.id for step in second.recipe.steps] == [step.id for step in saved.steps]
    # The split really ran: the new columns exist on the cleaned rows.
    assert second.applied is not None
    assert {"Department", "Region"} <= {column.name for column in second.applied.columns}


def test_the_first_review_after_a_replay_still_works(store: DatasetStore) -> None:
    """Detection gives the same step ids the saved recipe already carries.

    Adding one twice raises, so without matching on what a step does this is
    the request that never returns: the review screen would never render.
    """
    first = store.create("employees.csv", EMPLOYEE)
    review.prepare(first)
    data = saved_from(first, first.recipe)
    second = store.create("employees-later.csv", EMPLOYEE)
    apply_saved_recipe(second, data)
    before = list(second.recipe.steps)

    issues = review.prepare(second)

    assert issues
    assert [step.id for step in second.recipe.steps] == [step.id for step in before]


def test_a_card_reads_as_done_when_the_recipe_already_does_its_work(
    store: DatasetStore,
) -> None:
    first = store.create("employees.csv", EMPLOYEE)
    review.prepare(first)
    safe = next(issue for issue in review.issues_of(first) if issue.steps)
    # The same work under ids of its own — a model's fix, or a recipe hand-built
    # elsewhere, arrives looking like this.
    fresh = Recipe(
        steps=[step.model_copy(update={"id": new_step_id()}) for step in safe.steps]
    )
    assert {step.id for step in fresh.steps}.isdisjoint(step.id for step in safe.steps)

    second = store.create("employees-later.csv", EMPLOYEE)
    apply_saved_recipe(second, saved_from(first, fresh))
    review.prepare(second)
    same = next(issue for issue in review.issues_of(second) if issue.id == safe.id)

    state = review.state_of(second, same)
    assert state.state == "applied"
    # The ids handed back are the recipe's, so the panel can be pointed at them.
    assert set(state.step_ids) <= {step.id for step in second.recipe.steps}


def test_steps_that_dont_fit_change_nothing(store: DatasetStore) -> None:
    first = store.create("employees.csv", EMPLOYEE)
    data = saved_from(first, employee_steps())
    orders = store.create("store_orders.csv", ORDERS)

    outcome = apply_saved_recipe(orders, data)

    assert not outcome.applied
    # Every column it needs and can't find, not just the first one.
    assert len(outcome.problems) == 3
    for column in ["Salary", "Department_Region", "Join_Date"]:
        assert any(f'"{column}"' in problem for problem in outcome.problems)
    assert orders.recipe.steps == []
    # Nothing was built for a file the steps were refused on.
    assert work_tables(orders) == []


def test_a_file_that_isnt_a_recipe_is_explained(store: DatasetStore) -> None:
    session = store.create("employees.csv", EMPLOYEE)

    outcome = apply_saved_recipe(session, b"not json {")

    assert not outcome.applied
    assert "isn't a recipe file" in outcome.problems[0]
    assert session.recipe.steps == []


def test_a_warning_does_not_stop_the_steps(store: DatasetStore) -> None:
    first = store.create("numbers.csv", b"amount\n5\n6\n7\n")
    data = saved_from(first, Recipe(steps=[CastNumberStep(column="amount")]))
    wordy = store.create("words.csv", b"amount\nfive\nsix\nseven\neight\n")

    outcome = apply_saved_recipe(wordy, data)

    assert outcome.applied
    assert outcome.warnings == [
        '"amount" doesn\'t look mostly like numbers in this file, so many values may end up blank.'
    ]


def test_replacing_the_recipe_can_be_undone(store: DatasetStore) -> None:
    session = store.create("employees.csv", EMPLOYEE)
    review.prepare(session)
    mine = list(session.recipe.steps)
    assert mine

    other = store.create("other.csv", EMPLOYEE)
    apply_saved_recipe(session, saved_from(other, Recipe(steps=[TrimStep(columns=["Email"])])))
    assert [step.id for step in session.recipe.steps] != [step.id for step in mine]

    assert review.undo(session)
    assert [step.id for step in session.recipe.steps] == [step.id for step in mine]


def test_decisions_about_the_old_recipe_are_let_go(store: DatasetStore) -> None:
    session = store.create("employees.csv", EMPLOYEE)
    review.prepare(session)
    turned_down = review.issues_of(session)[0]
    review.reject(session, turned_down.id)
    assert session.rejected

    other = store.create("other.csv", EMPLOYEE)
    apply_saved_recipe(session, saved_from(other, Recipe(steps=[TrimStep(columns=["Email"])])))

    assert session.rejected == set()
    assert session.answers == {}
