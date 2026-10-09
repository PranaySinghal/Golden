"""Value patterns shared by header detection (Python `re`) and profiling (DuckDB RE2).

Every pattern is written in the subset of syntax both engines accept, and is
meant for full matches against a whitespace-trimmed value. Nothing here refers
to a particular dataset: these are general shapes of numbers, dates, and contacts.
"""

import re
from typing import Literal, get_args

_MONTH = r"(0?[1-9]|1[0-2])"
_DAY = r"(0?[1-9]|[12][0-9]|3[01])"
_MONTH_NAME = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_TIME = (
    r"([T ][0-9]{1,2}:[0-9]{2}(:[0-9]{2}(\.[0-9]+)?)?\s?([aApP][mM])?(Z|[+-][0-9]{2}:?[0-9]{2})?)"
)

INTEGER = r"[-+]?[0-9]+"
DECIMAL = r"[-+]?([0-9]+\.[0-9]*|\.[0-9]+)"
# What a spreadsheet would read as a number without any cleanup.
PLAIN_NUMBER = r"[-+]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][-+]?[0-9]+)?"
# Numbers people write with formatting: currency, thousands separators, percent,
# accounting-style parentheses for negatives.
LENIENT_NUMBER = (
    r"\(?[-+]?[$€£¥₹]?\s?[-+]?(([0-9]{1,3}(,[0-9]{3})+|[0-9]+)(\.[0-9]*)?|\.[0-9]+)"
    r"([eE][-+]?[0-9]+)?\s?[$€£¥₹]?\s?%?\)?"
)
CURRENCY = r".*[$€£¥₹].*"
PERCENT = r".*%\)?"
THOUSANDS_SEPARATOR = r".*[0-9]{1,3}(,[0-9]{3})+.*"
LEADING_ZEROS = r"[-+]?0[0-9]+"

# Year first (2024-03-15, 2024/3/15), optionally with a time.
DATE_YEAR_FIRST = r"[0-9]{4}[-/.]" + _MONTH + r"[-/.]" + _DAY + _TIME + "?"
# Day and month first in either order (3/15/2024 or 15.03.24), optionally with a time.
DATE_NUMERIC = (
    "(" + _MONTH + r"[-/.]" + _DAY + "|" + _DAY + r"[-/.]" + _MONTH + ")"
    r"[-/.]([0-9]{4}|[0-9]{2})" + _TIME + "?"
)
# Dates with month names: 15 Mar 2024, 15-Mar-24, March 15, 2024, Mon, Mar 4 2024.
DATE_TEXT = (
    r"(?i)(([a-z]+,?\s+)?" + _MONTH_NAME + r"\s+" + _DAY + r"(st|nd|rd|th)?,?\s+[0-9]{4}"
    r"|"
    + _DAY
    + r"(st|nd|rd|th)?[\s-]+"
    + _MONTH_NAME
    + r"[\s,-]+([0-9]{4}|[0-9]{2}))"
    + _TIME
    + "?"
)
HAS_TIME = r".*[0-9]{1,2}:[0-9]{2}.*"

EMAIL = r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
URL = r"(?i)(https?://|www\.)[^\s]+"
# A phone number with visible formatting: +, parentheses, or separators between
# digit groups. Plain digit strings are handled separately because they are
# indistinguishable from other long numbers.
PHONE_FORMATTED = (
    r"(\+\s?)?(\([0-9]{1,4}\)\s?[0-9]{1,5}|[0-9]{1,5})([\s.-]\(?[0-9]{1,5}\)?){1,5}"
    r"(\s?(x|ext\.?)\s?[0-9]{1,6})?"
)
PHONE_DIGITS_ONLY = r"[-+]?[0-9]{7,15}"
PHONE_MIN_DIGITS = 7
PHONE_MAX_DIGITS = 15

BOOLEAN_TOKEN = r"(?i)(true|false|yes|no|y|n|t|f)"
ZERO_ONE = r"[01]"

# Text people type when a value is missing.
PLACEHOLDER = (
    r"(?i)(n/?a|#n/?a|na|null|none|nil|nan|-+|\?+|\.+|unknown|tbd|tba|missing"
    r"|not available|not applicable|blank|empty)"
)

# Candidate separators for values that pack two things into one cell.
DELIMITERS: dict[str, str] = {
    "-": r"[^-]+-[^-]+",
    "/": r"[^/]+/[^/]+",
    "|": r"[^|]+\|[^|]+",
    ";": r"[^;]+;[^;]+",
    ":": r"[^:]+:[^:]+",
    "_": r"[^_]+_[^_]+",
}

# Date formats the app understands, in strptime syntax. Shared by profiling (to
# find date ranges) and by the parse_date step, which only accepts these.
DateFormat = Literal[
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%m/%d/%y",
    "%d/%m/%y",
    "%d %b %Y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
]
DATE_FORMATS: tuple[str, ...] = get_args(DateFormat)

LETTER_RUN = r"[A-Za-z]+"
DIGIT_RUN = r"[0-9]+"

_COMPILED: dict[str, re.Pattern[str]] = {}


def full_match(pattern: str, value: str) -> bool:
    compiled = _COMPILED.get(pattern)
    if compiled is None:
        compiled = re.compile(pattern)
        _COMPILED[pattern] = compiled
    return compiled.fullmatch(value) is not None


def looks_typed(value: str) -> bool:
    """True when a value reads as a number or a date rather than a label."""
    v = value.strip()
    return any(full_match(p, v) for p in (LENIENT_NUMBER, DATE_YEAR_FIRST, DATE_NUMERIC, DATE_TEXT))


def value_shape(value: str) -> str:
    """Letters become A and digits become 9, keeping length: 'EMP1000' -> 'AAA9999'."""
    return re.sub(r"[0-9]", "9", re.sub(r"[A-Za-z]", "A", value))
