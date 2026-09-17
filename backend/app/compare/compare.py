"""Answer every question before and after cleaning, and rank what changed."""

from collections.abc import MutableMapping

import duckdb

from app.compare.diff import diff_answers
from app.compare.evaluate import evaluate
from app.compare.impact import rank, score
from app.compare.reading import Reading
from app.questions.models import Answer, AnswerDiff, Question

# Answers keyed by (reading key, question id). The "before" key never changes
# because the raw table never does; "after" keys are recipe fingerprints.
AnswerCache = MutableMapping[tuple[str, str], Answer]


def answer(
    conn: duckdb.DuckDBPyConnection,
    question: Question,
    reading: Reading,
    reading_key: str,
    cache: AnswerCache | None = None,
) -> Answer:
    key = (reading_key, question.id)
    if cache is not None and key in cache:
        return cache[key]
    result = evaluate(conn, question, reading)
    if cache is not None:
        cache[key] = result
    return result


def compare(
    conn: duckdb.DuckDBPyConnection,
    questions: list[Question],
    before: Reading,
    after: Reading,
    after_key: str,
    cache: AnswerCache | None = None,
    before_key: str = "before",
) -> list[AnswerDiff]:
    diffs = [
        score(
            diff_answers(
                q,
                answer(conn, q, before, before_key, cache),
                answer(conn, q, after, after_key, cache),
            )
        )
        for q in questions
    ]
    return rank(diffs)
