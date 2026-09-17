"""Decide what each column is from the properties of its values.

Rules run in order and the first match wins. Every threshold is a named
constant so tests can document it. Column names only break ties in the two
cases where values can't tell the difference (see name_hints).
"""

from dataclasses import dataclass, field
from enum import StrEnum

from app.profile.models import ColumnFlag, PhysicalType, SemanticRole
from app.profile.name_hints import NameHint, name_hint
from app.profile.stats import ColumnStats

# Share of filled values that must match for a pattern to define the column.
# Leaves room for placeholders like "N/A" and typos.
STRONG_MATCH = 0.8
BOOLEAN_MATCH = 0.9
# Identifiers: codes that share one shape and are (almost) all different.
CODE_SHAPE_MATCH = 0.9
CODE_MIN_UNIQUENESS = 0.8
CODE_MAX_WHITESPACE = 0.05
NUMERIC_ID_INTEGER_SHARE = 0.95
NUMERIC_ID_MIN_UNIQUENESS = 0.95
LEADING_ZERO_SHARE = 0.05
# Whole numbers count as a sequence when they span at most this many times
# their count, e.g. 1..1020 for 1,020 rows.
SEQUENCE_SPAN_FACTOR = 1.5
SEQUENCE_MIN_VALUES = 10
FIXED_WIDTH_SHARE = 0.9
# Amounts rarely have 7+ digits that are all different and all the same length;
# phone numbers and account numbers do.
FIXED_WIDTH_MIN_DIGITS = 7
# Categories: values repeat, and they're short labels rather than sentences.
CATEGORY_MAX_UNIQUENESS = 0.5
CATEGORY_MAX_AVG_LENGTH = 50
SMALL_CATEGORY_MAX_DISTINCT = 12
LOW_UNIQUENESS = 0.9
MOSTLY_BLANK = 0.5
AMBIGUOUS_CONFIDENCE = 0.6
HINTED_CONFIDENCE = 0.75
TEXT_CONFIDENCE = 0.5


class RoleReason(StrEnum):
    """Why a role was chosen. Notes are rendered from this in notes.py."""

    NO_ROWS = "no_rows"
    ALL_BLANK = "all_blank"
    DATES = "dates"
    EMAILS = "emails"
    PHONES_FORMATTED = "phones_formatted"
    PHONES_BY_NAME = "phones_by_name"
    YES_NO = "yes_no"
    CODE_PATTERN = "code_pattern"
    NUMBER_CODES = "number_codes"
    SEQUENCE = "sequence"
    LONG_FIXED_WIDTH = "long_fixed_width"
    NUMBERS = "numbers"
    NUMBER_LABELS = "number_labels"
    REPEATED_LABELS = "repeated_labels"
    FREE_TEXT = "free_text"


@dataclass(frozen=True)
class RoleDecision:
    role: SemanticRole
    confidence: float
    reason: RoleReason
    physical_type: PhysicalType
    flags: list[ColumnFlag] = field(default_factory=list)


def infer_role(stats: ColumnStats) -> RoleDecision:
    role, confidence, reason, hint_used = _decide(stats)
    flags = _flags(stats, role)
    if hint_used:
        flags.append(ColumnFlag.NAME_HINT_USED)
    return RoleDecision(
        role=role,
        confidence=round(confidence, 3),
        reason=reason,
        physical_type=physical_type(stats),
        flags=flags,
    )


def uniqueness(stats: ColumnStats) -> float:
    return stats.distinct / stats.non_blank if stats.non_blank else 0.0


def is_yes_no(stats: ColumnStats) -> bool:
    n = stats.non_blank
    if n == 0:
        return False
    words = stats.boolean_token / n >= BOOLEAN_MATCH and stats.boolean_distinct == 2
    zero_one = stats.zero_one / n >= BOOLEAN_MATCH and stats.zero_one_distinct == 2
    return words or zero_one


def physical_type(stats: ColumnStats) -> PhysicalType:
    n = stats.non_blank
    if n == 0:
        return PhysicalType.EMPTY
    if is_yes_no(stats):
        return PhysicalType.BOOLEAN
    if stats.date_any / n >= STRONG_MATCH:
        if stats.date_with_time / stats.date_any >= 0.5:
            return PhysicalType.DATETIME
        return PhysicalType.DATE
    if stats.lenient_number / n >= STRONG_MATCH:
        return PhysicalType.DECIMAL if stats.with_fraction else PhysicalType.INTEGER
    return PhysicalType.TEXT


def _decide(stats: ColumnStats) -> tuple[SemanticRole, float, RoleReason, bool]:
    n = stats.non_blank
    if n == 0:
        reason = RoleReason.NO_ROWS if stats.row_count == 0 else RoleReason.ALL_BLANK
        return SemanticRole.TEXT, 0.0, reason, False

    def share(count: int) -> float:
        return count / n

    unique = uniqueness(stats)
    hint = name_hint(stats.name)

    if share(stats.date_any) >= STRONG_MATCH:
        return SemanticRole.DATE, share(stats.date_any), RoleReason.DATES, False
    if share(stats.email) >= STRONG_MATCH:
        return SemanticRole.CONTACT, share(stats.email), RoleReason.EMAILS, False
    if share(stats.phone_formatted) >= STRONG_MATCH:
        return (
            SemanticRole.CONTACT,
            share(stats.phone_formatted),
            RoleReason.PHONES_FORMATTED,
            False,
        )
    if is_yes_no(stats):
        return (
            SemanticRole.CATEGORY,
            max(share(stats.boolean_token), share(stats.zero_one)),
            RoleReason.YES_NO,
            False,
        )

    # Bare digit strings look the same whether they're phones or other numbers.
    if share(stats.phone_digits) >= STRONG_MATCH and hint is NameHint.PHONE:
        return SemanticRole.CONTACT, HINTED_CONFIDENCE, RoleReason.PHONES_BY_NAME, True

    if (
        stats.code_shape_has_digit
        and share(stats.code_shape_count) >= CODE_SHAPE_MATCH
        and unique >= CODE_MIN_UNIQUENESS
        and share(stats.with_whitespace) <= CODE_MAX_WHITESPACE
        and share(stats.lenient_number) < STRONG_MATCH
    ):
        return (
            SemanticRole.IDENTIFIER,
            share(stats.code_shape_count),
            RoleReason.CODE_PATTERN,
            False,
        )

    if share(stats.integer) >= NUMERIC_ID_INTEGER_SHARE and unique >= NUMERIC_ID_MIN_UNIQUENESS:
        if share(stats.leading_zeros) >= LEADING_ZERO_SHARE:
            return SemanticRole.IDENTIFIER, 0.9, RoleReason.NUMBER_CODES, False
        if _is_sequence(stats):
            return SemanticRole.IDENTIFIER, 0.9, RoleReason.SEQUENCE, False
        if (
            stats.integer_width is not None
            and stats.integer_width >= FIXED_WIDTH_MIN_DIGITS
            and stats.integer_width_count / stats.integer >= FIXED_WIDTH_SHARE
        ):
            hinted = hint is NameHint.IDENTIFIER
            confidence = HINTED_CONFIDENCE if hinted else AMBIGUOUS_CONFIDENCE
            return SemanticRole.IDENTIFIER, confidence, RoleReason.LONG_FIXED_WIDTH, hinted

    if share(stats.lenient_number) >= STRONG_MATCH:
        if share(stats.leading_zeros) >= LEADING_ZERO_SHARE:
            # Zip codes and account codes: numbers used as labels, never added up.
            return SemanticRole.CATEGORY, share(stats.integer), RoleReason.NUMBER_LABELS, False
        return SemanticRole.MEASURE, share(stats.lenient_number), RoleReason.NUMBERS, False

    repeated = unique <= CATEGORY_MAX_UNIQUENESS and stats.avg_length <= CATEGORY_MAX_AVG_LENGTH
    few_labels = stats.distinct <= SMALL_CATEGORY_MAX_DISTINCT and n >= 2 * stats.distinct
    if repeated or few_labels:
        return (
            SemanticRole.CATEGORY,
            max(1.0 - unique, TEXT_CONFIDENCE),
            RoleReason.REPEATED_LABELS,
            False,
        )

    return SemanticRole.TEXT, TEXT_CONFIDENCE, RoleReason.FREE_TEXT, False


def _is_sequence(stats: ColumnStats) -> bool:
    if stats.integer_min is None or stats.integer_max is None:
        return False
    if stats.integer < SEQUENCE_MIN_VALUES:
        return False
    span = stats.integer_max - stats.integer_min + 1
    return span <= SEQUENCE_SPAN_FACTOR * stats.integer


def _flags(stats: ColumnStats, role: SemanticRole) -> list[ColumnFlag]:
    flags: list[ColumnFlag] = []
    if stats.non_blank == 0:
        flags.append(ColumnFlag.ALL_BLANK)
        return flags
    fill_rate = stats.non_blank / stats.row_count if stats.row_count else 0.0
    if fill_rate < MOSTLY_BLANK:
        flags.append(ColumnFlag.MOSTLY_BLANK)
    if stats.distinct == 1:
        flags.append(ColumnFlag.CONSTANT)
    if (
        role in (SemanticRole.IDENTIFIER, SemanticRole.CONTACT)
        and uniqueness(stats) < LOW_UNIQUENESS
    ):
        flags.append(ColumnFlag.LOW_UNIQUENESS)
    return flags
