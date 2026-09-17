"""How one side of a comparison reads the table.

A Reading says where rows come from and how each column is read as a number, a
date, or a text key. The evaluator is shared, so "before" and "after" can only
differ in these reading rules, never in how answers are computed.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ColumnReading:
    # SQL expressions over the row source. Each yields NULL when a value can't be read.
    filled: str  # true when the cell isn't blank
    number: str  # DOUBLE
    date: str  # TIMESTAMP
    key: str  # text used for distinct counts, groups, and filters
    label: str  # text shown for a group


@dataclass(frozen=True)
class RowSource:
    sql: str  # a table reference or a parenthesized subquery
    params: dict[str, object] = field(default_factory=dict)


class Reading(Protocol):
    name: str

    def rows(self) -> RowSource: ...

    def column(self, name: str) -> ColumnReading | None: ...

    def params(self) -> dict[str, object]: ...
