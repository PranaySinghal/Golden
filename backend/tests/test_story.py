"""The short version of a comparison: what it says, and what it refuses to say."""

import json

import pytest

from app.ai.schemas import StoryReply
from app.ai.story_wording import accepted_story, known_figures, story_facts
from app.questions.models import Answer, AnswerDiff, GroupDiff, Question
from app.story import MAX_SENTENCES, Story, build_story, say_number


def question(label: str, **spec: object) -> Question:
    return Question.model_validate({"label": label, "prominence": 1, "measure": "count", **spec})


def diff(
    label: str,
    before: float | None,
    after: float | None,
    *,
    measure: str = "count",
    changed: bool = True,
    unlocked: bool = False,
    impact: float = 0.5,
    groups: list[GroupDiff] | None = None,
    **spec: object,
) -> AnswerDiff:
    return AnswerDiff(
        question=question(label, measure=measure, **spec),
        before=Answer(answerable=before is not None, value=before),
        after=Answer(answerable=after is not None, value=after),
        changed=changed,
        impact=impact,
        unlocked=unlocked,
        groups=groups or [],
    )


ROWS = diff("How many rows are there?", 1071, 1020, impact=0.9)
PHONES = diff(
    'How many different "Phone" values are there?',
    1020,
    928,
    measure="count_distinct",
    column="Phone",
    impact=0.8,
)
SALARY = diff(
    'What\'s the average "Salary"?', 85155.06, 83151.41, measure="avg", column="Salary", impact=0.7
)
BREAKDOWN = diff(
    'What\'s the average "Salary" for each "First_Name"?',
    None,
    None,
    measure="avg",
    column="Salary",
    group_by="First_Name",
    impact=0.4,
)
NEW_TOTAL = diff(
    'What\'s the total "Unit Price"?',
    None,
    20686.29,
    measure="sum",
    column="Unit Price",
    unlocked=True,
    impact=0.8,
)
UNCHANGED = diff('What\'s the total "Age"?', 5, 5, measure="sum", column="Age", changed=False)
CROSS_TAB = diff(
    'What\'s the total "column_3"?',
    2214.0,
    8132.41,
    measure="sum",
    column="column_3",
    impact=0.6,
)


def figures(story: Story) -> list[str]:
    return [
        part.text for sentence in story.sentences for part in sentence.parts if part.question_id
    ]


def text(story: Story) -> str:
    return " ".join(sentence.text for sentence in story.sentences)


# --- what the story says --------------------------------------------------------------------


def test_a_story_is_built_from_the_answers_that_moved() -> None:
    story = build_story([ROWS, PHONES, SALARY])
    assert story is not None

    assert "1,071" in text(story)
    assert "83,151.41" in text(story)
    assert story.source == "template"


def test_every_figure_carries_the_answer_it_came_from() -> None:
    story = build_story([ROWS, PHONES, SALARY])
    assert story is not None

    known = {ROWS.question.id, PHONES.question.id, SALARY.question.id}
    for sentence in story.sentences:
        for part in sentence.parts:
            if part.question_id is not None:
                assert part.question_id in known


def test_the_story_holds_no_figure_that_isnt_an_answer() -> None:
    """Every number in the words has to be one of the parts that carries a link."""
    story = build_story([ROWS, PHONES, SALARY, BREAKDOWN, NEW_TOTAL])
    assert story is not None

    linked = set(figures(story))
    for sentence in story.sentences:
        for part in sentence.parts:
            if part.question_id is None:
                assert not any(character.isdigit() for character in part.text), part.text
            else:
                assert part.text in linked


def test_it_says_no_more_than_four_sentences() -> None:
    story = build_story([ROWS, PHONES, SALARY, BREAKDOWN, NEW_TOTAL])
    assert story is not None

    assert len(story.sentences) <= MAX_SENTENCES


def test_answers_with_a_figure_come_before_the_ones_without() -> None:
    story = build_story([BREAKDOWN, PHONES])
    assert story is not None

    assert "1,020" in story.sentences[0].text


def test_a_breakdown_is_named_without_pretending_to_a_single_number() -> None:
    story = build_story([BREAKDOWN])
    assert story is not None

    assert "group by group" in text(story)
    assert figures(story) == []


def test_an_answer_the_file_could_not_give_before_gets_its_figure() -> None:
    story = build_story([NEW_TOTAL])
    assert story is not None

    assert "could not answer" in text(story)
    assert "20,686.29" in figures(story)


def test_nothing_changed_means_nothing_to_say() -> None:
    assert build_story([UNCHANGED]) is None


def test_no_answers_at_all_means_nothing_to_say() -> None:
    assert build_story([]) is None


@pytest.mark.parametrize(
    ("value", "measure", "expected"),
    [
        (1020, "count", "1,020"),
        (928.0, "count_distinct", "928"),
        (83151.41, "avg", "83,151.41"),
        (20686.0, "sum", "20,686"),
        (None, "avg", "no answer"),
    ],
)
def test_figures_are_written_the_way_the_cards_write_them(
    value: float | None, measure: str, expected: str
) -> None:
    assert say_number(value, measure) == expected  # type: ignore[arg-type]


# --- a model's version ----------------------------------------------------------------------


DIFFS = [ROWS, PHONES, SALARY, NEW_TOTAL]


def reply(*sentences: str) -> StoryReply:
    return StoryReply.model_validate({"sentences": list(sentences)})


def test_the_figures_a_model_may_use_are_the_ones_we_computed() -> None:
    allowed = known_figures(DIFFS)

    assert allowed["1020"] == ROWS.question.id
    assert allowed["83151.41"] == SALARY.question.id
    assert "12" not in allowed


def test_the_facts_a_model_is_given_are_only_the_answers_that_moved() -> None:
    facts = story_facts([*DIFFS, UNCHANGED])

    written = json.dumps(facts)
    assert UNCHANGED.question.label not in written
    assert "83,151.41" in written


def test_a_model_story_that_uses_our_figures_is_accepted_and_linked() -> None:
    story = accepted_story(
        DIFFS,
        reply(
            "Your customer list went from 1,071 rows to 1,020.",
            "Average pay is now 83,151.41.",
        ),
    )
    assert story is not None

    assert story.source == "ai"
    linked = {
        part.text: part.question_id for s in story.sentences for part in s.parts if part.question_id
    }
    assert linked["1,071"] == ROWS.question.id
    assert linked["83,151.41"] == SALARY.question.id


def test_a_model_story_that_invents_a_figure_is_refused() -> None:
    story = accepted_story(DIFFS, reply("Your file lost about 12% of its rows."))

    assert story is None


def test_a_figure_that_belongs_to_no_answer_is_refused() -> None:
    """Right shape, wrong number: 1,021 was never an answer."""
    story = accepted_story(DIFFS, reply("Your file went from 1,071 rows to 1,021."))

    assert story is None


def test_a_model_story_that_reaches_for_jargon_is_refused() -> None:
    story = accepted_story(DIFFS, reply("We deduped the rows down to 1,020."))

    assert story is None


def test_a_model_story_dressed_up_as_markdown_is_refused() -> None:
    story = accepted_story(DIFFS, reply("**Your file** went from 1,071 to 1,020."))

    assert story is None


def test_one_bad_sentence_loses_the_whole_story() -> None:
    """A story is one piece of prose; half of it isn't worth showing."""
    story = accepted_story(
        DIFFS, reply("Your file went from 1,071 rows to 1,020.", "That's 12% fewer.")
    )

    assert story is None


def test_a_model_that_says_nothing_leaves_the_templates_alone() -> None:
    assert accepted_story(DIFFS, reply()) is None


def test_a_digit_in_a_column_name_is_not_a_figure() -> None:
    """Columns arrive called "column_3" or "2023 Sales". Naming one states nothing."""
    story = accepted_story(
        [CROSS_TAB], reply('“What\'s the total "column_3"?” went from 2,214 to 8,132.41.')
    )
    assert story is not None

    linked = {
        part.text: part.question_id for s in story.sentences for part in s.parts if part.question_id
    }
    assert set(linked) == {"2,214", "8,132.41"}


def test_a_digit_outside_a_column_name_is_still_checked() -> None:
    """The name is excused, not the sentence around it."""
    story = accepted_story([CROSS_TAB], reply('The total "column_3" went up by 5,918.'))

    assert story is None


def test_a_figure_from_an_answer_that_did_not_move_is_not_ours_to_use() -> None:
    """A model is only shown what changed, so anything else it cites is a coincidence."""
    allowed = known_figures([*DIFFS, UNCHANGED])
    assert "5" not in allowed

    assert accepted_story([*DIFFS, UNCHANGED], reply('"Age" still totals 5.')) is None
