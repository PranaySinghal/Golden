"""The one-sentence description of what each row holds, shown after upload."""

import re
from collections.abc import Callable

import pytest

from app.profile.describe import describe_rows
from tests.conftest import SAMPLES, Dataset, open_sample

MakeDataset = Callable[..., Dataset]

# Everything the sentence may say besides the ID column's own name. If a column
# name ever leaked in ("Salary", "Order"), it would fall outside this list.
VOCABULARY = {
    "each", "row", "has", "an", "a", "and", "id", "ids", "date", "dates", "number",
    "numbers", "category", "categories", "contact", "info", "kinds", "of", "some",
    "text", "columns", "empty", "column", "every", "in", "this", "file", "is",
}  # fmt: skip


def words_outside_the_id(sentence: str) -> set[str]:
    without_id = re.sub(r"“[^”]*”", "", sentence)
    return set(re.findall(r"[a-z]+", without_id.lower())) - VOCABULARY


@pytest.mark.parametrize("name", SAMPLES)
def test_every_sample_is_described_in_our_own_words(name: str) -> None:
    sentence = describe_rows(open_sample(name).profile)

    assert sentence.startswith("Each row has ")
    assert words_outside_the_id(sentence) == set()


def test_the_employee_file() -> None:
    sentence = describe_rows(open_sample("Messy_Employee_dataset").profile)

    assert sentence == (
        "Each row has an ID (“Employee_ID”), a date, 2 numbers, 6 categories "
        "and 2 kinds of contact info."
    )


def test_a_differently_shaped_file_reads_differently() -> None:
    orders = describe_rows(open_sample("store_orders").profile)
    employees = describe_rows(open_sample("Messy_Employee_dataset").profile)

    assert orders != employees
    assert "text columns" in orders


def test_a_file_without_an_id(make_dataset: MakeDataset) -> None:
    ds = make_dataset("team,amount\nSales,10\nOps,20\nSales,30\nOps,40\n")

    assert describe_rows(ds.profile) == "Each row has a number and a category."


def test_one_column(make_dataset: MakeDataset) -> None:
    ds = make_dataset("note\nhello there\nsomething else entirely\nand a third\n")

    assert words_outside_the_id(describe_rows(ds.profile)) == set()
    assert describe_rows(ds.profile).count(",") == 0


def test_an_empty_column_is_named_as_empty(make_dataset: MakeDataset) -> None:
    ds = make_dataset("team,blank\nSales,\nOps,\nSales,\n")

    assert describe_rows(ds.profile).endswith("and an empty column.")


def test_a_file_of_only_empty_columns(make_dataset: MakeDataset) -> None:
    ds = make_dataset("a,b\n,\n,\n")

    assert describe_rows(ds.profile) == "Every column in this file is empty."
