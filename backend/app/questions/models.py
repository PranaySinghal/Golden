"""Business questions asked of a table, and their answers."""

import hashlib
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class Measure(StrEnum):
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    SUM = "sum"
    AVG = "avg"


class DateGrain(StrEnum):
    MONTH = "month"
    YEAR = "year"


class QuestionFilter(BaseModel):
    column: str
    equals: str = Field(min_length=1)


class Question(BaseModel):
    id: str = ""
    measure: Measure
    column: str | None = None
    group_by: str | None = None
    grain: DateGrain | None = None
    filter: QuestionFilter | None = None
    label: str
    # How headline the question is, from 0 to 1; weights impact.
    prominence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _valid_spec(self) -> Self:
        if self.measure is Measure.COUNT and self.column is not None:
            raise ValueError("a count question doesn't take a column")
        if self.measure is not Measure.COUNT and self.column is None:
            raise ValueError(f"a {self.measure} question needs a column")
        if self.grain is not None and self.group_by is None:
            raise ValueError("a grain only applies when grouping by a date column")
        if not self.id:
            self.id = question_id(self)
        return self

    @property
    def columns(self) -> set[str]:
        names = {self.column, self.group_by, self.filter.column if self.filter else None}
        return {name for name in names if name is not None}


def question_id(question: Question) -> str:
    spec = question.model_dump_json(include={"measure", "column", "group_by", "grain", "filter"})
    return hashlib.sha1(spec.encode()).hexdigest()[:12]


class GroupValue(BaseModel):
    # The key groups are matched on (case ignored); None is the blank group.
    key: str | None
    # How the group is shown: its most common spelling.
    label: str | None
    value: float | None
    rows: int


class Answer(BaseModel):
    answerable: bool
    value: float | None = None
    groups: list[GroupValue] = Field(default_factory=list)
    rows_used: int = 0
    rows_skipped: int = 0
    note: str | None = None


class GroupDiff(BaseModel):
    key: str | None
    label: str | None
    before: float | None
    after: float | None
    status: Literal["same", "changed", "appeared", "disappeared"]
    # A group that disappeared because its spelling folded into another group.
    merged_into: str | None = None
    change: float | None = None
    relative_change: float | None = None


class AnswerDiff(BaseModel):
    question: Question
    before: Answer
    after: Answer
    changed: bool
    change: float | None = None
    relative_change: float | None = None
    groups: list[GroupDiff] = Field(default_factory=list)
    magnitude: float = 0.0
    impact: float = 0.0
    attribution: list[str] = Field(default_factory=list)
    unlocked: bool = False
