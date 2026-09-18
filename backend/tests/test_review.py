"""Accepting, answering and turning down what a file's review found."""

from collections.abc import Iterator

import pytest

from app import review
from app.config import Settings
from app.detectors.models import Issue, Tier
from app.questions.models import Question
from app.steps.copy import describe
from app.store import DatasetSession, DatasetStore
from tests.conftest import SAMPLES_DIR

EMPLOYEE = (SAMPLES_DIR / "Messy_Employee_dataset.csv").read_bytes()


@pytest.fixture(scope="module")
def found() -> tuple[list[Issue], list[Question]]:
    """Detect and score once: every test here starts from the same findings."""
    store = DatasetStore(Settings())
    session = store.create("Messy_Employee_dataset.csv", EMPLOYEE)
    try:
        review.prepare(session)
        assert session.questions is not None
        return list(session.issues or []), list(session.questions)
    finally:
        store.close_all()


@pytest.fixture
def session(found: tuple[list[Issue], list[Question]]) -> Iterator[DatasetSession]:
    store = DatasetStore(Settings())
    fresh = store.create("Messy_Employee_dataset.csv", EMPLOYEE)
    # Each test gets its own recipe and decisions, over the same findings.
    fresh.issues, fresh.questions = list(found[0]), list(found[1])
    yield fresh
    store.close_all()


def issue_of(session: DatasetSession, tier: Tier) -> Issue:
    return next(issue for issue in review.issues_of(session) if issue.tier is tier)


def step_ids(session: DatasetSession) -> set[str]:
    return {step.id for step in session.recipe.steps}


def test_safe_fixes_are_applied_without_asking(session: DatasetSession) -> None:
    issues = review.issues_of(session)

    safe = [issue for issue in issues if issue.tier is Tier.SAFE]
    assert safe
    for issue in safe:
        assert review.state_of(session, issue).state == "applied"
        assert {step.id for step in issue.steps} <= step_ids(session)


def test_nothing_else_is_applied_on_its_own(session: DatasetSession) -> None:
    for issue in review.issues_of(session):
        if issue.tier is not Tier.SAFE:
            assert review.state_of(session, issue).state == "available"


def test_applying_the_safe_fixes_leaves_nothing_to_undo(session: DatasetSession) -> None:
    review.issues_of(session)

    assert session.history.past == ()
    assert review.undo(session) is False


def test_the_review_is_only_worked_out_once(session: DatasetSession) -> None:
    first = review.issues_of(session)

    assert review.issues_of(session) is first
    assert len(session.recipe.steps) == len(set(step_ids(session)))


def test_accepting_a_suggestion_adds_its_steps(session: DatasetSession) -> None:
    issue = issue_of(session, Tier.LIKELY)

    review.accept(session, issue.id)

    assert {step.id for step in issue.steps} <= step_ids(session)
    assert review.state_of(session, issue).state == "applied"
    assert session.step_origin[issue.steps[0].id] == issue.id


def test_answering_a_question_applies_that_choice(session: DatasetSession) -> None:
    issue = issue_of(session, Tier.ASK)
    assert issue.ask is not None
    choice = issue.ask.choices[0]

    review.accept(session, issue.id, choice.id)

    state = review.state_of(session, issue)
    assert (state.state, state.chosen_choice_id) == ("applied", choice.id)


def test_changing_an_answer_replaces_the_steps(session: DatasetSession) -> None:
    issue = issue_of(session, Tier.ASK)
    assert issue.ask is not None
    first, second = issue.ask.choices[0], issue.ask.choices[1]

    review.accept(session, issue.id, first.id)
    review.accept(session, issue.id, second.id)

    assert {step.id for step in first.steps}.isdisjoint(step_ids(session))
    assert {step.id for step in second.steps} <= step_ids(session)
    assert review.state_of(session, issue).chosen_choice_id == second.id


def test_turning_a_suggestion_down_removes_it_and_remembers(session: DatasetSession) -> None:
    issue = issue_of(session, Tier.LIKELY)
    review.accept(session, issue.id)

    review.reject(session, issue.id)

    assert {step.id for step in issue.steps}.isdisjoint(step_ids(session))
    assert review.state_of(session, issue).state == "rejected"


def test_accepting_after_turning_down_brings_it_back(session: DatasetSession) -> None:
    issue = issue_of(session, Tier.LIKELY)
    review.reject(session, issue.id)

    review.accept(session, issue.id)

    assert review.state_of(session, issue).state == "applied"


def test_a_question_needs_an_answer(session: DatasetSession) -> None:
    issue = issue_of(session, Tier.ASK)

    with pytest.raises(review.ChoiceRequiredError):
        review.accept(session, issue.id)


def test_an_answer_that_isnt_offered_is_refused(session: DatasetSession) -> None:
    issue = issue_of(session, Tier.ASK)

    with pytest.raises(review.ChoiceNotFoundError):
        review.accept(session, issue.id, "not-a-choice")


def test_an_unknown_suggestion_is_refused(session: DatasetSession) -> None:
    with pytest.raises(review.IssueNotFoundError):
        review.accept(session, "nope")


def test_steps_are_kept_in_the_order_they_have_to_run(session: DatasetSession) -> None:
    """Splitting a column has to happen before the steps that read what it made."""
    split = next(
        issue for issue in review.issues_of(session) if issue.detector.value == "combined_columns"
    )
    numbers = next(
        issue for issue in review.issues_of(session) if issue.detector.value == "numbers_as_text"
    )

    review.accept(session, split.id)

    types = [step.type for step in session.recipe.steps]
    assert types.index("split_column") < types.index(numbers.steps[0].type)


def test_undo_goes_back_one_decision(session: DatasetSession) -> None:
    issue = issue_of(session, Tier.LIKELY)
    before = step_ids(session)
    review.accept(session, issue.id)

    for _ in issue.steps:
        review.undo(session)

    assert step_ids(session) == before


def test_a_step_can_be_turned_off_and_on(session: DatasetSession) -> None:
    review.issues_of(session)
    step = session.recipe.steps[0]

    review.set_step_enabled(session, step.id, False)
    assert session.recipe.steps[0].enabled is False

    review.undo(session)
    assert session.recipe.steps[0].enabled is True


def test_every_step_in_the_recipe_can_be_described(session: DatasetSession) -> None:
    for issue in review.issues_of(session):
        if issue.tier is Tier.LIKELY:
            review.accept(session, issue.id)

    for step in session.recipe.steps:
        assert describe(step)
