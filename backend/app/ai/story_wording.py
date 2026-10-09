"""Accepting a model's version of the story, on one condition.

The story is the one place the app speaks in whole sentences, so it's the most
tempting place to invent a figure. The rule is stricter than for other wording:
every number in an AI story has to be a value the engine computed, and it's
matched back to the answer it came from — which is both the check and the link.
Anything that doesn't match rejects the whole story, and the templates stand.
"""

import logging
import re

from app.ai.schemas import StoryReply
from app.ai.wording import MARKDOWN, uses_jargon
from app.questions.models import AnswerDiff
from app.story import Story, StoryPart, StorySentence, say_number

logger = logging.getLogger("tidylab.ai")

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Curly and straight quotes are the same character to a reader, and a model
# picks whichever it likes. Mapped one-for-one so positions in the text hold.
_QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})


def known_figures(diffs: list[AnswerDiff]) -> dict[str, str]:
    """Every figure the story may use, and the answer it belongs to.

    Only answers that moved: those are the ones the model was shown, and a
    figure from an answer it never saw is a coincidence, not a citation.
    """
    figures: dict[str, str] = {}
    for diff in diffs:
        if not diff.changed:
            continue
        measure = diff.question.measure
        for value in (diff.before.value, diff.after.value):
            if value is None:
                continue
            shown = say_number(value, measure)
            figures.setdefault(_plain(shown), diff.question.id)
            figures.setdefault(_plain(str(value)), diff.question.id)
        for group in diff.groups:
            for value in (group.before, group.after):
                if value is not None:
                    figures.setdefault(_plain(say_number(value, measure)), diff.question.id)
    return figures


def story_facts(diffs: list[AnswerDiff]) -> dict[str, object]:
    """What the model is told: the answers that moved, and nothing else."""
    changed = [diff for diff in diffs if diff.changed]
    return {
        "answers": [
            {
                "id": diff.question.id,
                "question": diff.question.label,
                "before": say_number(diff.before.value, diff.question.measure)
                if diff.before.answerable
                else "couldn't be answered",
                "after": say_number(diff.after.value, diff.question.measure)
                if diff.after.answerable
                else "couldn't be answered",
                "new_question": diff.unlocked,
            }
            for diff in changed
        ]
    }


def accepted_story(
    diffs: list[AnswerDiff], reply: StoryReply, recipe_key: str | None = None
) -> Story | None:
    """The model's story, if every figure in it is one of ours."""
    figures = known_figures(diffs)
    names = _names_with_digits(diffs)
    sentences: list[StorySentence] = []
    for text in reply.sentences:
        if uses_jargon(text) or any(m in text for m in MARKDOWN):
            logger.info("ai story rejected reason=wording")
            return None
        sentence = _as_parts(text, figures, names)
        if sentence is None:
            logger.info("ai story rejected reason=invented a number")
            return None
        sentences.append(sentence)
    if not sentences:
        return None
    return Story(sentences=sentences, source="ai", recipe_key=recipe_key)


def _names_with_digits(diffs: list[AnswerDiff]) -> list[str]:
    """Wording that carries a digit without stating a figure.

    A column can be called "column_3" or "2023 Sales", and a model naturally
    names the column, or quotes the question, it is talking about. Reading those
    digits as figures would throw away a sound story over a column's spelling.
    Only names that actually contain a digit are listed, so the text a figure
    can hide in stays as small as possible.
    """
    names: set[str] = set()
    for diff in diffs:
        if not diff.changed:
            continue
        for name in (diff.question.label.rstrip("?"), *diff.question.columns):
            if any(character.isdigit() for character in name):
                names.add(name.translate(_QUOTES).strip())
    return sorted(names)


def _spans_of(text: str, names: list[str]) -> list[tuple[int, int]]:
    """Where in the sentence those names are spelled out."""
    flat = text.translate(_QUOTES)
    spans: list[tuple[int, int]] = []
    for name in names:
        start = flat.find(name)
        while start != -1:
            spans.append((start, start + len(name)))
            start = flat.find(name, start + 1)
    return spans


def _as_parts(text: str, figures: dict[str, str], names: list[str]) -> StorySentence | None:
    """Split a sentence into words and figures, linking each figure to its answer."""
    spans = _spans_of(text, names)
    parts: list[StoryPart] = []
    position = 0
    for match in _NUMBER.finditer(text):
        # Part of a name, so it stays in the words around it and points nowhere.
        if any(start <= match.start() and match.end() <= end for start, end in spans):
            continue
        question_id = figures.get(_plain(match.group()))
        if question_id is None:
            return None
        if match.start() > position:
            parts.append(StoryPart(text=text[position : match.start()]))
        parts.append(StoryPart(text=match.group(), question_id=question_id))
        position = match.end()
    if position < len(text):
        parts.append(StoryPart(text=text[position:]))
    return StorySentence(parts=parts)


def _plain(value: str) -> str:
    """How a figure is compared: without separators, and without trailing zeros."""
    cleaned = value.replace(",", "").strip()
    if "." in cleaned:
        cleaned = cleaned.rstrip("0").rstrip(".")
    return cleaned.lstrip("0") or "0"
