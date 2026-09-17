"""Steps that change the shape of the table: split, dedupe, set aside rows."""

from collections.abc import Callable

import pytest

from app.steps.apply import StepStatus
from app.steps.models import (
    BlankCondition,
    CastNumberStep,
    DedupeStep,
    EqualsCondition,
    NotMatchingCondition,
    OneOfCondition,
    OutsideRangeCondition,
    ParseDateStep,
    RowCondition,
    RowIdsCondition,
    SetAsideRowsStep,
    SplitColumnStep,
)
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]

PEOPLE = (
    "name,email,dept,age\n"
    "Ann,ann@x.com,Sales-Texas,34\n"
    "Bo,BO@x.com ,HR-New York,\n"
    "ann,ann@x.com,Sales-Texas,34\n"
    "Cy,not-an-email,Cloud Tech-Florida-East,71\n"
    "Bo,bo@x.com,HR-New York,29\n"
)


# --- split_column -----------------------------------------------------------------------------


def test_split_column_places_new_columns_after_the_original(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    result = ds.apply(SplitColumnStep(column="dept", delimiter="-", into=["Department", "Region"]))

    assert [c.name for c in result.columns] == [
        "name",
        "email",
        "dept",
        "Department",
        "Region",
        "age",
    ]
    assert ds.column("Department") == ["Sales", "HR", "Sales", "Cloud Tech", "HR"]
    # The last column keeps the remainder, so "Florida-East" isn't lost.
    assert ds.column("Region") == ["Texas", "New York", "Texas", "Florida-East", "New York"]
    assert result.outcomes[0].cells_changed == 10
    assert {change[5] for change in ds.changes()} == {"created"}


def test_split_column_with_more_names_than_parts(make_dataset: MakeDataset) -> None:
    ds = make_dataset("code\nA-B\nC\n")

    ds.apply(SplitColumnStep(column="code", delimiter="-", into=["x", "y", "z"]))

    assert ds.column("x") == ["A", "C"]
    assert ds.column("y") == ["B", None]
    assert ds.column("z") == [None, None]


def test_split_column_can_drop_the_original(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    result = ds.apply(
        SplitColumnStep(column="dept", delimiter="-", into=["dept", "Region"], keep_original=False)
    )

    assert [c.name for c in result.columns] == ["name", "email", "dept", "Region", "age"]
    assert ds.column("dept")[0] == "Sales"


def test_split_column_without_trimming(make_dataset: MakeDataset) -> None:
    ds = make_dataset('v\n"a - b"\n')

    ds.apply(SplitColumnStep(column="v", delimiter="-", into=["l", "r"], trim_parts=False))

    assert (ds.column("l"), ds.column("r")) == (["a "], [" b"])


@pytest.mark.parametrize(
    ("into", "message"),
    [
        (["NAME", "x"], 'already a column called "NAME"'),
        (["x", "X"], "named twice"),
        (["_row_id", "x"], "reserved"),
    ],
)
def test_split_column_name_clashes_are_blocked(
    make_dataset: MakeDataset, into: list[str], message: str
) -> None:
    ds = make_dataset(PEOPLE)

    result = ds.apply(SplitColumnStep(column="dept", delimiter="-", into=into))

    assert result.outcomes[0].status is StepStatus.BLOCKED
    assert message in (result.outcomes[0].reason or "")


# --- dedupe -----------------------------------------------------------------------------------


def test_dedupe_exact_on_all_columns(make_dataset: MakeDataset) -> None:
    ds = make_dataset("a,b\n1,x\n1,x\n1,y\n1,x\n")

    result = ds.apply(DedupeStep())

    assert ds.row_ids() == [1, 3]
    assert result.set_aside_count == 2
    assert [(row[0], row[2]) for row in ds.set_aside()] == [
        (2, "Same values as an earlier row."),
        (4, "Same values as an earlier row."),
    ]


def test_dedupe_ignoring_case_and_spaces_on_chosen_columns(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    ds.apply(DedupeStep(columns=["email"], match="ignore_case_and_spaces"))

    assert ds.row_ids() == [1, 2, 4]
    assert ds.set_aside()[0][2] == 'Same "email" as an earlier row.'


def test_dedupe_exact_is_case_sensitive(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    ds.apply(DedupeStep(columns=["name"]))

    assert ds.row_ids() == [1, 2, 3, 4]


def test_dedupe_keep_last(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    ds.apply(DedupeStep(columns=["email"], match="ignore_case_and_spaces", keep="last"))

    assert ds.row_ids() == [3, 4, 5]
    assert "a later row" in str(ds.set_aside()[0][2])


def test_dedupe_treats_blanks_as_equal(make_dataset: MakeDataset) -> None:
    ds = make_dataset("k,v\n,1\n,2\nz,3\n")

    ds.apply(DedupeStep(columns=["k"]))

    assert ds.row_ids() == [1, 3]


def test_dedupe_keeps_rows_the_user_chose_to_keep(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    result = ds.apply(
        DedupeStep(columns=["email"], match="ignore_case_and_spaces", keep_row_ids=[5])
    )

    assert ds.row_ids() == [1, 2, 4, 5]
    assert result.set_aside_count == 1


# --- set_aside_rows ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("condition", "kept", "reason"),
    [
        (BlankCondition(column="age"), [1, 3, 4, 5], '"age" is blank.'),
        (EqualsCondition(column="name", value="Bo"), [1, 3, 4], '"name" is "Bo".'),
        (
            EqualsCondition(column="name", value="ANN", match="ignore_case_and_spaces"),
            [2, 4, 5],
            '"name" is "ANN".',
        ),
        (OneOfCondition(column="name", values=["Ann", "Cy"]), [2, 3, 5], "one of the listed"),
        (RowIdsCondition(row_ids=[2, 4]), [1, 3, 5], "Picked by hand."),
        (
            NotMatchingCondition(column="email", pattern="email"),
            [1, 2, 3, 5],
            "doesn't look like an email address",
        ),
    ],
)
def test_set_aside_rows_conditions(
    make_dataset: MakeDataset, condition: RowCondition, kept: list[int], reason: str
) -> None:
    ds = make_dataset(PEOPLE)

    result = ds.apply(SetAsideRowsStep(condition=condition))

    assert ds.row_ids() == kept
    assert result.set_aside_count == 5 - len(kept)
    assert all(reason in str(row[2]) for row in ds.set_aside())


@pytest.mark.parametrize(
    ("bounds", "kept", "reason"),
    [
        ({"min": 30}, [1, 2, 3, 4], "below 30"),
        ({"max": 70}, [1, 2, 3, 5], "above 70"),
        ({"min": 30, "max": 70}, [1, 2, 3], "outside 30 to 70"),
    ],
)
def test_set_aside_outside_range_keeps_blank_numbers(
    make_dataset: MakeDataset, bounds: dict[str, float], kept: list[int], reason: str
) -> None:
    ds = make_dataset(PEOPLE)

    ds.apply(
        CastNumberStep(column="age"),
        SetAsideRowsStep(condition=OutsideRangeCondition(column="age", **bounds)),
    )

    # Row 2 has no age, so it can't be outside the range and stays.
    assert ds.row_ids() == kept
    assert reason in str(ds.set_aside()[0][2])


def test_equals_on_number_and_date_columns(make_dataset: MakeDataset) -> None:
    ds = make_dataset("n,d\n5,2024-01-01\n6,2024-01-02\n")

    ds.apply(
        CastNumberStep(column="n"),
        ParseDateStep(column="d", formats=["%Y-%m-%d"]),
        SetAsideRowsStep(condition=EqualsCondition(column="n", value=5)),
        SetAsideRowsStep(condition=EqualsCondition(column="d", value="2024-01-02")),
    )

    assert ds.row_ids() == []
    assert [row[0] for row in ds.set_aside()] == [1, 2]


def test_number_column_compared_to_text_is_blocked(make_dataset: MakeDataset) -> None:
    ds = make_dataset("n\n5\n")

    result = ds.apply(
        CastNumberStep(column="n"),
        SetAsideRowsStep(condition=EqualsCondition(column="n", value="five")),
    )

    assert result.outcomes[1].status is StepStatus.BLOCKED


def test_set_aside_keep_row_ids(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    ds.apply(
        SetAsideRowsStep(condition=EqualsCondition(column="name", value="Bo"), keep_row_ids=[2])
    )

    assert ds.row_ids() == [1, 2, 3, 4]


def test_later_steps_only_see_rows_that_remain(make_dataset: MakeDataset) -> None:
    ds = make_dataset(PEOPLE)

    result = ds.apply(
        SetAsideRowsStep(condition=RowIdsCondition(row_ids=[1])),
        DedupeStep(columns=["email"], match="ignore_case_and_spaces"),
    )

    # Row 1 is gone before deduping, so row 3 is now the first "ann@x.com".
    assert ds.row_ids() == [2, 3, 4]
    assert [(row[0], row[1]) for row in ds.set_aside()] == [
        (1, result.outcomes[0].step_id),
        (5, result.outcomes[1].step_id),
    ]
    assert [o.rows_set_aside for o in result.outcomes] == [1, 1]


def test_hostile_column_names_work_in_every_row_step(make_dataset: MakeDataset) -> None:
    name = 'a"; DROP TABLE raw; --'
    ds = make_dataset(f'"{name.replace(chr(34), chr(34) * 2)}",other\nx-1,1\nx-1,2\n,3\n')

    result = ds.apply(
        SplitColumnStep(column=name, delimiter="-", into=["left", "right"]),
        DedupeStep(columns=[name]),
        SetAsideRowsStep(condition=BlankCondition(column=name)),
    )

    assert all(o.status is StepStatus.APPLIED for o in result.outcomes)
    assert ds.row_ids() == [1]
