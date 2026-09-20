"""Everything a model is allowed to see, and nothing else.

CLAUDE.md: the LLM sees metadata, not data — the profile, the statistics, and a
small sample of rows. This builds that as a plain dict, so what gets sent can be
read in a test instead of taken on trust.
"""

from typing import Any

import duckdb
from pydantic import BaseModel

from app.config import MAX_SAMPLE_ROWS
from app.db import RAW_REF, ROW_ID_COLUMN, quote_ident
from app.detectors.models import Issue
from app.profile.models import ColumnProfile, DatasetProfile
from app.questions.models import Question

# A sample is for seeing the shape of a value, not for reading its contents.
MAX_VALUE_CHARS = 80
MAX_SAMPLE_VALUES = 5
# Past this, the sample is trimmed: rows first, then per-column examples.
MAX_PAYLOAD_CHARS = 40_000


class ColumnFacts(BaseModel):
    name: str
    kind: str  # the semantic role, in the app's own words
    stored_as: str
    filled: float
    different_values: int
    looks_like: list[str]
    examples: list[str]


class IssueFacts(BaseModel):
    id: str
    title: str
    explanation: str
    affected_rows: int
    tier: str


class QuestionFacts(BaseModel):
    id: str
    label: str


def column_facts(column: ColumnProfile) -> ColumnFacts:
    patterns = [
        f"{pattern.kind.value} ({round(pattern.match_rate * 100)}%)"
        for pattern in column.patterns
        if pattern.match_rate >= 0.05
    ]
    return ColumnFacts(
        name=column.name,
        kind=column.semantic_role.value,
        stored_as=column.physical_type.value,
        filled=round(column.fill_rate, 3),
        different_values=column.distinct_count,
        looks_like=patterns,
        examples=[_short(value) for value in column.sample_values[:MAX_SAMPLE_VALUES]],
    )


def sample_rows(
    conn: duckdb.DuckDBPyConnection, profile: DatasetProfile, limit: int
) -> list[dict[str, str | None]]:
    """The first few rows as text, for shape. Never more than MAX_SAMPLE_ROWS."""
    names = [column.name for column in profile.columns]
    if not names or limit <= 0:
        return []
    wanted = min(limit, MAX_SAMPLE_ROWS)
    selected = ", ".join(quote_ident(name) for name in names)
    rows = conn.execute(
        f"SELECT {selected} FROM {RAW_REF} ORDER BY {quote_ident(ROW_ID_COLUMN)} LIMIT {wanted}"
    ).fetchall()
    return [
        {
            name: None if value is None else _short(str(value))
            for name, value in zip(names, row, strict=True)
        }
        for row in rows
    ]


def fixes_payload(
    conn: duckdb.DuckDBPyConnection,
    profile: DatasetProfile,
    known: list[Issue],
    sample_limit: int,
) -> dict[str, Any]:
    """What the "suggest fixes" prompt gets: the shape of the file and what we already found."""
    payload: dict[str, Any] = {
        "row_count": profile.row_count,
        "columns": [column_facts(column).model_dump() for column in profile.columns],
        "already_found": [issue.title for issue in known],
        "sample_rows": sample_rows(conn, profile, sample_limit),
    }
    return _within_limit(payload)


def issue_wording_payload(issues: list[Issue]) -> dict[str, Any]:
    return {
        "issues": [
            IssueFacts(
                id=issue.id,
                title=issue.title,
                explanation=issue.explanation,
                affected_rows=issue.affected_rows,
                tier=issue.tier.value,
            ).model_dump()
            for issue in issues
        ]
    }


def question_wording_payload(questions: list[Question]) -> dict[str, Any]:
    return {"questions": [QuestionFacts(id=q.id, label=q.label).model_dump() for q in questions]}


def _short(value: str) -> str:
    return value if len(value) <= MAX_VALUE_CHARS else value[: MAX_VALUE_CHARS - 1] + "…"


def _within_limit(payload: dict[str, Any]) -> dict[str, Any]:
    """Trim the sample until the payload is a reasonable size: rows first, then examples."""
    while _size(payload) > MAX_PAYLOAD_CHARS and payload["sample_rows"]:
        payload["sample_rows"] = payload["sample_rows"][: len(payload["sample_rows"]) // 2]
    if _size(payload) > MAX_PAYLOAD_CHARS:
        for column in payload["columns"]:
            column["examples"] = column["examples"][:1]
    return payload


def _size(payload: dict[str, Any]) -> int:
    return len(str(payload))
