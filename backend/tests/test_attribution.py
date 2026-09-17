"""Known cases: which steps get the credit for a changed answer, and what it costs."""

from collections.abc import Callable

from app.compare.models import Comparison
from app.config import Settings
from app.questions.models import AnswerDiff, Question
from app.steps.models import (
    CastNumberStep,
    DedupeStep,
    EqualsCondition,
    MapValuesStep,
    NullPlaceholdersStep,
    Recipe,
    SetAsideRowsStep,
    SplitColumnStep,
    Step,
    TrimStep,
    ValueMapping,
)
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]

ROWS = Question.model_validate({"measure": "count", "label": "How many rows?", "prominence": 1})


def question(**spec: object) -> Question:
    return Question.model_validate({"label": "q", "prominence": 1, **spec})


def run(
    ds: Dataset, questions: list[Question], *steps: Step, settings: Settings | None = None
) -> Comparison:
    return ds.engine(questions=questions, settings=settings).compare(Recipe(steps=list(steps)))


def only(comparison: Comparison) -> AnswerDiff:
    return comparison.diffs[0]


def groups(diff: AnswerDiff) -> list[list[str]]:
    return [contribution.step_ids for contribution in diff.attribution_detail]


# --- who moved the answer -----------------------------------------------------------------


def test_setting_aside_repeats_is_credited_with_the_row_count(make_dataset: MakeDataset) -> None:
    ds = make_dataset("Name,City\nAnn,Paris\nAnn,Paris\nBo,Rome\n")
    trim, dedupe = TrimStep(columns=["City"]), DedupeStep()

    diff = only(run(ds, [ROWS], trim, dedupe))

    assert (diff.before.value, diff.after.value) == (3.0, 2.0)
    assert (diff.attribution, diff.attribution_method) == ([dedupe.id], "exact")
    # Without the step the answer is 3 rather than 2: a third of the way back.
    assert diff.attribution_detail[0].contribution == 0.333333


def test_reading_a_column_as_numbers_isnt_credited_when_it_changes_nothing(
    make_dataset: MakeDataset,
) -> None:
    """Treating "N/A" as zero moves the average; reading "0" as a number doesn't."""
    ds = make_dataset("Salary\n100\n200\nN/A\n")
    zero = MapValuesStep(column="Salary", mappings=[ValueMapping(from_value="N/A", to_value="0")])
    cast = CastNumberStep(column="Salary")

    diff = only(run(ds, [question(measure="avg", column="Salary")], zero, cast))

    assert (diff.before.value, diff.after.value) == (150.0, 100.0)
    assert diff.attribution == [zero.id]


def test_an_answer_that_didnt_move_gets_no_attribution(make_dataset: MakeDataset) -> None:
    ds = make_dataset("Salary\n100\n200\nN/A\n")
    missing = NullPlaceholdersStep(columns=["Salary"], placeholders=["N/A"])
    cast = CastNumberStep(column="Salary")

    diff = only(run(ds, [question(measure="avg", column="Salary")], missing, cast))

    assert (diff.changed, diff.before.value, diff.after.value) == (False, 150.0, 150.0)
    assert (diff.attribution, diff.attribution_detail) == ([], [])
    assert diff.attribution_method == "none"


def test_steps_that_only_matter_together_are_reported_together(
    make_dataset: MakeDataset,
) -> None:
    """Trimming and merging spellings both fold "Active " into "Active"."""
    ds = make_dataset("Status\nActive\nActive\nActive \nPaused\n")
    trim = TrimStep(columns=["Status"])
    merge = MapValuesStep(
        column="Status",
        mappings=[ValueMapping(from_value="Active", to_value="Active")],
        match="ignore_case_and_spaces",
    )

    diff = only(run(ds, [question(measure="count", group_by="Status")], trim, merge))

    assert (len(diff.before.groups), len(diff.after.groups)) == (3, 2)
    assert groups(diff) == [[trim.id, merge.id]]
    assert diff.attribution_detail[0].together
    assert diff.attribution == [trim.id, merge.id]
    assert diff.attribution_method == "exact"


def test_a_step_is_credited_through_the_step_that_needed_it(make_dataset: MakeDataset) -> None:
    """Without the split, setting aside rows by "Region" can't run either."""
    ds = make_dataset("Dept_Region\nSales-North\nSales-South\nHR-North\n")
    split = SplitColumnStep(column="Dept_Region", delimiter="-", into=["Dept", "Region"])
    aside = SetAsideRowsStep(condition=EqualsCondition(column="Region", value="South"))

    diff = only(run(ds, [ROWS], split, aside))

    assert (diff.before.value, diff.after.value) == (3.0, 2.0)
    assert sorted(diff.attribution) == sorted([split.id, aside.id])
    assert groups(diff) == [[split.id], [aside.id]] or groups(diff) == [[aside.id], [split.id]]


def test_a_step_that_changes_nothing_is_never_credited(make_dataset: MakeDataset) -> None:
    ds = make_dataset("Name,City\nAnn,Paris\nAnn,Paris\nBo,Rome\n")
    idle = TrimStep(columns=["Name"])  # no stray spaces to trim
    dedupe = DedupeStep()

    diff = only(run(ds, [ROWS], idle, dedupe))

    assert idle.id not in diff.attribution


def test_bigger_contributions_come_first(make_dataset: MakeDataset) -> None:
    ds = make_dataset("City\nParis\nParis\nParis\nRome\nLyon\n")
    drop_lyon = SetAsideRowsStep(condition=EqualsCondition(column="City", value="Lyon"))
    dedupe = DedupeStep(columns=["City"])

    diff = only(run(ds, [ROWS], drop_lyon, dedupe))

    assert diff.attribution == [dedupe.id, drop_lyon.id]
    first, second = diff.attribution_detail
    assert first.contribution > second.contribution
    assert diff.attribution == [step for group in groups(diff) for step in group]


def test_an_unlocked_answer_is_credited_to_the_step_that_made_it_possible(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset('Price\n"$1,200.00"\n"$300.00"\n')
    cast = CastNumberStep(column="Price")

    diff = only(run(ds, [question(measure="sum", column="Price")], cast))

    assert (diff.before.answerable, diff.after.value) == (False, 1500.0)
    assert (diff.unlocked, diff.attribution) == (True, [cast.id])


# --- cost ---------------------------------------------------------------------------------


def test_an_empty_recipe_leaves_every_answer_where_it_was(make_dataset: MakeDataset) -> None:
    ds = make_dataset("City,Salary\nParis, 100 \nRome,N/A\nParis,300\n")
    questions = [
        ROWS,
        question(measure="avg", column="Salary"),
        question(measure="count", group_by="City"),
    ]

    comparison = run(ds, questions)

    assert [d.changed for d in comparison.diffs] == [False, False, False]
    assert all(d.attribution_method == "none" for d in comparison.diffs)


def test_the_same_recipe_twice_costs_nothing_the_second_time(make_dataset: MakeDataset) -> None:
    ds = make_dataset("Name,City\nAnn,Paris\nAnn,Paris\nBo,Rome\n")
    engine = ds.engine(questions=[ROWS])
    recipe = Recipe(steps=[TrimStep(columns=["City"]), DedupeStep()])

    first = engine.compare(recipe)
    again = engine.compare(recipe)

    assert first.evaluations > 0
    assert (again.evaluations, again.recomputed) == (0, [])
    assert [d.attribution for d in again.diffs] == [d.attribution for d in first.diffs]


def test_the_same_steps_under_new_ids_reuse_cached_answers(make_dataset: MakeDataset) -> None:
    """Answers are keyed by what the steps do, not by which step objects did it."""
    ds = make_dataset("Name,City\nAnn,Paris\nAnn,Paris\nBo,Rome\n")
    engine = ds.engine(questions=[ROWS])

    engine.compare(Recipe(steps=[TrimStep(columns=["City"]), DedupeStep()]))
    again = engine.compare(Recipe(steps=[TrimStep(columns=["City"]), DedupeStep()]))

    assert again.evaluations == 0


def test_a_disabled_step_answers_like_a_step_that_was_never_added(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset("Name,City\nAnn,Paris\nAnn,Paris\nBo,Rome\n")
    engine = ds.engine(questions=[ROWS])

    engine.compare(Recipe(steps=[DedupeStep()]))
    off = engine.compare(Recipe(steps=[DedupeStep(), TrimStep(columns=["City"], enabled=False)]))

    assert off.evaluations == 0


def test_a_small_budget_estimates_instead_of_re_running(make_dataset: MakeDataset) -> None:
    ds = make_dataset("City\nParis\nParis\nParis\nRome\nLyon\n")
    drop_lyon = SetAsideRowsStep(condition=EqualsCondition(column="City", value="Lyon"))
    dedupe = DedupeStep(columns=["City"])
    questions = [ROWS, question(measure="count", group_by="City", prominence=0.6)]

    exact = run(ds, questions, drop_lyon, dedupe)
    tight = run(ds, questions, drop_lyon, dedupe, settings=Settings(max_attribution_queries=2))

    methods = {d.question.id: d.attribution_method for d in tight.diffs}
    assert sorted(methods.values()) == ["estimated", "exact"]
    # The estimate names everything that could have mattered, so it can't miss
    # the steps the exact answer found.
    for diff in tight.diffs:
        found = next(d for d in exact.diffs if d.question.id == diff.question.id)
        assert set(found.attribution) <= set(diff.attribution)


def test_no_budget_at_all_still_explains_what_could_have_mattered(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset("Name,City\nAnn,Paris\nAnn,Paris\nBo,Rome\n")
    dedupe = DedupeStep()

    comparison = run(ds, [ROWS], dedupe, settings=Settings(max_attribution_queries=0))
    diff = only(comparison)

    assert (diff.attribution, diff.attribution_method) == ([dedupe.id], "estimated")


def test_attribution_stays_within_steps_times_questions(make_dataset: MakeDataset) -> None:
    ds = make_dataset("City,Salary\nParis, 100 \nRome,N/A\nParis,300\nParis,300\n")
    steps: list[Step] = [
        TrimStep(columns=["City", "Salary"]),
        MapValuesStep(column="Salary", mappings=[ValueMapping(from_value="N/A", to_value="0")]),
        CastNumberStep(column="Salary"),
        DedupeStep(),
    ]
    questions = [
        ROWS,
        question(measure="avg", column="Salary"),
        question(measure="count", group_by="City"),
    ]

    comparison = run(ds, questions, *steps)

    # Two answers per question (before and after), plus at most one per step and
    # question for the re-runs, plus the joint and pair checks.
    assert comparison.evaluations <= 2 * len(questions) + len(steps) * len(questions) * 2
