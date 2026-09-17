import csv
import io
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from app.steps.errors import RecipeFileError, RecipeIncompatibleError
from app.steps.export import (
    build_recipe_file,
    cleaned_csv_bytes,
    guard_formula,
    recipe_file_bytes,
)
from app.steps.models import (
    CastNumberStep,
    DedupeStep,
    EqualsCondition,
    NullPlaceholdersStep,
    ParseDateStep,
    Recipe,
    SetAsideRowsStep,
    SplitColumnStep,
    TrimStep,
)
from app.steps.replay import (
    check_compatibility,
    load_recipe_file,
    replay_recipe,
    required_columns,
)
from tests.conftest import SAMPLES_DIR, Dataset, load

MakeDataset = Callable[..., Dataset]
EMPLOYEE = (SAMPLES_DIR / "Messy_Employee_dataset.csv").read_bytes()
ORDERS = (SAMPLES_DIR / "store_orders.csv").read_bytes()


def employee_recipe() -> Recipe:
    return Recipe(
        steps=[
            NullPlaceholdersStep(columns=["Salary"], placeholders=["N/A"]),
            CastNumberStep(column="Salary"),
            SplitColumnStep(
                column="Department_Region", delimiter="-", into=["Department", "Region"]
            ),
            TrimStep(columns=["Region"]),  # reads a created column, so it isn't required
            ParseDateStep(column="Join_Date", formats=["%m/%d/%Y"]),
            DedupeStep(columns=["Email"], match="ignore_case_and_spaces"),
            TrimStep(columns=["Phone"], enabled=False),  # disabled, so not required
        ]
    )


def shuffled_with_extra_column(data: bytes) -> bytes:
    rows = list(csv.reader(io.StringIO(data.decode())))
    order = list(reversed(range(len(rows[0]))))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for number, row in enumerate(rows):
        writer.writerow([row[i] for i in order] + (["Notes"] if number == 0 else ["x"]))
    return out.getvalue().encode()


# --- required columns and compatibility -------------------------------------------------------


def test_required_columns_skip_created_and_disabled(make_dataset: MakeDataset) -> None:
    ds = make_dataset(EMPLOYEE)

    assert required_columns(employee_recipe(), ds.base) == [
        "Salary",
        "Department_Region",
        "Join_Date",
        "Email",
    ]


def test_recipe_replays_on_a_compatible_file_with_identical_results(
    make_dataset: MakeDataset,
) -> None:
    original = make_dataset(EMPLOYEE)
    recipe_file = build_recipe_file(employee_recipe(), original.base, "employees.csv")
    first = original.apply_recipe(recipe_file.recipe)

    other = make_dataset(shuffled_with_extra_column(EMPLOYEE))
    compatibility = check_compatibility(recipe_file, other.profile)
    assert compatibility.compatible, compatibility.problems
    replayed = replay_recipe(other.conn, recipe_file, other.profile)

    assert replayed.row_count == first.row_count
    assert replayed.set_aside_count == first.set_aside_count
    for name in ["Salary", "Department", "Region", "Join_Date", "Email"]:
        assert other.column(name) == original.column(name)


def test_recipe_fails_on_an_incompatible_file_and_lists_every_missing_column(
    make_dataset: MakeDataset,
) -> None:
    original = make_dataset(EMPLOYEE)
    recipe_file = build_recipe_file(employee_recipe(), original.base, "employees.csv")
    orders = make_dataset(ORDERS)

    compatibility = check_compatibility(recipe_file, orders.profile)

    assert not compatibility.compatible
    assert len(compatibility.problems) == 4
    assert all("needs a column called" in problem for problem in compatibility.problems)
    with pytest.raises(RecipeIncompatibleError) as excinfo:
        replay_recipe(orders.conn, recipe_file, orders.profile)
    assert excinfo.value.problems == compatibility.problems
    # Nothing was built for the incompatible file.
    tables = orders.conn.execute(
        "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'work'"
    )
    assert tables.fetchall() == []


def test_similar_column_names_are_suggested(make_dataset: MakeDataset) -> None:
    original = make_dataset("Join Date,Amount\n2024-01-01,5\n")
    recipe_file = build_recipe_file(
        Recipe(steps=[CastNumberStep(column="Amount")]), original.base, "a.csv"
    )
    renamed = make_dataset("join_date,amount \n2024-01-01,5\n")

    problems = check_compatibility(recipe_file, renamed.profile).problems

    assert problems == [
        'This recipe needs a column called "Amount", but this file doesn\'t have one. '
        'It has "amount", which might be the same column.'
    ]


def test_new_column_name_clash_makes_a_recipe_incompatible(make_dataset: MakeDataset) -> None:
    original = make_dataset("region\nNorth-East\n")
    recipe_file = build_recipe_file(
        Recipe(steps=[SplitColumnStep(column="region", delimiter="-", into=["area", "side"])]),
        original.base,
        "a.csv",
    )
    clashing = make_dataset("region,side\nNorth-East,left\n")

    compatibility = check_compatibility(recipe_file, clashing.profile)

    assert not compatibility.compatible
    assert compatibility.problems[0].startswith('Step 1 ("Split a column") can\'t run')


def test_kind_mismatch_is_a_warning_not_a_failure(make_dataset: MakeDataset) -> None:
    original = make_dataset("amount\n5\n6\n7\n")
    recipe_file = build_recipe_file(
        Recipe(steps=[CastNumberStep(column="amount")]), original.base, "a.csv"
    )
    wordy = make_dataset("amount\nfive\nsix\nseven\neight\n")

    compatibility = check_compatibility(recipe_file, wordy.profile)

    assert compatibility.compatible
    assert compatibility.warnings == [
        '"amount" doesn\'t look mostly like numbers in this file, so many values may end up blank.'
    ]


# --- recipe file ------------------------------------------------------------------------------


def test_recipe_file_round_trips(make_dataset: MakeDataset) -> None:
    ds = make_dataset(EMPLOYEE)
    created = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    recipe_file = build_recipe_file(employee_recipe(), ds.base, "employees.csv", now=created)

    data = recipe_file_bytes(recipe_file)
    loaded = load_recipe_file(data)

    assert loaded == recipe_file
    parsed = json.loads(data)
    assert parsed["format"] == "tidylab.recipe"
    assert parsed["source"]["filename"] == "employees.csv"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"not json {", "isn't a recipe file"),
        (b"\xff\xfe", "isn't a recipe file"),
        (b"[]", "isn't a TidyLab recipe"),
        (json.dumps({"format": "other"}).encode(), "isn't a TidyLab recipe"),
        (json.dumps({"format": "tidylab.recipe", "version": 2}).encode(), "different version"),
    ],
)
def test_unreadable_recipe_files(data: bytes, message: str) -> None:
    with pytest.raises(RecipeFileError, match=message):
        load_recipe_file(data)


def test_hand_edited_invalid_step_is_explained(make_dataset: MakeDataset) -> None:
    ds = make_dataset(EMPLOYEE)
    recipe_file = build_recipe_file(employee_recipe(), ds.base, "employees.csv")
    parsed = json.loads(recipe_file_bytes(recipe_file))
    del parsed["recipe"]["steps"][2]["delimiter"]

    with pytest.raises(RecipeFileError) as excinfo:
        load_recipe_file(json.dumps(parsed).encode())

    assert "step 3" in excinfo.value.message
    assert "delimiter" in excinfo.value.message


# --- cleaned CSV ------------------------------------------------------------------------------


def exported_rows(ds: Dataset, tmp_path: Path) -> list[list[str]]:
    assert ds.result is not None
    data = cleaned_csv_bytes(ds.conn, ds.result, tmp_path)
    assert data.startswith("﻿".encode())
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


def test_csv_export_formats_values_for_people(make_dataset: MakeDataset, tmp_path: Path) -> None:
    ds = make_dataset("id,amount,joined,city\n1,85000,4/2/2021,Zürich\n2,12.5,,\n3,N/A,1/1/2020,\n")
    ds.apply(
        NullPlaceholdersStep(columns=["amount"], placeholders=["N/A"]),
        CastNumberStep(column="amount"),
        ParseDateStep(column="joined", formats=["%m/%d/%Y"]),
    )

    rows = exported_rows(ds, tmp_path)

    assert rows == [
        ["id", "amount", "joined", "city"],
        ["1", "85000", "2021-04-02", "Zürich"],
        ["2", "12.5", "", ""],
        ["3", "", "2020-01-01", ""],
    ]
    assert list(tmp_path.iterdir()) == []


def test_csv_export_leaves_out_set_aside_rows(make_dataset: MakeDataset, tmp_path: Path) -> None:
    ds = make_dataset("id,status\n1,ok\n2,test\n3,ok\n")
    ds.apply(SetAsideRowsStep(condition=EqualsCondition(column="status", value="test")))

    assert [row[0] for row in exported_rows(ds, tmp_path)] == ["id", "1", "3"]


def test_csv_export_neutralizes_formulas(make_dataset: MakeDataset, tmp_path: Path) -> None:
    ds = make_dataset('"=HEADER()",note\n"=SUM(A1:A9)",-5\n"+1+1","@cmd"\n"-2.5","- dash"\n')
    ds.apply()

    rows = exported_rows(ds, tmp_path)

    assert rows == [
        ["'=HEADER()", "note"],
        ["'=SUM(A1:A9)", "-5"],
        ["'+1+1", "'@cmd"],
        ["-2.5", "'- dash"],
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("=1+1", "'=1+1"), ("-5", "-5"), ("+3.5", "+3.5"), ("@x", "'@x"), ("plain", "plain")],
)
def test_guard_formula(text: str, expected: str) -> None:
    assert guard_formula(text) == expected


def test_exported_csv_reads_back_through_ingest(make_dataset: MakeDataset, tmp_path: Path) -> None:
    ds = make_dataset(EMPLOYEE)
    ds.apply_recipe(employee_recipe())
    assert ds.result is not None
    data = cleaned_csv_bytes(ds.conn, ds.result, tmp_path)

    conn = duckdb.connect(":memory:")
    try:
        result = load(conn, data, filename="cleaned.csv")
    finally:
        conn.close()

    assert result.row_count == ds.result.row_count
    assert result.columns == [c.name for c in ds.result.columns]
