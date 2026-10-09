"""add_column: a new column that is blank, or holds the same text in every row."""

import csv
import io
from collections.abc import Callable
from pathlib import Path

from app.steps.apply import StepStatus
from app.steps.copy import columns_of, describe
from app.steps.export import cleaned_csv_bytes
from app.steps.models import AddColumnStep, DedupeStep, Recipe, SplitColumnStep, TrimStep
from app.steps.replay import required_columns
from app.steps.schema import StageSchema
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]

PEOPLE = "name,team\nAnn,Sales\nBo,Support\n"


def test_an_empty_column_goes_last_and_changes_no_cells(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    result = ds.apply(AddColumnStep(name="Notes"))

    assert result.outcomes[0].status is StepStatus.APPLIED
    assert [column.name for column in result.columns] == ["name", "team", "Notes"]
    assert ds.column("Notes") == [None, None]
    assert ds.changes() == []


def test_placeholder_text_fills_every_row_and_is_traced_to_the_step(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset(PEOPLE)
    step = AddColumnStep(name="Status", value="To review", insert_after="name")

    result = ds.apply(step)

    assert [column.name for column in result.columns] == ["name", "Status", "team"]
    assert ds.column("Status") == ["To review", "To review"]
    assert result.outcomes[0].cells_changed == 2
    assert [change[3:] for change in ds.changes()] == [(None, "To review", "created")] * 2


def test_placeholder_text_is_data_never_sql(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    ds.apply(AddColumnStep(name='x"; DROP TABLE t; --', value="'); DROP TABLE t; --"))

    assert ds.column('x"; DROP TABLE t; --') == ["'); DROP TABLE t; --"] * 2


def test_text_made_only_of_spaces_leaves_the_column_blank(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    ds.apply(AddColumnStep(name="Notes", value="   "))

    assert ds.column("Notes") == [None, None]


def test_a_name_already_in_use_is_refused_whatever_its_capitals(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset(PEOPLE)

    result = ds.apply(AddColumnStep(name="TEAM"))

    assert result.outcomes[0].status is StepStatus.BLOCKED
    assert "already a column" in (result.outcomes[0].reason or "")
    assert [column.name for column in result.columns] == ["name", "team"]


def test_the_internal_row_number_name_is_reserved(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    result = ds.apply(AddColumnStep(name="_ROW_ID"))

    assert result.outcomes[0].status is StepStatus.BLOCKED
    assert "reserved" in (result.outcomes[0].reason or "")


def test_placing_it_after_a_column_that_isnt_there_is_refused(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    result = ds.apply(AddColumnStep(name="Notes", insert_after="nope"))

    assert result.outcomes[0].status is StepStatus.BLOCKED


def test_it_can_sit_after_a_column_an_earlier_step_made(make_dataset: MakeDataset) -> None:
    ds = make_dataset("who\nAnn-Sales\nBo-Support\n")

    result = ds.apply(
        SplitColumnStep(column="who", delimiter="-", into=["name", "team"]),
        AddColumnStep(name="Notes", insert_after="name"),
    )

    assert [column.name for column in result.columns] == ["who", "name", "Notes", "team"]


def test_switched_off_is_the_same_as_never_added(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)
    trim = TrimStep(columns=["name"])
    without = ds.apply(trim)

    with_it_off = ds.apply(trim, AddColumnStep(name="Notes", value="x", enabled=False))

    assert with_it_off.fingerprint == without.fingerprint
    assert with_it_off.columns == without.columns


def test_it_does_not_change_which_rows_count_as_repeats(make_dataset: MakeDataset) -> None:
    ds = make_dataset("name\nAnn\nAnn\nBo\n")

    result = ds.apply(DedupeStep(), AddColumnStep(name="Status", value="To review"))

    assert result.row_count == 2
    assert ds.column("Status") == ["To review", "To review"]


def test_a_recipe_only_needs_the_column_it_was_placed_after(make_dataset: MakeDataset) -> None:
    base = StageSchema.all_text(["name", "team"])

    assert required_columns(Recipe(steps=[AddColumnStep(name="Notes")]), base) == []
    assert required_columns(
        Recipe(steps=[AddColumnStep(name="Notes", insert_after="team")]), base
    ) == ["team"]


def test_the_download_has_the_column_and_guards_formula_text(
    make_dataset: MakeDataset, tmp_path: Path
) -> None:
    ds = make_dataset(PEOPLE)
    result = ds.apply(AddColumnStep(name="Check", value="=1+1"))

    text = cleaned_csv_bytes(ds.conn, result, tmp_path).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))

    assert rows[0] == ["name", "team", "Check"]
    assert rows[1][2] == "'=1+1"


def test_how_it_reads_in_the_recipe_panel() -> None:
    blank = AddColumnStep(name="Notes")
    filled = AddColumnStep(name="Status", value="To review")

    assert describe(blank) == 'Add an empty column called "Notes"'
    assert describe(filled) == 'Add a column called "Status" filled with "To review"'
    assert columns_of(filled) == ["Status"]
