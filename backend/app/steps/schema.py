"""What the table looks like at each point in a recipe: column names and the kind of values."""

from dataclasses import dataclass
from enum import StrEnum

from app.profile.models import DatasetProfile


class ValueKind(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    DATETIME = "datetime"


SQL_TYPES: dict[ValueKind, str] = {
    ValueKind.TEXT: "VARCHAR",
    ValueKind.NUMBER: "DOUBLE",
    ValueKind.DATE: "DATE",
    ValueKind.DATETIME: "TIMESTAMP",
}

# How error messages describe a column's contents.
KIND_WORDS: dict[ValueKind, str] = {
    ValueKind.TEXT: "text",
    ValueKind.NUMBER: "numbers",
    ValueKind.DATE: "dates",
    ValueKind.DATETIME: "dates and times",
}


@dataclass(frozen=True)
class StageColumn:
    name: str
    kind: ValueKind


@dataclass(frozen=True)
class StageSchema:
    columns: tuple[StageColumn, ...]

    @classmethod
    def all_text(cls, names: list[str]) -> "StageSchema":
        return cls(tuple(StageColumn(name, ValueKind.TEXT) for name in names))

    def names(self) -> list[str]:
        return [column.name for column in self.columns]

    def get(self, name: str) -> StageColumn | None:
        return next((column for column in self.columns if column.name == name), None)

    def name_taken(self, name: str) -> bool:
        # DuckDB compares identifiers without case, so "Region" and "region" clash.
        folded = name.casefold()
        return any(column.name.casefold() == folded for column in self.columns)


def base_schema(profile: DatasetProfile) -> StageSchema:
    """Every raw column is text; identifiers are validated against this, i.e. the profile."""
    return StageSchema.all_text([column.name for column in profile.columns])


# Whole numbers are shown without ".0"; beyond 2^53 a double can't hold every integer.
_MAX_EXACT_WHOLE = 9007199254740992


def text_of(expr: str, kind: ValueKind) -> str:
    """SQL that renders a value of the given kind as the text a user would expect."""
    match kind:
        case ValueKind.TEXT:
            return expr
        case ValueKind.NUMBER:
            return (
                f"CASE WHEN {expr} IS NULL THEN NULL "
                f"WHEN {expr} = trunc({expr}) AND abs({expr}) < {_MAX_EXACT_WHOLE} "
                f"THEN CAST(CAST({expr} AS BIGINT) AS VARCHAR) "
                f"ELSE CAST({expr} AS VARCHAR) END"
            )
        case ValueKind.DATE:
            return f"CAST({expr} AS VARCHAR)"
        case ValueKind.DATETIME:
            return f"strftime({expr}, '%Y-%m-%d %H:%M:%S')"


def blank_predicate(expr: str, kind: ValueKind) -> str:
    """Missing means NULL, or text made only of whitespace."""
    if kind is ValueKind.TEXT:
        return f"({expr} IS NULL OR regexp_full_match({expr}, '\\s*'))"
    return f"({expr} IS NULL)"


def trimmed(expr: str) -> str:
    return f"NULLIF(regexp_replace({expr}, '^\\s+|\\s+$', '', 'g'), '')"


def match_key(expr: str) -> str:
    """Text compared ignoring case and spacing. Mirrors normalize_text()."""
    return f"NULLIF(lower(regexp_replace({trimmed(expr)}, '\\s+', ' ', 'g')), '')"


def normalize_text(value: str) -> str:
    return " ".join(value.split()).lower()
