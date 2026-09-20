import duckdb

from app.db import ROW_ID_COLUMN, raw_columns
from app.profile.models import (
    ColumnProfile,
    DatasetProfile,
    DetectedPattern,
    PatternKind,
    PhysicalType,
    SemanticRole,
)
from app.profile.notes import role_note, yes_no_answers
from app.profile.roles import RoleDecision, RoleReason, infer_role
from app.profile.stats import ColumnStats, compute_column_stats, count_rows

# Patterns below this share are noise, except placeholders: 24 "N/A" in a
# thousand salaries is exactly what later steps need to know about.
_PATTERN_MIN_SHARE = 0.05
_DELIMITED_MIN_SHARE = 0.9
_SAMPLE_VALUE_MAX_CHARS = 80
_MAX_EXACT_WHOLE = 2**53


def profile_table(conn: duckdb.DuckDBPyConnection) -> DatasetProfile:
    row_count = count_rows(conn)
    names = [name for name in raw_columns(conn) if name != ROW_ID_COLUMN]
    columns = [
        profile_column(compute_column_stats(conn, name, position, row_count))
        for position, name in enumerate(names)
    ]
    return DatasetProfile(row_count=row_count, column_count=len(columns), columns=columns)


def profile_column(stats: ColumnStats) -> ColumnProfile:
    decision = infer_role(stats)
    min_value, max_value = _range(stats, decision)
    return ColumnProfile(
        name=stats.name,
        position=stats.position,
        physical_type=decision.physical_type,
        semantic_role=decision.role,
        role_confidence=decision.confidence,
        role_note=role_note(stats, decision),
        flags=decision.flags,
        row_count=stats.row_count,
        non_blank_count=stats.non_blank,
        fill_rate=_ratio(stats.non_blank, stats.row_count),
        distinct_count=stats.distinct,
        uniqueness=_ratio(stats.distinct, stats.non_blank),
        patterns=detect_patterns(stats, decision),
        min_value=min_value,
        max_value=max_value,
        sample_values=[_truncate(value) for value, _ in stats.top_values],
    )


def detect_patterns(stats: ColumnStats, decision: RoleDecision) -> list[DetectedPattern]:
    n = stats.non_blank
    if n == 0:
        return []

    found: list[DetectedPattern] = []

    def add(kind: PatternKind, count: int, detail: str | None = None) -> None:
        if count > 0 and count / n >= _PATTERN_MIN_SHARE:
            found.append(
                DetectedPattern(
                    kind=kind, match_count=count, match_rate=_ratio(count, n), detail=detail
                )
            )

    add(PatternKind.EMAIL, stats.email)
    add(PatternKind.URL, stats.url)
    add(PatternKind.PHONE, stats.phone_formatted)
    if decision.reason is RoleReason.PHONES_BY_NAME:
        add(PatternKind.PHONE, stats.phone_digits, "digits only")
    add(PatternKind.DATE_YEAR_FIRST, stats.date_year_first)
    add(PatternKind.DATE_NUMERIC, stats.date_numeric)
    add(PatternKind.DATE_TEXT, stats.date_text)
    add(PatternKind.DATETIME, stats.date_with_time)
    if decision.physical_type is PhysicalType.BOOLEAN:
        count = max(stats.boolean_token, stats.zero_one)
        add(PatternKind.BOOLEAN, count, " / ".join(yes_no_answers(stats)))
    add(PatternKind.INTEGER, stats.integer)
    add(PatternKind.DECIMAL, stats.decimal)
    add(PatternKind.CURRENCY, stats.currency)
    add(PatternKind.PERCENT, stats.percent)
    add(PatternKind.THOUSANDS_SEPARATOR, stats.thousands_separator)
    add(PatternKind.LEADING_ZEROS, stats.leading_zeros)
    if stats.placeholder:
        found.append(
            DetectedPattern(
                kind=PatternKind.PLACEHOLDER,
                match_count=stats.placeholder,
                match_rate=_ratio(stats.placeholder, n),
                detail=", ".join(stats.placeholder_examples) or None,
            )
        )
    # Numbers and dates always share a shape, so the shape only says something about IDs.
    if decision.role is SemanticRole.IDENTIFIER and stats.code_shape_has_digit:
        add(PatternKind.CODE_SHAPE, stats.code_shape_count, stats.code_shape_example)
    if decision.role in (SemanticRole.CATEGORY, SemanticRole.TEXT, SemanticRole.IDENTIFIER):
        for delimiter, count in stats.delimiter_counts.items():
            if count / n >= _DELIMITED_MIN_SHARE:
                add(PatternKind.DELIMITED, count, delimiter)
    return found


def _range(stats: ColumnStats, decision: RoleDecision) -> tuple[str | None, str | None]:
    if decision.role is SemanticRole.DATE:
        return stats.date_min, stats.date_max
    if decision.role is SemanticRole.MEASURE:
        return _format_number(stats.number_min), _format_number(stats.number_max)
    return None, None


def _format_number(value: float | None) -> str | None:
    """A number as a person would write it.

    `repr` shows how a decimal is really stored — 2.2140000000000004 for a value
    a spreadsheet displays as 2.214 — which reads as nonsense in a column
    summary. Ten significant digits keep every figure these files hold without
    showing the noise underneath them.
    """
    if value is None:
        return None
    if value.is_integer() and abs(value) < _MAX_EXACT_WHOLE:
        return str(int(value))
    return f"{value:.10g}"


def _ratio(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def _truncate(value: str) -> str:
    if len(value) <= _SAMPLE_VALUE_MAX_CHARS:
        return value
    return value[: _SAMPLE_VALUE_MAX_CHARS - 1] + "…"
