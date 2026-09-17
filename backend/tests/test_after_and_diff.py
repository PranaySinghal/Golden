"""The after reading, answer diffs, and impact."""

from collections.abc import Callable

import pytest

from app.compare.after import AfterReading
from app.compare.before import BeforeReading
from app.compare.diff import MAX_SHOWN_GROUPS, diff_answers
from app.compare.evaluate import evaluate
from app.compare.impact import magnitude, rank, score
from app.questions.models import Answer, AnswerDiff, GroupValue, Question
from app.steps.apply import plan_recipe
from app.steps.models import (
    CastNumberStep,
    EqualsCondition,
    MapValuesStep,
    ParseDateStep,
    Recipe,
    SetAsideRowsStep,
    SplitColumnStep,
    Step,
    TrimStep,
    ValueMapping,
)
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]


def question(**spec: object) -> Question:
    return Question.model_validate({"label": "q", "prominence": 1, **spec})


def after_answer(ds: Dataset, q: Question, *steps: Step) -> Answer:
    result = ds.apply(*steps, lineage=False)
    return evaluate(ds.conn, q, AfterReading.cleaned_table(result.output_schema()))


def before_answer(ds: Dataset, q: Question) -> Answer:
    return evaluate(ds.conn, q, BeforeReading([c.name for c in ds.profile.columns]))


# --- after reading ----------------------------------------------------------------------------


def test_numbers_and_dates_read_directly_once_cast(make_dataset: MakeDataset) -> None:
    ds = make_dataset('amount,when\n"$1,000",15/03/2024\n$500,16/04/2024\n')
    total = question(measure="sum", column="amount")
    trend = question(measure="count", group_by="when", grain="month")

    assert not before_answer(ds, total).answerable
    steps = (CastNumberStep(column="amount"), ParseDateStep(column="when", formats=["%d/%m/%Y"]))
    assert after_answer(ds, total, *steps).value == 1500
    assert [g.key for g in after_answer(ds, trend, *steps).groups] == ["2024-03", "2024-04"]


def test_columns_left_as_text_use_the_before_rules(make_dataset: MakeDataset) -> None:
    ds = make_dataset('amount\n"$1,000"\n500\n')
    total = question(measure="sum", column="amount")

    assert after_answer(ds, total, TrimStep(columns=["amount"])).value == 500


def test_set_aside_rows_are_not_counted_after(make_dataset: MakeDataset) -> None:
    ds = make_dataset("status\nok\ntest\nok\n")

    count = after_answer(
        ds,
        question(measure="count"),
        SetAsideRowsStep(condition=EqualsCondition(column="status", value="test")),
    )

    assert count.value == 2


def test_a_dropped_column_is_unanswerable_after(make_dataset: MakeDataset) -> None:
    ds = make_dataset("pair\na-b\nc-d\n")
    q = question(measure="count_distinct", column="pair")

    answer = after_answer(
        ds, q, SplitColumnStep(column="pair", delimiter="-", into=["l", "r"], keep_original=False)
    )

    assert not answer.answerable


def test_reading_a_plan_matches_reading_the_cleaned_table(make_dataset: MakeDataset) -> None:
    ds = make_dataset('dept,amount\nSales,10\n"sales ",20\nHR,$30\n')
    steps: list[Step] = [
        MapValuesStep(
            column="dept",
            match="ignore_case_and_spaces",
            mappings=[ValueMapping(from_value="Sales", to_value="Sales")],
        ),
        CastNumberStep(column="amount"),
    ]
    q = question(measure="avg", column="amount", group_by="dept")

    from_table = after_answer(ds, q, *steps)
    from_plan = evaluate(
        ds.conn, q, AfterReading.from_plan(plan_recipe(Recipe(steps=steps), ds.base))
    )

    assert from_plan == from_table


# --- diffs ------------------------------------------------------------------------------------


def groups(*pairs: tuple[str | None, float, int]) -> list[GroupValue]:
    return [GroupValue(key=k, label=k, value=v, rows=r) for k, v, r in pairs]


def test_unchanged_scalar() -> None:
    q = question(measure="avg", column="x")
    diff = score(
        diff_answers(q, Answer(answerable=True, value=10), Answer(answerable=True, value=10))
    )

    assert (diff.changed, diff.magnitude, diff.impact) == (False, 0.0, 0.0)


def test_float_noise_is_not_a_change() -> None:
    q = question(measure="sum", column="x")
    before = Answer(answerable=True, value=84814436.17)
    after = Answer(answerable=True, value=84814436.16999996)

    assert not diff_answers(q, before, after).changed


def test_only_one_side_answerable_is_a_full_change() -> None:
    q = question(
        measure="sum",
        column="x",
    )
    diff = score(diff_answers(q, Answer(answerable=False), Answer(answerable=True, value=5)))

    assert (diff.changed, diff.magnitude, diff.change) == (True, 1.0, None)


def test_groups_that_appear_disappear_and_merge() -> None:
    q = question(measure="count", group_by="dept")
    before = Answer(
        answerable=True, groups=groups(("sales", 10, 10), ("sales ", 2, 2), ("hr", 5, 5))
    )
    after = Answer(
        answerable=True, groups=groups(("sales", 12, 12), ("hr", 5, 5), ("unknown", 1, 1))
    )

    by_key = {g.key: g for g in diff_answers(q, before, after).groups}

    assert (by_key["sales"].status, by_key["sales"].change) == ("changed", 2)
    assert by_key["hr"].status == "same"
    assert (by_key["sales "].status, by_key["sales "].after, by_key["sales "].merged_into) == (
        "disappeared",
        0.0,
        "sales",
    )
    assert (by_key["unknown"].status, by_key["unknown"].before) == ("appeared", 0.0)


def test_average_groups_that_appear_have_no_before_value() -> None:
    q = question(measure="avg", column="x", group_by="dept")
    before = Answer(answerable=True, groups=groups(("a", 10, 4)))
    after = Answer(answerable=True, groups=groups(("a", 10, 4), ("b", 20, 1)))

    b = next(g for g in diff_answers(q, before, after).groups if g.key == "b")

    assert (b.status, b.before, b.after) == ("appeared", None, 20)


def test_long_breakdowns_are_capped_with_an_other_line() -> None:
    q = question(measure="count", group_by="k")
    many = groups(*[(f"g{i}", float(100 - i), 100 - i) for i in range(30)])

    shown = diff_answers(
        q, Answer(answerable=True, groups=many), Answer(answerable=True, groups=many)
    ).groups

    assert len(shown) == MAX_SHOWN_GROUPS
    assert shown[-1].label == "All other groups"
    assert shown[-1].before == sum(100 - i for i in range(MAX_SHOWN_GROUPS - 1, 30))


def test_trends_stay_in_date_order() -> None:
    q = question(measure="count", group_by="d", grain="year")
    before = Answer(answerable=True, groups=groups(("2021", 5, 5), ("2020", 9, 9)))
    after = Answer(answerable=True, groups=groups(("2022", 1, 1), ("2020", 9, 9)))

    assert [g.key for g in diff_answers(q, before, after).groups] == ["2020", "2021", "2022"]


# --- impact -----------------------------------------------------------------------------------


def test_share_shift_magnitude() -> None:
    q = question(measure="count", group_by="k")
    before = Answer(answerable=True, groups=groups(("a", 50, 50), ("b", 50, 50)))
    after = Answer(answerable=True, groups=groups(("a", 75, 75), ("b", 25, 25)))

    assert magnitude(diff_answers(q, before, after)) == pytest.approx(0.25)


def test_same_shares_with_fewer_rows_is_no_shift() -> None:
    q = question(measure="count", group_by="k")
    before = Answer(answerable=True, groups=groups(("a", 50, 50), ("b", 50, 50)))
    after = Answer(answerable=True, groups=groups(("a", 40, 40), ("b", 40, 40)))

    assert magnitude(diff_answers(q, before, after)) == 0.0


def test_average_shift_is_weighted_by_rows() -> None:
    q = question(measure="avg", column="x", group_by="k")
    before = Answer(answerable=True, groups=groups(("a", 100, 90), ("b", 100, 10)))
    after = Answer(answerable=True, groups=groups(("a", 100, 90), ("b", 150, 10)))

    # Only b (10% of rows) moved, by 50%.
    assert magnitude(diff_answers(q, before, after)) == pytest.approx(0.05)


def test_impact_is_prominence_times_magnitude_and_capped() -> None:
    q = Question.model_validate({"measure": "avg", "column": "x", "label": "q", "prominence": 0.8})
    diff = score(
        diff_answers(q, Answer(answerable=True, value=10), Answer(answerable=True, value=40))
    )

    assert (diff.magnitude, diff.impact) == (1.0, 0.8)


def test_ranking_by_impact_then_prominence_then_order() -> None:
    def scored(label: str, prominence: float, before: float, after: float) -> AnswerDiff:
        q = Question.model_validate(
            {"measure": "avg", "column": label, "label": label, "prominence": prominence}
        )
        return score(
            diff_answers(
                q, Answer(answerable=True, value=before), Answer(answerable=True, value=after)
            )
        )

    diffs = [
        scored("small", 1.0, 100, 101),
        scored("unchanged_low", 0.4, 5, 5),
        scored("big", 0.6, 100, 150),
        scored("unchanged_high", 1.0, 5, 5),
    ]

    assert [d.question.label for d in rank(diffs)] == [
        "big",
        "small",
        "unchanged_high",
        "unchanged_low",
    ]
