"""Accepting better wording, and only better wording.

A rewrite may change how something is said. It may not change what it says, and
above all it may not introduce a number: every figure a user reads has to come
from the engine (CLAUDE.md principle 2). So each rewrite is checked against the
text it replaces, and anything that brings a new number, a jargon word or
markdown is dropped — one bad item at a time, never the whole batch.
"""

import logging
import re

from pydantic import BaseModel

from app.ai.schemas import RewordIssuesReply, RewordQuestionsReply
from app.detectors.models import Issue
from app.questions.models import Question

logger = logging.getLogger("tidylab.ai")

# Words from the machinery. A business user should never meet them.
JARGON = (
    "null",
    "nan",
    "dedupe",
    "deduplicate",
    "cast",
    "parse",
    "regex",
    "delimiter",
    "schema",
    "column_2",
    "varchar",
    "sql",
    "aggregate",
    "distinct count",
)
MARKDOWN = ("**", "##", "```", "- ", "* ")
_NUMBER = re.compile(r"\d[\d,._]*")


class RewordedCopy(BaseModel):
    """The title and explanation a card should show, once a rewrite was accepted."""

    title: str
    explanation: str


def numbers_in(text: str) -> set[str]:
    """Every figure in a sentence, in a form that ignores how it was written.

    "1,020" and "1020" are the same number; "2.50" and "2.5" are too. Anything
    the user could read as a quantity counts.
    """
    found = set()
    for token in _NUMBER.findall(text):
        cleaned = token.replace(",", "").replace("_", "").rstrip(".")
        if "." in cleaned:
            # 2.50 and 2.5 are the same figure; 2 and 50 are not what was said.
            cleaned = cleaned.rstrip("0").rstrip(".")
        found.add(cleaned.lstrip("0") or "0")
    return found


def invents_numbers(source: str, rewrite: str) -> bool:
    """True when the rewrite contains a figure its source didn't."""
    return bool(numbers_in(rewrite) - numbers_in(source))


def is_acceptable(source: str, rewrite: str) -> tuple[bool, str]:
    if invents_numbers(source, rewrite):
        return False, "invented a number"
    lowered = rewrite.lower()
    if any(word in lowered for word in JARGON):
        return False, "used jargon"
    if any(mark in rewrite for mark in MARKDOWN):
        return False, "used markdown"
    return True, ""


def accepted_issue_copy(issues: list[Issue], reply: RewordIssuesReply) -> dict[str, RewordedCopy]:
    """Rewrites we're willing to show, by issue id. Everything else keeps its template."""
    by_id = {issue.id: issue for issue in issues}
    accepted: dict[str, RewordedCopy] = {}
    for item in reply.items:
        issue = by_id.get(item.id)
        if issue is None:
            logger.info("ai wording rejected reason=unknown id")
            continue
        source = f"{issue.title} {issue.explanation} {issue.affected_rows}"
        title_ok, title_why = is_acceptable(source, item.title)
        body_ok, body_why = is_acceptable(source, item.explanation)
        if not (title_ok and body_ok):
            logger.info("ai wording rejected reason=%s", title_why or body_why)
            continue
        accepted[item.id] = RewordedCopy(title=item.title, explanation=item.explanation)
    return accepted


def accepted_question_labels(
    questions: list[Question], reply: RewordQuestionsReply
) -> dict[str, str]:
    by_id = {question.id: question for question in questions}
    accepted: dict[str, str] = {}
    for item in reply.items:
        question = by_id.get(item.id)
        if question is None:
            logger.info("ai wording rejected reason=unknown id")
            continue
        ok, why = is_acceptable(question.label, item.label)
        if not ok:
            logger.info("ai wording rejected reason=%s", why)
            continue
        accepted[item.id] = item.label
    return accepted
