"""Realistic recipes on both sample files, checked against expectations computed
independently in Python from the CSV text."""

import csv
import datetime as dt
from collections import Counter
from collections.abc import Callable

import pytest

from app.steps.apply import StepStatus
from app.steps.lineage import cell_history
from app.steps.models import (
    CastNumberStep,
    DedupeStep,
    MapValuesStep,
    NullPlaceholdersStep,
    ParseDateStep,
    SplitColumnStep,
    TrimStep,
    ValueMapping,
)
from tests.conftest import SAMPLES_DIR, Dataset

MakeDataset = Callable[..., Dataset]


def sample_rows(name: str) -> list[dict[str, str]]:
    with open(SAMPLES_DIR / f"{name}.csv", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_employee_recipe(make_dataset: MakeDataset) -> None:
    rows = sample_rows("Messy_Employee_dataset")
    ds = make_dataset((SAMPLES_DIR / "Messy_Employee_dataset.csv").read_bytes())

    result = ds.apply(
        NullPlaceholdersStep(columns=["Salary"], placeholders=["N/A"]),
        CastNumberStep(column="Salary"),
        SplitColumnStep(column="Department_Region", delimiter="-", into=["Department", "Region"]),
        ParseDateStep(column="Join_Date", formats=["%m/%d/%Y"]),
        DedupeStep(columns=["Employee_ID"]),
        CastNumberStep(column="Age"),
    )

    assert all(o.status is StepStatus.APPLIED for o in result.outcomes)
    placeholders, cast, split, dates, dedupe, age = result.outcomes
    salaries = [float(r["Salary"]) for r in rows if r["Salary"] != "N/A"]

    assert result.row_count == len(rows) == 1020
    assert placeholders.cells_changed == len(rows) - len(salaries) == 24
    assert (cast.cells_changed, cast.values_unreadable) == (0, 0)
    assert split.cells_changed == 2 * len(rows)
    assert (dates.cells_changed, dates.values_unreadable) == (len(rows), 0)
    assert dedupe.rows_set_aside == 0
    assert age.values_unreadable == 0

    cleaned_salaries = [float(v) for v in ds.column("Salary") if isinstance(v, float)]
    assert sum(cleaned_salaries) / len(cleaned_salaries) == pytest.approx(
        sum(salaries) / len(salaries)
    )
    assert Counter(ds.column("Department")) == Counter(
        r["Department_Region"].split("-")[0] for r in rows
    )
    assert ds.column("Join_Date")[0] == dt.date(2021, 4, 2)

    na_row = next(i for i, r in enumerate(rows, 1) if r["Salary"] == "N/A")
    history = cell_history(ds.conn, result, na_row, "Salary")
    assert history.original == "N/A"
    assert [(c.step_id, c.kind) for c in history.changes] == [(placeholders.step_id, "cleared")]


def test_orders_recipe(make_dataset: MakeDataset) -> None:
    rows = sample_rows("store_orders")
    ds = make_dataset((SAMPLES_DIR / "store_orders.csv").read_bytes())

    result = ds.apply(
        TrimStep(columns=["Product Category"]),
        MapValuesStep(
            column="Product Category",
            match="ignore_case_and_spaces",
            mappings=[
                ValueMapping(from_value="Home and Garden", to_value="Home & Garden"),
                ValueMapping(from_value="electronics", to_value="Electronics"),
                ValueMapping(from_value="books", to_value="Books"),
            ],
        ),
        CastNumberStep(column="Unit Price"),
        CastNumberStep(column="Discount", percent="fraction"),
        ParseDateStep(column="Order Date", formats=["%d/%m/%Y"]),
        MapValuesStep(
            column="Paid",
            match="ignore_case_and_spaces",
            mappings=[
                ValueMapping(from_value="yes", to_value="Yes"),
                ValueMapping(from_value="no", to_value="No"),
            ],
        ),
        DedupeStep(columns=["Order No"]),
    )

    assert all(o.status is StepStatus.APPLIED for o in result.outcomes)
    assert result.row_count == len(rows) == 64

    def category(value: str) -> str:
        key = " ".join(value.split()).lower()
        return {"home and garden": "Home & Garden"}.get(key, key.title().replace("And", "&"))

    assert Counter(ds.column("Product Category")) == Counter(
        category(r["Product Category"]) for r in rows
    )
    assert set(ds.column("Paid")) == {"Yes", "No"}

    prices = [
        float(r["Unit Price"].replace("$", "").replace(",", "")) for r in rows if r["Unit Price"]
    ]
    cleaned_prices = [float(v) for v in ds.column("Unit Price") if isinstance(v, float)]
    assert sum(cleaned_prices) == pytest.approx(sum(prices))
    assert result.outcomes[2].values_unreadable == 0

    discounts = [float(r["Discount"].rstrip("%")) / 100 for r in rows]
    assert ds.column("Discount") == pytest.approx(discounts)

    first_date = rows[0]["Order Date"]
    day, month, year = (int(part) for part in first_date.split("/"))
    assert ds.column("Order Date")[0] == dt.date(year, month, day)
