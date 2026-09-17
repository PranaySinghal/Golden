"""The "before" reading: how a typical spreadsheet reads the raw file.

This module is the only place these rules live (CLAUDE.md, key definitions).
They're shown to users in plain words (see RULES), and each has a test.

B1  Every row in the file counts, including repeated rows.
B2  A blank is an empty cell or one holding only spaces. Blanks don't count in
    distinct counts, totals, or averages; the row count still includes them.
B3  A value counts as a number only if, with surrounding spaces removed, it's a
    plain number: 12, -3.5, 1e3. "$85,000", "1,200", "12%", "85k", "N/A" don't.
B4  An average divides by the number of values read as numbers, so text like
    "N/A" is left out of both the total and the count.
B5  Distinct counts ignore capital letters but not spaces: "Sales" and "sales"
    are one value, "Sales " is another. (Excel does the same.)
B6  Groups follow B5. Blank cells form a "(blank)" group; placeholder text such
    as "N/A" is a group of its own. A group is shown with its most common spelling.
B7  A value counts as a date only as yyyy-mm-dd or month/day/year (US order),
    optionally with a time. Other date styles are left out of trends.
B8  Filters follow B5: "Active" matches "active" but not "Active ".
B9  A question is unanswerable when none of its values can be read.

The "after" reading reuses B3, B5, B7, and B8 for any column a recipe left as text,
so skipping a fix never quietly improves an answer.
"""

from app.compare.reading import ColumnReading, RowSource
from app.db import RAW_REF, quote_ident
from app.profile.patterns import PLAIN_NUMBER

RULES: list[str] = [
    "Every row in the file counts, including repeated rows.",
    "Blank cells, or cells with only spaces, are left out of counts of different values, "
    "totals, and averages.",
    "A value counts as a number only if it's a plain number like 12 or -3.5. Values like "
    '"$85,000", "1,200", "12%", or "N/A" are left out.',
    'Averages divide by how many values were read as numbers, so "N/A" doesn\'t pull them down.',
    'Capital letters are ignored but spaces aren\'t: "Sales" and "sales" match, "Sales " doesn\'t.',
    'Blank cells form their own "(blank)" group.',
    "Dates count only when written like 2024-03-15 or 3/15/2024.",
]

# Only the styles a US-locale spreadsheet turns into dates on its own.
DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
]
PLAIN_NUMBER_PARAM = "before_plain_number"


def spreadsheet_trimmed(expr: str) -> str:
    return f"NULLIF(regexp_replace({expr}, '^\\s+|\\s+$', '', 'g'), '')"


def spreadsheet_filled(expr: str) -> str:
    """B2."""
    return f"({expr} IS NOT NULL AND NOT regexp_full_match({expr}, '\\s*'))"


def spreadsheet_number(expr: str) -> str:
    """B3."""
    t = spreadsheet_trimmed(expr)
    return (
        f"CASE WHEN regexp_full_match({t}, ${PLAIN_NUMBER_PARAM}) THEN TRY_CAST({t} AS DOUBLE) END"
    )


def spreadsheet_date(expr: str) -> str:
    """B7."""
    formats = ", ".join(f"'{fmt}'" for fmt in DATE_FORMATS)
    return f"try_strptime({spreadsheet_trimmed(expr)}, [{formats}])"


def spreadsheet_key(expr: str) -> str:
    """B5, B6, B8: capitals ignored, spaces kept, blanks are NULL."""
    return f"CASE WHEN {spreadsheet_filled(expr)} THEN lower({expr}) END"


def spreadsheet_label(expr: str) -> str:
    return f"CASE WHEN {spreadsheet_filled(expr)} THEN {expr} END"


def spreadsheet_params() -> dict[str, object]:
    return {PLAIN_NUMBER_PARAM: PLAIN_NUMBER}


def text_column(expr: str) -> ColumnReading:
    return ColumnReading(
        filled=spreadsheet_filled(expr),
        number=spreadsheet_number(expr),
        date=spreadsheet_date(expr),
        key=spreadsheet_key(expr),
        label=spreadsheet_label(expr),
    )


class BeforeReading:
    name = "before"

    def __init__(self, column_names: list[str]) -> None:
        self._columns = set(column_names)

    def rows(self) -> RowSource:
        """B1: the raw table as uploaded."""
        return RowSource(RAW_REF)

    def column(self, name: str) -> ColumnReading | None:
        if name not in self._columns:
            return None
        return text_column(quote_ident(name))

    def params(self) -> dict[str, object]:
        return spreadsheet_params()
