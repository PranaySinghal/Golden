from collections.abc import Callable

import duckdb
import pytest
from pydantic import ValidationError

from app.questions.generate import MAX_QUESTIONS, generate_questions
from app.questions.models import DateGrain, Measure, Question
from tests.conftest import SAMPLES_DIR, Dataset, load

MakeDataset = Callable[..., Dataset]


@pytest.mark.parametrize(
    "spec",
    [
        {"measure": "sum"},
        {"measure": "count", "column": "a"},
        {"measure": "count_distinct"},
        {"measure": "count", "grain": "month"},
        {"measure": "count", "prominence": 2},
    ],
)
def test_invalid_questions_are_rejected(spec: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Question.model_validate({"label": "q", "prominence": 1, **spec})


def test_question_ids_depend_only_on_the_spec() -> None:
    a = Question(measure=Measure.AVG, column="x", label="one", prominence=0.8)
    b = Question(measure=Measure.AVG, column="x", label="two", prominence=0.2)
    c = Question(measure=Measure.SUM, column="x", label="one", prominence=0.8)

    assert a.id == b.id
    assert a.id != c.id


def sample(name: str, anonymize: bool = False) -> Dataset:
    data = (SAMPLES_DIR / f"{name}.csv").read_bytes()
    if anonymize:
        header, rest = data.split(b"\n", 1)
        width = len(header.split(b","))
        data = ",".join(f"col_{i + 1}" for i in range(width)).encode() + b"\n" + rest
    conn = duckdb.connect(":memory:")
    load(conn, data)
    return Dataset(conn)


def labels(ds: Dataset) -> list[str]:
    return [q.label for q in generate_questions(ds.conn, ds.profile)]


def test_employee_questions_in_priority_order() -> None:
    assert labels(sample("Messy_Employee_dataset")) == [
        "How many rows are there?",
        'How many different "Employee_ID" values are there?',
        'What\'s the average "Salary"?',
        'What\'s the total "Salary"?',
        'What\'s the average "Age"?',
        'What\'s the total "Age"?',
        'How many rows are there for each "First_Name"?',
        'How many rows are there for each "Last_Name"?',
        'How many rows are there for each "Status"?',
        'What\'s the average "Salary" for each "First_Name"?',
        'What\'s the average "Salary" for each "Last_Name"?',
        'How many rows are there each year, by "Join_Date"?',
        'What\'s the average "Salary" each year, by "Join_Date"?',
        'How many different "Email" values are there?',
        'How many different "Phone" values are there?',
        'How many rows are there for each "Performance_Score"?',
    ]


def test_questions_are_capped() -> None:
    ds = sample("Messy_Employee_dataset")

    assert len(generate_questions(ds.conn, ds.profile)) == MAX_QUESTIONS == 16
    assert len(generate_questions(ds.conn, ds.profile, limit=5)) == 5


def test_percentages_get_an_average_but_no_total() -> None:
    found = labels(sample("store_orders"))

    assert 'What\'s the average "Discount"?' in found
    assert 'What\'s the total "Discount"?' not in found


def test_short_date_ranges_are_monthly_and_long_ones_yearly() -> None:
    grains = {
        name: {q.grain for q in generate_questions(ds.conn, ds.profile) if q.grain}
        for name, ds in [
            ("orders", sample("store_orders")),
            ("employees", sample("Messy_Employee_dataset")),
        ]
    }

    assert grains == {"orders": {DateGrain.MONTH}, "employees": {DateGrain.YEAR}}


def test_ids_free_text_and_many_valued_columns_are_never_breakdowns() -> None:
    ds = sample("store_orders")
    group_columns = {q.group_by for q in generate_questions(ds.conn, ds.profile, limit=100)}

    assert "Order No" not in group_columns
    assert "Notes" not in group_columns
    assert "Customer" not in group_columns

    employees = sample("Messy_Employee_dataset")
    employee_groups = {
        q.group_by for q in generate_questions(employees.conn, employees.profile, limit=100)
    }
    assert "Department_Region" not in employee_groups  # 36 groups


def test_messy_spellings_still_get_a_breakdown() -> None:
    ds = sample("Messy_Employee_dataset_messier")

    assert 'How many rows are there for each "Status"?' in labels(ds)


def test_single_valued_categories_are_skipped(make_dataset: MakeDataset) -> None:
    ds = make_dataset("id,kind,amount\n" + "".join(f"{i},same,{i}\n" for i in range(20)))

    assert all(q.group_by != "kind" for q in generate_questions(ds.conn, ds.profile))


@pytest.mark.parametrize("name", ["Messy_Employee_dataset", "store_orders"])
def test_questions_do_not_depend_on_column_names(name: str) -> None:
    def shapes(ds: Dataset) -> list[tuple[str, bool, bool, str | None]]:
        return [
            (q.measure.value, q.column is not None, q.group_by is not None, q.grain)
            for q in generate_questions(ds.conn, ds.profile)
        ]

    # Order can shift where a column is only recognized by name (Phone becomes an ID).
    assert sorted(shapes(sample(name)), key=str) == sorted(
        shapes(sample(name, anonymize=True)), key=str
    )
