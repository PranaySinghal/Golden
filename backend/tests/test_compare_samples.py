"""Questions, answers, and issue impact on the samples, including the worked examples."""

import json
import time
from typing import Any

import duckdb
import pytest

from app.compare.after import AfterReading
from app.compare.before import BeforeReading
from app.compare.compare import compare
from app.compare.issue_impact import score_issues
from app.detectors.step_order import recipe_for
from app.questions.generate import generate_questions
from app.questions.models import AnswerDiff, Measure
from tests.conftest import GOLDEN_DIR, SAMPLES_DIR, Dataset, load

SAMPLES = ["Messy_Employee_dataset", "store_orders", "Messy_Employee_dataset_messier"]


def sample(name: str) -> Dataset:
    conn = duckdb.connect(":memory:")
    load(conn, (SAMPLES_DIR / f"{name}.csv").read_bytes())
    return Dataset(conn)


def run(ds: Dataset, answers: dict[str, str] | None = None) -> list[AnswerDiff]:
    questions = generate_questions(ds.conn, ds.profile)
    result = ds.apply_recipe(recipe_for(ds.issues(), answers=answers), lineage=False)
    before = BeforeReading([c.name for c in ds.profile.columns])
    after = AfterReading.cleaned_table(result.output_schema())
    return compare(ds.conn, questions, before, after, result.fingerprint)


def find(diffs: list[AnswerDiff], label: str) -> AnswerDiff:
    return next(d for d in diffs if d.question.label == label)


def test_average_salary_moves_only_when_na_means_zero() -> None:
    """Worked example 1."""
    ds = sample("Messy_Employee_dataset")
    issue = next(i for i in ds.issues() if i.detector.value == "placeholders")
    assert issue.ask is not None
    missing, zero = issue.ask.choices

    as_missing = find(run(ds, {issue.id: missing.id}), 'What\'s the average "Salary"?')
    as_zero = find(run(ds, {issue.id: zero.id}), 'What\'s the average "Salary"?')

    assert as_missing.before.value == pytest.approx(85155.06, abs=0.01)
    assert (as_missing.changed, as_missing.impact) == (False, 0.0)
    assert as_zero.after.value == pytest.approx(83151.41, abs=0.01)
    assert as_zero.change == pytest.approx(-2003.65, abs=0.01)
    assert as_zero.magnitude == pytest.approx(0.0235, abs=1e-4)
    assert as_zero.impact == pytest.approx(0.0188, abs=1e-4)


def test_row_count_on_the_messier_file() -> None:
    """Worked example 2."""
    rows = find(run(sample("Messy_Employee_dataset_messier")), "How many rows are there?")

    assert (rows.before.value, rows.after.value) == (1071, 1020)
    assert rows.impact == pytest.approx(51 / 1071, abs=1e-6)


def test_status_breakdown_on_the_messier_file() -> None:
    """Worked example 3: spelling variants fold into their groups."""
    status = find(
        run(sample("Messy_Employee_dataset_messier")), 'How many rows are there for each "Status"?'
    )

    by_label = {g.label: g for g in status.groups}
    assert (by_label["Pending"].before, by_label["Pending"].after) == (362, 356)
    folded = [g for g in status.groups if g.status == "disappeared"]
    assert folded
    assert {g.merged_into for g in folded} == {"Active", "Inactive", "Pending"}
    assert status.magnitude == pytest.approx(0.0532, abs=1e-4)
    assert status.impact == pytest.approx(0.6 * status.magnitude, abs=1e-6)


def test_day_first_dates_show_how_a_spreadsheet_misreads_them() -> None:
    trend = find(
        run(sample("store_orders")), 'How many rows are there each month, by "Order Date"?'
    )

    assert trend.changed
    assert trend.before.rows_skipped > 0
    assert trend.after.rows_skipped == 0


def test_nothing_accepted_means_nothing_changes() -> None:
    ds = sample("Messy_Employee_dataset")
    questions = generate_questions(ds.conn, ds.profile)
    result = ds.apply(lineage=False)

    diffs = compare(
        ds.conn,
        questions,
        BeforeReading([c.name for c in ds.profile.columns]),
        AfterReading.cleaned_table(result.output_schema()),
        result.fingerprint,
    )

    assert all(not d.changed and d.impact == 0 for d in diffs)


def test_answers_are_cached() -> None:
    ds = sample("store_orders")
    questions = generate_questions(ds.conn, ds.profile)
    result = ds.apply(lineage=False)
    before = BeforeReading([c.name for c in ds.profile.columns])
    after = AfterReading.cleaned_table(result.output_schema())
    cache: dict[tuple[str, str], Any] = {}

    first = compare(ds.conn, questions, before, after, result.fingerprint, cache)
    ds.conn.execute("DROP TABLE work.cleaned")  # a cache miss would now fail
    again = compare(ds.conn, questions, before, after, result.fingerprint, cache)

    assert again == first
    assert len(cache) == 2 * len(questions)


# --- issue impact -----------------------------------------------------------------------


def test_issue_impact_comes_from_answer_changes() -> None:
    ds = sample("Messy_Employee_dataset")
    questions = generate_questions(ds.conn, ds.profile)
    issues = ds.issues()

    scored = score_issues(ds.conn, ds.profile, issues, questions)

    salary = next(i for i in scored if i.detector.value == "placeholders")
    average_salary = next(q for q in questions if q.label == 'What\'s the average "Salary"?')
    assert salary.impact == pytest.approx(0.0188, abs=1e-4)
    assert average_salary.id in salary.moves_answers
    reading = next(i for i in scored if i.title == 'Read "Salary" as numbers')
    assert (reading.impact, reading.moves_answers) == (0.0, [])
    assert [i.impact for i in scored] == sorted((i.impact for i in scored), reverse=True)


def test_issue_scoring_leaves_the_cleaned_table_alone() -> None:
    ds = sample("store_orders")
    ds.apply(lineage=False)
    before = ds.cleaned()

    score_issues(ds.conn, ds.profile, ds.issues(), generate_questions(ds.conn, ds.profile))

    assert ds.cleaned() == before


# --- golden answers ----------------------------------------------------------------------


def summary(diffs: list[AnswerDiff]) -> list[dict[str, Any]]:
    def value(d: AnswerDiff, side: str) -> Any:
        answer = getattr(d, side)
        if d.question.group_by is None:
            return None if answer.value is None else round(answer.value, 4)
        return {
            str(g.key): round(g.value, 4) if g.value is not None else None for g in answer.groups
        }

    return [
        {
            "question": d.question.label,
            "before": value(d, "before"),
            "after": value(d, "after"),
            "changed": d.changed,
            "impact": round(d.impact, 4),
        }
        for d in diffs
    ]


@pytest.mark.parametrize("name", SAMPLES)
def test_answers_match_golden_file(name: str) -> None:
    expected = json.loads((GOLDEN_DIR / "answers" / f"{name}.json").read_text())

    assert summary(run(sample(name))) == expected


# --- scale -----------------------------------------------------------------------------------


def test_large_file_is_answered_in_sql(make_dataset: Any) -> None:
    rows = 300_000
    regions = ["North", "South", "east ", "West"]
    body = "".join(
        f"R{i},{regions[i % 4]},{(i % 997) * 1.5},{(i % 12) + 1}/{(i % 28) + 1}/2023\n"
        for i in range(rows)
    )
    ds = make_dataset("id,region,amount,when\n" + body)
    questions = generate_questions(ds.conn, ds.profile)
    assert any(q.measure is Measure.AVG for q in questions)

    started = time.monotonic()
    diffs = run(ds)
    elapsed = time.monotonic() - started

    assert len(diffs) == len(questions)
    assert all(len(d.before.groups) <= 1001 for d in diffs)
    assert elapsed < 60
