"""Patterns run in two engines (Python for header detection, DuckDB for profiling).

Each case is checked in both, so the engines can't quietly disagree.
"""

import duckdb
import pytest

from app.profile import patterns as p
from app.profile.name_hints import NameHint, name_hint, name_words

CASES: list[tuple[str, str, bool]] = [
    (p.INTEGER, "42", True),
    (p.INTEGER, "-7", True),
    (p.INTEGER, "4.2", False),
    (p.DECIMAL, "4.20", True),
    (p.DECIMAL, ".5", True),
    (p.DECIMAL, "12", False),
    (p.PLAIN_NUMBER, "1e5", True),
    (p.PLAIN_NUMBER, "-0.25", True),
    (p.PLAIN_NUMBER, "$5", False),
    (p.PLAIN_NUMBER, "1,200", False),
    (p.LENIENT_NUMBER, "$1,200.50", True),
    (p.LENIENT_NUMBER, "€85", True),
    (p.LENIENT_NUMBER, "(35.10)", True),
    (p.LENIENT_NUMBER, "15%", True),
    (p.LENIENT_NUMBER, "-$4", True),
    (p.LENIENT_NUMBER, "12,34", False),
    (p.LENIENT_NUMBER, "N/A", False),
    (p.LENIENT_NUMBER, "abc", False),
    (p.LEADING_ZEROS, "02134", True),
    (p.LEADING_ZEROS, "0", False),
    (p.LEADING_ZEROS, "2134", False),
    (p.DATE_YEAR_FIRST, "2024-03-15", True),
    (p.DATE_YEAR_FIRST, "2024/3/5", True),
    (p.DATE_YEAR_FIRST, "2024-03-15T09:30:00Z", True),
    (p.DATE_YEAR_FIRST, "2024-13-01", False),
    (p.DATE_NUMERIC, "4/2/2021", True),
    (p.DATE_NUMERIC, "15/03/2024", True),
    (p.DATE_NUMERIC, "15.03.24", True),
    (p.DATE_NUMERIC, "12/7/2023 14:05", True),
    (p.DATE_NUMERIC, "13/13/2024", False),
    (p.DATE_NUMERIC, "20240315", False),
    (p.DATE_TEXT, "15 Mar 2024", True),
    (p.DATE_TEXT, "15-Mar-24", True),
    (p.DATE_TEXT, "March 5, 2024", True),
    (p.DATE_TEXT, "Tue, Mar 5 2024", True),
    (p.DATE_TEXT, "Marketing 2024", False),
    (p.EMAIL, "bob.davis@example.com", True),
    (p.EMAIL, "o'neil+tag@mail.co.uk", True),
    (p.EMAIL, "bob.davis@example", False),
    (p.EMAIL, "not an email", False),
    (p.URL, "https://example.com/a", True),
    (p.URL, "www.example.com", True),
    (p.URL, "example.com", False),
    (p.PHONE_FORMATTED, "(415) 555-0134", True),
    (p.PHONE_FORMATTED, "+44 20 7946 0958", True),
    (p.PHONE_FORMATTED, "415.555.0134", True),
    (p.PHONE_FORMATTED, "415-555-0134 x12", True),
    (p.PHONE_FORMATTED, "4155550134", False),
    (p.PHONE_DIGITS_ONLY, "-1651623197", True),
    (p.PHONE_DIGITS_ONLY, "123456", False),
    (p.BOOLEAN_TOKEN, "TRUE", True),
    (p.BOOLEAN_TOKEN, "yes", True),
    (p.BOOLEAN_TOKEN, "N", True),
    (p.BOOLEAN_TOKEN, "maybe", False),
    (p.PLACEHOLDER, "N/A", True),
    (p.PLACEHOLDER, "#N/A", True),
    (p.PLACEHOLDER, "null", True),
    (p.PLACEHOLDER, "-", True),
    (p.PLACEHOLDER, "?", True),
    (p.PLACEHOLDER, "Not Available", True),
    (p.PLACEHOLDER, "Nancy", False),
    (p.PLACEHOLDER, "-5", False),
    (p.DELIMITERS["-"], "Cloud Tech-Florida", True),
    (p.DELIMITERS["-"], "a-b-c", False),
    (p.DELIMITERS["|"], "x|y", True),
]


@pytest.fixture(scope="module")
def duck() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


@pytest.mark.parametrize(("pattern", "value", "expected"), CASES)
def test_pattern_in_python(pattern: str, value: str, expected: bool) -> None:
    assert p.full_match(pattern, value) is expected


@pytest.mark.parametrize(("pattern", "value", "expected"), CASES)
def test_pattern_in_duckdb(
    duck: duckdb.DuckDBPyConnection, pattern: str, value: str, expected: bool
) -> None:
    row = duck.execute("SELECT regexp_full_match($v, $p)", {"v": value, "p": pattern}).fetchone()
    assert row is not None
    assert row[0] is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("25", True), ("$1,000", True), ("2024-01-01", True), ("3 Mar 2024", True), ("Age", False)],
)
def test_looks_typed(value: str, expected: bool) -> None:
    assert p.looks_typed(value) is expected


def test_value_shape() -> None:
    assert p.value_shape("EMP-1000x") == "AAA-9999A"


@pytest.mark.parametrize(
    ("name", "words"),
    [
        ("Employee_ID", ["employee", "id"]),
        ("customerPhoneNumber", ["customer", "phone", "number"]),
        ("Order No.", ["order", "no"]),
        ("col_1", ["col"]),
    ],
)
def test_name_words(name: str, words: list[str]) -> None:
    assert name_words(name) == words


@pytest.mark.parametrize(
    ("name", "hint"),
    [
        ("Phone", NameHint.PHONE),
        ("Mobile No", NameHint.PHONE),
        ("Employee_ID", NameHint.IDENTIFIER),
        ("SKU", NameHint.IDENTIFIER),
        ("Salary", None),
        # Substrings don't count: "valid" contains "id" but isn't an ID.
        ("Valid", None),
        ("Telescope", None),
        ("column_3", None),
    ],
)
def test_name_hint(name: str, hint: NameHint | None) -> None:
    assert name_hint(name) is hint
