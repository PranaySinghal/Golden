"""The short version: what cleaning did to this file, in three or four sentences.

Every figure in a story comes from an answer the engine computed, and carries
the id of the card it came from — a story is built as parts, not as a string, so
a number can't appear in it without something to point at. That's what makes
"the story contains only numbers from computed diffs" a property of the type
rather than a promise.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.questions.models import AnswerDiff, Measure

MAX_SENTENCES = 4
# A breakdown has no single figure, so it can only be named, not quantified.
# One of those is context; three in a row is a story that says nothing.
MAX_BREAKDOWN_SENTENCES = 1
# Two new answers is a pleasant surprise; four in a row is a list.
MAX_UNLOCKED_SENTENCES = 2


class StoryPart(BaseModel):
    text: str
    # Set on figures: the answer this number came from, so the screen can point
    # at it. Plain words carry nothing.
    question_id: str | None = None


class StorySentence(BaseModel):
    parts: list[StoryPart] = Field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(part.text for part in self.parts)


class Story(BaseModel):
    sentences: list[StorySentence] = Field(default_factory=list)
    source: Literal["template", "ai"] = "template"
    # The cleaned rows this story describes. A story outlives the answers it was
    # written about — a model's especially, since it's fetched once — so the
    # screen has to be able to tell that its figures are the ones on the cards.
    recipe_key: str | None = None


def say_number(value: float | None, measure: Measure) -> str:
    """A figure as a person reads it. Mirrors how the cards show the same value."""
    if value is None:
        return "no answer"
    if measure in (Measure.COUNT, Measure.COUNT_DISTINCT) or value == int(value):
        return f"{round(value):,}"
    return f"{value:,.2f}"


def build_story(diffs: list[AnswerDiff], recipe_key: str | None = None) -> Story | None:
    """The story for a comparison, or None when there's nothing worth saying."""
    changed = [diff for diff in diffs if diff.changed and not diff.unlocked]
    unlocked = [diff for diff in diffs if diff.unlocked]
    if not changed and not unlocked:
        return None

    sentences: list[StorySentence] = []
    used: set[str] = set()
    room = MAX_SENTENCES - (1 if unlocked else 0)

    rows = _rows_sentence(changed)
    if rows is not None:
        sentences.append(rows.sentence)
        used.add(rows.question_id)

    # Answers with a figure say the most, so they come first whatever their rank.
    with_figures = [diff for diff in changed if _has_figures(diff)]
    without = [diff for diff in changed if not _has_figures(diff)]

    for diff in [*with_figures, *without[:MAX_BREAKDOWN_SENTENCES]]:
        if len(sentences) >= room:
            break
        if diff.question.id in used:
            continue
        moved = _moved_sentence(diff)
        if moved is not None:
            sentences.append(moved)
            used.add(diff.question.id)

    # An answer the file simply couldn't give before is worth the last line,
    # and worth its figure: that's the whole point of having cleaned it.
    # Figures first: "it comes to 20,686.29" says more than "now it can".
    telling = sorted(unlocked, key=lambda d: d.after.value is None)
    for position, diff in enumerate(telling[:MAX_UNLOCKED_SENTENCES]):
        if len(sentences) >= MAX_SENTENCES:
            break
        sentences.append(_unlocked_sentence(diff, first=position == 0))

    return Story(sentences=sentences, recipe_key=recipe_key) if sentences else None


def _has_figures(diff: AnswerDiff) -> bool:
    return diff.before.value is not None and diff.after.value is not None


class _Rows(BaseModel):
    sentence: StorySentence
    question_id: str


def _rows_sentence(changed: list[AnswerDiff]) -> _Rows | None:
    """How many rows the file has now, when that's what moved."""
    rows = next(
        (
            diff
            for diff in changed
            if diff.question.measure is Measure.COUNT and diff.question.group_by is None
        ),
        None,
    )
    if rows is None or rows.before.value is None or rows.after.value is None:
        return None
    measure = rows.question.measure
    sentence = StorySentence(
        parts=[
            StoryPart(text="Your file went from "),
            _figure(rows.before.value, measure, rows.question.id),
            StoryPart(text=" rows to "),
            _figure(rows.after.value, measure, rows.question.id),
            StoryPart(text=", once repeated and set-aside rows were taken out."),
        ]
    )
    return _Rows(sentence=sentence, question_id=rows.question.id)


def _moved_sentence(diff: AnswerDiff) -> StorySentence | None:
    """One answer that moved. Only answers with a single value carry figures."""
    label = diff.question.label.rstrip("?")
    if diff.before.answerable and not diff.after.answerable:
        return None
    if diff.before.value is None or diff.after.value is None:
        # A breakdown has no single number, so it's named without one.
        return StorySentence(
            parts=[StoryPart(text=f"“{label}?” came out differently, group by group.")]
        )
    measure = diff.question.measure
    return StorySentence(
        parts=[
            StoryPart(text=f"“{label}?” went from "),
            _figure(diff.before.value, measure, diff.question.id),
            StoryPart(text=" to "),
            _figure(diff.after.value, measure, diff.question.id),
            StoryPart(text="."),
        ]
    )


def _unlocked_sentence(diff: AnswerDiff, first: bool = True) -> StorySentence:
    label = diff.question.label.rstrip("?")
    opening = (
        f"Your file could not answer “{label}?” at all before"
        if first
        else f"Nor could it answer “{label}?”"
    )
    if diff.after.value is None:
        return StorySentence(parts=[StoryPart(text=f"{opening}. Now it can.")])
    return StorySentence(
        parts=[
            StoryPart(text=f"{opening}. It comes to "),
            _figure(diff.after.value, diff.question.measure, diff.question.id),
            StoryPart(text="."),
        ]
    )


def _figure(value: float, measure: Measure, question_id: str) -> StoryPart:
    return StoryPart(text=say_number(value, measure), question_id=question_id)
