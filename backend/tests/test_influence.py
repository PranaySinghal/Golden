"""Which steps could reach which questions. No queries, so no data is needed."""

from app.compare.influence import Influence, StepInfluence, influence_of
from app.questions.models import Question
from app.steps.apply import plan_recipe
from app.steps.models import (
    BlankCondition,
    CastNumberStep,
    DedupeStep,
    MapValuesStep,
    Recipe,
    SetAsideRowsStep,
    SplitColumnStep,
    Step,
    TrimStep,
    ValueMapping,
)
from app.steps.schema import StageSchema

COLUMNS = ["Name", "Email", "City", "Salary", "Department_Region"]


def influence(*steps: Step, columns: list[str] | None = None) -> Influence:
    plan = plan_recipe(Recipe(steps=list(steps)), StageSchema.all_text(columns or COLUMNS))
    return influence_of(plan)


def by_id(found: Influence) -> dict[str, StepInfluence]:
    return {step.step_id: step for step in found.steps}


def question(**spec: object) -> Question:
    return Question.model_validate({"label": "q", "prominence": 1, **spec})


ROWS = question(measure="count")
BY_CITY = question(measure="count", group_by="City")
AVERAGE_SALARY = question(measure="avg", column="Salary")


def test_a_step_influences_the_column_it_changes() -> None:
    trim = TrimStep(columns=["City"])

    found = by_id(influence(trim))[trim.id]

    assert (found.columns, found.every_question) == (frozenset({"City"}), False)
    assert influence(trim).relevant(BY_CITY) == [trim.id]
    assert influence(trim).relevant(AVERAGE_SALARY) == []


def test_a_row_count_is_only_reached_by_steps_that_remove_rows() -> None:
    trim = TrimStep(columns=["City"])
    cast = CastNumberStep(column="Salary")

    assert influence(trim, cast).relevant(ROWS) == []


def test_trimming_a_column_a_dedupe_compares_reaches_every_question() -> None:
    """A trim can decide which rows count as repeats, so it moves row counts."""
    trim = TrimStep(columns=["Email"])
    dedupe = DedupeStep(columns=["Email"])

    found = by_id(influence(trim, dedupe))

    assert found[trim.id].every_question
    assert found[dedupe.id].every_question
    assert influence(trim, dedupe).relevant(ROWS) == [trim.id, dedupe.id]


def test_a_dedupe_over_every_column_inherits_from_every_step() -> None:
    trim = TrimStep(columns=["City"])
    dedupe = DedupeStep()

    assert by_id(influence(trim, dedupe))[trim.id].every_question


def test_a_step_that_doesnt_feed_a_removal_stays_out_of_row_counts() -> None:
    cast = CastNumberStep(column="Salary")
    dedupe = DedupeStep(columns=["Email"])

    found = by_id(influence(cast, dedupe))

    assert not found[cast.id].every_question
    assert influence(cast, dedupe).relevant(ROWS) == [dedupe.id]


def test_a_split_influences_the_columns_it_creates() -> None:
    split = SplitColumnStep(column="Department_Region", delimiter="-", into=["Dept", "Region"])

    found = by_id(influence(split))[split.id]

    assert {"Dept", "Region"} <= found.columns
    assert influence(split).relevant(question(measure="count", group_by="Region")) == [split.id]


def test_influence_passes_through_a_created_column() -> None:
    split = SplitColumnStep(column="Department_Region", delimiter="-", into=["Dept", "Region"])
    trim = TrimStep(columns=["Region"])

    assert influence(split, trim).relevant(question(measure="count", group_by="Region")) == [
        split.id,
        trim.id,
    ]


def test_dropping_a_column_counts_as_changing_it() -> None:
    split = SplitColumnStep(
        column="Department_Region", delimiter="-", into=["Dept", "Region"], keep_original=False
    )

    assert "Department_Region" in by_id(influence(split))[split.id].columns


def test_a_step_feeding_a_set_aside_reaches_every_question() -> None:
    mapped = MapValuesStep(column="City", mappings=[ValueMapping(from_value="n/a", to_value=None)])
    aside = SetAsideRowsStep(condition=BlankCondition(column="City"))

    found = by_id(influence(mapped, aside))

    assert (found[mapped.id].every_question, found[aside.id].every_question) == (True, True)


def test_a_disabled_step_influences_nothing() -> None:
    trim = TrimStep(columns=["City"], enabled=False)

    assert influence(trim).steps == ()


def test_a_blocked_step_influences_nothing() -> None:
    """Reading a column that doesn't exist yet: the step never runs."""
    trim = TrimStep(columns=["Region"])
    split = SplitColumnStep(column="Department_Region", delimiter="-", into=["Dept", "Region"])

    found = influence(trim, split)

    assert [step.step_id for step in found.steps] == [split.id]


def test_questions_are_matched_against_changed_steps() -> None:
    trim = TrimStep(columns=["City"])
    cast = CastNumberStep(column="Salary")
    found = influence(trim, cast)

    assert found.touched_by(BY_CITY, {trim.id})
    assert not found.touched_by(BY_CITY, {cast.id})
