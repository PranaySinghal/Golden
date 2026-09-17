"""remove_characters, clear_values, and the digits_fewer_than condition."""

from collections.abc import Callable

import pytest

from app.steps.apply import StepStatus
from app.steps.models import (
    CastNumberStep,
    ClearValuesStep,
    DigitsFewerThanCondition,
    NotMatchingCondition,
    OutsideRangeCondition,
    RemoveCharactersStep,
    RowIdsCondition,
    SetAsideRowsStep,
)
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]


@pytest.mark.parametrize(
    ("where", "expected"),
    [
        ("leading", ["1651623197", "+44 20", "5-5", None]),
        ("trailing", ["-1651623197", "+44 20", "-5-5", None]),
        ("anywhere", ["1651623197", "44 20", "55", None]),
    ],
)
def test_remove_characters(
    make_dataset: MakeDataset, where: str, expected: list[str | None]
) -> None:
    ds = make_dataset('id,phone\n1,-1651623197\n2,+44 20\n3,-5-5\n4,"--"\n')

    step = RemoveCharactersStep.model_validate(
        {"columns": ["phone"], "characters": "-+" if where == "anywhere" else "-", "where": where}
    )
    result = ds.apply(step)

    assert result.outcomes[0].status is StepStatus.APPLIED
    assert ds.column("phone") == expected


def test_remove_characters_treats_characters_as_data(make_dataset: MakeDataset) -> None:
    ds = make_dataset("v\n'%$1\n")

    ds.apply(RemoveCharactersStep(columns=["v"], characters="'%$", where="anywhere"))

    assert ds.column("v") == ["1"]


def test_clear_values_short_phones_keeps_the_row(make_dataset: MakeDataset) -> None:
    ds = make_dataset("id,phone\n1,1651623197\n2,165162\n3,\n4,(415) 555-0134\n")

    result = ds.apply(
        ClearValuesStep(
            column="phone", condition=DigitsFewerThanCondition(column="phone", count=10)
        )
    )

    assert ds.column("phone") == ["1651623197", None, None, "(415) 555-0134"]
    assert ds.row_ids() == [1, 2, 3, 4]
    assert result.outcomes[0].cells_changed == 1
    assert ds.changes()[0][3:] == ("165162", None, "cleared")


def test_clear_values_invalid_emails_and_out_of_range_numbers(make_dataset: MakeDataset) -> None:
    ds = make_dataset("email,age\na@x.com,30\nnope,250\n,40\n")

    ds.apply(
        ClearValuesStep(
            column="email", condition=NotMatchingCondition(column="email", pattern="email")
        ),
        CastNumberStep(column="age"),
        ClearValuesStep(column="age", condition=OutsideRangeCondition(column="age", max=120)),
    )

    assert ds.column("email") == ["a@x.com", None, None]
    assert ds.column("age") == [30.0, None, 40.0]


def test_clear_values_by_row_ids(make_dataset: MakeDataset) -> None:
    ds = make_dataset("v\na\nb\nc\n")

    ds.apply(ClearValuesStep(column="v", condition=RowIdsCondition(row_ids=[2])))

    assert ds.column("v") == ["a", None, "c"]


def test_clear_values_rule_must_check_the_same_column(make_dataset: MakeDataset) -> None:
    ds = make_dataset("a,b\nx,y\n")

    result = ds.apply(
        ClearValuesStep(column="a", condition=NotMatchingCondition(column="b", pattern="email"))
    )

    assert result.outcomes[0].status is StepStatus.BLOCKED
    assert "must check" in (result.outcomes[0].reason or "")


def test_set_aside_rows_with_too_few_digits(make_dataset: MakeDataset) -> None:
    ds = make_dataset("id,phone\n1,4155550134\n2,415555\n")

    ds.apply(SetAsideRowsStep(condition=DigitsFewerThanCondition(column="phone", count=10)))

    assert ds.row_ids() == [1]
    assert ds.set_aside()[0][2] == '"phone" has fewer than 10 digits.'
