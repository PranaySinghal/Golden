"""What every detector gets, and helpers they share.

A detector has two halves: `gather` runs SQL against the read-only raw table
and returns plain facts; `decide` turns facts into issues without touching the
database, so the decisions can be tested on hand-written evidence.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import duckdb

from app.detectors.models import AskQuestion, Choice, DetectorName, Issue, Tier
from app.profile.models import ColumnProfile, DatasetProfile, SemanticRole
from app.steps.models import Step

MAX_EXAMPLES = 5


@dataclass(frozen=True)
class DetectorContext:
    conn: duckdb.DuckDBPyConnection
    profile: DatasetProfile
    today: date

    @property
    def row_count(self) -> int:
        return self.profile.row_count

    def columns_with_role(self, *roles: SemanticRole) -> list[ColumnProfile]:
        return [c for c in self.profile.columns if c.semantic_role in roles and c.non_blank_count]

    def query(self, sql: str, params: Mapping[str, object] | None = None) -> list[tuple[Any, ...]]:
        return self.conn.execute(sql, dict(params or {})).fetchall()


class Detector(Protocol):
    name: DetectorName

    def run(self, ctx: DetectorContext) -> list[Issue]: ...


def stable_id(*parts: object) -> str:
    """Same inputs give the same id, so re-running detection doesn't reshuffle issues."""
    digest = hashlib.sha1("|".join(str(part) for part in parts).encode()).hexdigest()
    return digest[:12]


class IssueBuilder:
    """Assembles an Issue with stable ids for the issue, its choices, and its steps."""

    def __init__(
        self, ctx: DetectorContext, detector: DetectorName, columns: Sequence[str], kind: str
    ) -> None:
        self.ctx = ctx
        self.detector = detector
        self.columns = list(columns)
        self.id = stable_id(detector, kind, *columns)
        self._step_count = 0

    def step(self, step: Step) -> Step:
        """Give a proposed step a stable id derived from this issue."""
        self._step_count += 1
        return step.model_copy(update={"id": stable_id(self.id, "step", self._step_count)})

    def choice(
        self, key: str, label: str, description: str, steps: list[Step], recommended: bool = False
    ) -> Choice:
        return Choice(
            id=stable_id(self.id, "choice", key),
            label=label,
            description=description,
            steps=steps,
            recommended=recommended,
        )

    def build(
        self,
        *,
        title: str,
        explanation: str,
        affected_rows: int,
        tier: Tier,
        steps: list[Step] | None = None,
        ask: AskQuestion | None = None,
        examples: Sequence[str] = (),
        requires: Sequence[str] = (),
    ) -> Issue:
        rows = self.ctx.row_count
        return Issue(
            id=self.id,
            detector=self.detector,
            columns=self.columns,
            title=title,
            explanation=explanation,
            affected_rows=affected_rows,
            tier=tier,
            impact=round(affected_rows / rows, 4) if rows else 0.0,
            steps=steps or [],
            ask=ask,
            examples=list(dict.fromkeys(examples))[:MAX_EXAMPLES],
            requires=list(requires),
        )


def reading_issue_id(column: str) -> str:
    """Id of the issue that reads a column as numbers or dates, which other fixes rely on."""
    return stable_id(DetectorName.NUMBERS_AS_TEXT, "read", column)


def date_issue_id(column: str) -> str:
    return stable_id(DetectorName.DATES, "read", column)
