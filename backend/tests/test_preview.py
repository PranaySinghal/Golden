"""The few rows a card shows: what changes, and what gets set aside."""

from collections.abc import Callable

from app.preview import MAX_COLUMNS, Preview, preview
from app.steps.models import (
    CastNumberStep,
    DedupeStep,
    EqualsCondition,
    NullPlaceholdersStep,
    Recipe,
    SetAsideRowsStep,
    SplitColumnStep,
    Step,
    TrimStep,
)
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]


def show(ds: Dataset, *steps: Step, existing: list[Step] | None = None, limit: int = 5) -> Preview:
    without = Recipe(steps=existing or [])
    with_steps = Recipe(steps=[*(existing or []), *steps])
    return preview(ds.conn, ds.base, without, with_steps, {step.id for step in steps}, limit=limit)


def test_a_value_change_shows_before_and_after(make_dataset: MakeDataset) -> None:
    ds = make_dataset("City,Name\n Paris ,Ann\nRome,Bo\n")

    result = show(ds, TrimStep(columns=["City"]))

    assert result.columns == ["City"]
    assert result.changed_rows == 1
    cell = result.rows[0].cells["City"]
    assert (cell.before, cell.after, cell.changed) == (" Paris ", "Paris", True)


def test_only_rows_that_change_are_shown(make_dataset: MakeDataset) -> None:
    ds = make_dataset("City\n Paris \nRome\nLyon\n")

    result = show(ds, TrimStep(columns=["City"]))

    assert [row.row_id for row in result.rows] == [1]


def test_nothing_changes_says_so(make_dataset: MakeDataset) -> None:
    ds = make_dataset("City\nParis\nRome\n")

    result = show(ds, TrimStep(columns=["City"]))

    assert (result.rows, result.changed_rows) == ([], 0)
    assert result.note == "Nothing in this file changes."


def test_rows_set_aside_keep_their_values_and_are_marked(make_dataset: MakeDataset) -> None:
    ds = make_dataset("Status,Name\nLeft,Ann\nHere,Bo\n")

    result = show(ds, SetAsideRowsStep(condition=EqualsCondition(column="Status", value="Left")))

    assert (result.changed_rows, result.set_aside_rows) == (1, 1)
    row = result.rows[0]
    assert row.set_aside is True
    assert (row.cells["Status"].before, row.cells["Status"].changed) == ("Left", False)


def test_repeated_rows_show_the_ones_that_go(make_dataset: MakeDataset) -> None:
    ds = make_dataset("Email\na@x.com\na@x.com\nb@x.com\n")

    result = show(ds, DedupeStep(columns=["Email"]))

    assert [(row.row_id, row.set_aside) for row in result.rows] == [(2, True)]


def test_a_created_column_has_no_before(make_dataset: MakeDataset) -> None:
    ds = make_dataset("Dept_Region\nSales-North\nHR-South\n")

    result = show(ds, SplitColumnStep(column="Dept_Region", delimiter="-", into=["Dept", "Region"]))

    assert result.columns == ["Dept_Region", "Dept", "Region"]
    assert result.rows[0].cells["Dept"].before is None
    assert result.rows[0].cells["Dept"].after == "Sales"


def test_a_step_that_cant_run_explains_why(make_dataset: MakeDataset) -> None:
    ds = make_dataset("Age\n30\n40\n")

    result = show(ds, CastNumberStep(column="Salary"))

    assert result.rows == []
    assert result.note is not None
    assert "Salary" in result.note


def test_a_preview_reads_the_recipe_that_is_already_there(make_dataset: MakeDataset) -> None:
    """Clearing "N/A" first is what makes reading Salary as numbers change nothing."""
    ds = make_dataset("Salary\n100\nN/A\n")
    clear = NullPlaceholdersStep(columns=["Salary"], placeholders=["N/A"])

    with_clear = show(ds, CastNumberStep(column="Salary"), existing=[clear])
    without_clear = show(ds, CastNumberStep(column="Salary"))

    assert with_clear.changed_rows == 0
    assert without_clear.changed_rows == 1


def test_the_row_limit_is_honoured(make_dataset: MakeDataset) -> None:
    rows = "".join(f" {name} \n" for name in ["a", "b", "c", "d", "e", "f"])
    ds = make_dataset(f"City\n{rows}")

    result = show(ds, TrimStep(columns=["City"]), limit=2)

    assert (len(result.rows), result.changed_rows) == (2, 6)


def test_a_preview_shows_a_handful_of_columns_at_most(make_dataset: MakeDataset) -> None:
    names = [f"c{index}" for index in range(10)]
    ds = make_dataset(",".join(names) + "\n" + ",".join(" x " for _ in names) + "\n")

    result = show(ds, TrimStep(columns=names))

    assert len(result.columns) == MAX_COLUMNS


def test_a_file_with_no_rows_yet_previews_as_no_change(make_dataset: MakeDataset) -> None:
    ds = make_dataset("City,Name\n")

    result = show(ds, TrimStep(columns=["City"]))

    assert (result.rows, result.changed_rows, result.set_aside_rows) == ([], 0, 0)


def test_a_preview_leaves_no_tables_behind(make_dataset: MakeDataset) -> None:
    ds = make_dataset("City\n Paris \n")

    show(ds, TrimStep(columns=["City"]))

    tables = ds.conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'work'"
    ).fetchall()
    assert [name for (name,) in tables if "preview" in str(name)] == []
