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
from app.ai.wording import JARGON, MARKDOWN
from app.questions.models import AnswerDiff
from app.story import Story, StoryPart, StorySentence, say_number

logger = logging.getLogger("tidylab.ai")

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def known_figures(diffs: list[AnswerDiff]) -> dict[str, str]:
    """Every figure the story may use, and the answer it belongs to."""
    figures: dict[str, str] = {}
    for diff in diffs:
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


def accepted_story(diffs: list[AnswerDiff], reply: StoryReply) -> Story | None:
    """The model's story, if every figure in it is one of ours."""
    figures = known_figures(diffs)
    sentences: list[StorySentence] = []
    for text in reply.sentences:
        if any(word in text.lower() for word in JARGON) or any(m in text for m in MARKDOWN):
            logger.info("ai story rejected reason=wording")
            return None
        sentence = _as_parts(text, figures)
        if sentence is None:
            logger.info("ai story rejected reason=invented a number")
            return None
        sentences.append(sentence)
    if not sentences:
        return None
    return Story(sentences=sentences, source="ai")


def _as_parts(text: str, figures: dict[str, str]) -> StorySentence | None:
    """Split a sentence into words and figures, linking each figure to its answer."""
    parts: list[StoryPart] = []
    position = 0
    for match in _NUMBER.finditer(text):
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
