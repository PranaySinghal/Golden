"""Plain-language notes explaining each column's role, shown on hover in the UI.

Every number in a note comes from the column's statistics. Copy follows
CLAUDE.md principle 6: no data jargon.
"""

from app.profile.models import ColumnFlag
from app.profile.patterns import LEADING_ZEROS, full_match
from app.profile.roles import RoleDecision, RoleReason
from app.profile.stats import ColumnStats


def role_note(stats: ColumnStats, decision: RoleDecision) -> str:
    note = _main_note(stats, decision.reason)
    extras: list[str] = []
    if ColumnFlag.LOW_UNIQUENESS in decision.flags:
        extras.append(
            f"Only {stats.distinct:,} different values appear across {stats.non_blank:,} "
            "filled rows, so some rows share the same one."
        )
    if stats.placeholder and decision.reason is RoleReason.NUMBERS:
        extras.append(
            f"{_count(stats.placeholder, 'value is', 'values are')} text like "
            f'"{stats.placeholder_examples[0]}" instead of a number.'
        )
    if ColumnFlag.MOSTLY_BLANK in decision.flags:
        extras.append(f"Only {_percent(stats.non_blank, stats.row_count)} of rows are filled in.")
    return " ".join([note, *extras])


def _main_note(stats: ColumnStats, reason: RoleReason) -> str:
    n = stats.non_blank
    example = f' (like "{stats.top_values[0][0]}")' if stats.top_values else ""
    zero_led = next((v for v, _ in stats.top_values if full_match(LEADING_ZEROS, v.strip())), None)
    zero_example = f' (like "{zero_led}")' if zero_led else ""
    match reason:
        case RoleReason.NO_ROWS:
            return "The file has no rows yet, so we can't tell what this column holds."
        case RoleReason.ALL_BLANK:
            return (
                f"All {stats.row_count:,} rows are empty in this column, so we can't tell "
                "what it's meant to hold. It may be unused, or the values may have been lost "
                "when the file was exported."
            )
        case RoleReason.DATES:
            return f"{_percent(stats.date_any, n)} of filled values look like dates{example}."
        case RoleReason.EMAILS:
            return f"{_percent(stats.email, n)} of filled values look like email addresses."
        case RoleReason.PHONES_FORMATTED:
            return (
                f"{_percent(stats.phone_formatted, n)} of filled values look like phone "
                f"numbers{example}."
            )
        case RoleReason.PHONES_BY_NAME:
            return (
                "Values are long strings of digits, and the column name suggests they're "
                "phone numbers."
            )
        case RoleReason.YES_NO:
            answers = " or ".join(f'"{value}"' for value in yes_no_answers(stats))
            return f"Every filled value is a yes/no answer: {answers}."
        case RoleReason.CODE_PATTERN:
            shape = f" ({stats.code_shape_example})" if stats.code_shape_example else ""
            return (
                "Almost every value is different and follows the same code pattern"
                f"{shape}, so this looks like an ID."
            )
        case RoleReason.NUMBER_CODES:
            return (
                f"Values are number codes with leading zeros{zero_example} and almost all are "
                "different, so this looks like an ID."
            )
        case RoleReason.SEQUENCE:
            return (
                "Values are whole numbers that are almost all different and run in a "
                "sequence, so this looks like an ID rather than an amount."
            )
        case RoleReason.LONG_FIXED_WIDTH:
            return (
                "Values are long whole numbers of the same length and almost all "
                "different, so this looks like an ID rather than an amount."
            )
        case RoleReason.NUMBERS:
            return (
                f"{_percent(stats.lenient_number, n)} of filled values are numbers, so they "
                "can be added up and averaged."
            )
        case RoleReason.NUMBER_LABELS:
            return (
                f"Values are numbers with leading zeros{zero_example}, so they're treated as "
                "labels rather than amounts."
            )
        case RoleReason.REPEATED_LABELS:
            return (
                f"{stats.distinct:,} different values repeat across {n:,} filled rows, "
                "so this groups rows into categories."
            )
        case RoleReason.FREE_TEXT:
            return "Values are mostly different from each other, so this looks like free text."


def yes_no_answers(stats: ColumnStats) -> list[str]:
    """The two answers as written, treating "Yes" and "yes" as the same answer."""
    seen: dict[str, str] = {}
    for value, _ in stats.top_values:
        seen.setdefault(value.strip().lower(), value.strip())
    return list(seen.values())[:2]


def _percent(part: int, whole: int) -> str:
    if whole == 0:
        return "0%"
    value = part / whole * 100
    # Never round up to 100% or down to 0% when that would hide a remainder.
    if part < whole and value > 99:
        return "over 99%"
    if part > 0 and value < 1:
        return "under 1%"
    return f"{round(value)}%"


def _count(count: int, singular: str, plural: str) -> str:
    return f"{count:,} {singular if count == 1 else plural}"
