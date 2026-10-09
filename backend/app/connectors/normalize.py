"""Turning a cell into the thing a service is asked about. Pure.

Each kind of value has a strict shape. A value that doesn't fit is never sent
anywhere: it is "not found" without a call, which also means nothing but a
well-formed postal code or stock symbol can end up in a request.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class PostalFormat:
    country: str  # ISO 3166-1 alpha-2
    name: str
    # Matched against the whole value, trimmed and in capitals.
    pattern: str
    # The part of the code the lookup service indexes.
    to_query: Callable[[str], str]
    # Short all-digit codes look like years, counts and ids. On their own they
    # aren't evidence of a postal code.
    weak_shape: bool = False


def _whole(code: str) -> str:
    return code


_FIVE_DIGITS = r"[0-9]{5}"

POSTAL_FORMATS: tuple[PostalFormat, ...] = (
    PostalFormat("US", "United States", r"[0-9]{5}(-[0-9]{4})?", lambda code: code[:5]),
    PostalFormat("CA", "Canada", r"[A-Z][0-9][A-Z] ?[0-9][A-Z][0-9]", lambda code: code[:3]),
    PostalFormat(
        "GB",
        "United Kingdom",
        r"[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][A-Z]{2}",
        lambda code: code.replace(" ", "")[:-3],
    ),
    PostalFormat("DE", "Germany", _FIVE_DIGITS, _whole),
    PostalFormat("FR", "France", _FIVE_DIGITS, _whole),
    PostalFormat("ES", "Spain", _FIVE_DIGITS, _whole),
    PostalFormat("IT", "Italy", _FIVE_DIGITS, _whole),
    PostalFormat("MX", "Mexico", _FIVE_DIGITS, _whole),
    PostalFormat("IN", "India", r"[0-9]{6}", _whole),
    PostalFormat("AU", "Australia", r"[0-9]{4}", _whole, weak_shape=True),
)
POSTAL_BY_COUNTRY = {fmt.country: fmt for fmt in POSTAL_FORMATS}


def clean(value: str) -> str:
    return " ".join(value.split()).upper()


def postal_query(country: str, value: str) -> str | None:
    """What to ask the service for this code, or None if it isn't one for that country."""
    fmt = POSTAL_BY_COUNTRY.get(country.upper())
    code = clean(value)
    if fmt is None or not re.fullmatch(fmt.pattern, code):
        return None
    return fmt.to_query(code)


TICKER_PATTERN = r"[A-Z]{1,5}([.\-][A-Z]{1,2})?"


def ticker_query(value: str) -> str | None:
    symbol = clean(value)
    return symbol if re.fullmatch(TICKER_PATTERN, symbol) else None


# Words that say what kind of company it is, not which one.
COMPANY_ENDINGS = frozenset(
    {
        "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
        "llc", "lp", "llp", "sa", "ag", "nv", "se", "holdings", "group",
    }
)  # fmt: skip
# Endings that are ordinary words too. "Garden Group" is a product line and
# "Supply Co" a shop sign; on their own they don't make a column a list of companies.
WEAK_COMPANY_ENDINGS = frozenset({"co", "company", "group", "holdings"})


def _ending_pattern(endings: frozenset[str]) -> str:
    return r"(?i)\b(" + "|".join(sorted(endings)) + r")\.?\s*$"


# For spotting company names in SQL: the same endings, as a whole last word.
COMPANY_ENDING_PATTERN = _ending_pattern(COMPANY_ENDINGS)
LEGAL_ENDING_PATTERN = _ending_pattern(COMPANY_ENDINGS - WEAK_COMPANY_ENDINGS)
_STATE_MARKER = re.compile(r"\s*/[a-z]{2,3}/?\s*$")
_NOT_WORD = re.compile(r"[^a-z0-9]+")


def company_key(name: str) -> str:
    """A company's name with everything that varies between spellings removed.

    "Apple Inc.", "APPLE INC" and "Apple, Incorporated" all become "apple". The
    official list also writes where some companies are registered ("/DE/").
    """
    lowered = _STATE_MARKER.sub("", name.lower().replace("&", " and "))
    words = [word for word in _NOT_WORD.split(lowered.replace("'", "")) if word]
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    while len(words) > 1 and words[-1] in COMPANY_ENDINGS:
        words = words[:-1]
    return " ".join(words)
