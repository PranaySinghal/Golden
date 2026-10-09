"""Which columns a connector could fill from, judged by what the values look like.

Evidence comes from the values: their shape, how often they repeat, and (for
companies and stock symbols) how many of them appear in the public companies
list once we hold a copy. Words in a column's name only ever tip a close call,
the way `profile/name_hints.py` uses them: they are never needed and never
enough.

Runs against the cleaned table, so a column an earlier lookup created (a
"Ticker" column, say) can be the start of the next one.
"""

from dataclasses import dataclass

import duckdb

from app.connectors.matching import CompanyIndex
from app.connectors.normalize import (
    COMPANY_ENDING_PATTERN,
    LEGAL_ENDING_PATTERN,
    POSTAL_FORMATS,
    TICKER_PATTERN,
    company_key,
)
from app.db import quote_ident, work_ref
from app.profile.name_hints import name_words
from app.steps.apply import CLEANED_TABLE, OutputColumn
from app.steps.schema import ValueKind, blank_predicate, text_of

# Share of filled values that must have the shape before it counts as the shape.
SHAPE_SHARE = 0.9
# An id is different on every row; a postal code or a company repeats, or at
# least could. Above this share of different values, shape alone isn't enough.
MOSTLY_UNIQUE = 0.9
# All-digit codes with no leading zero and no telling name look like any other
# repeated number: batch numbers, round quantities, account codes. They count
# as postal codes only when there are enough different ones, spread across
# areas the way addresses are, and not round numbers the way quantities are.
MIN_DIGIT_CODES = 8
MIN_AREA_SPREAD = 0.5
MAX_ROUND_SHARE = 0.2
COMPANY_ENDING_SHARE = 0.2
COMPANY_LISTED_SHARE = 0.3
TICKER_LISTED_SHARE = 0.5
# With a name that points the same way, weaker evidence from the values will do.
HINTED_ENDING_SHARE = 0.05
HINTED_LISTED_SHARE = 0.1
MIN_VALUES = 2
MAX_COLUMNS = 80
TOP_VALUES = 200

_POSTAL_WORDS = {"zip", "zipcode", "postal", "postcode", "pincode", "plz"}
_COMPANY_WORDS = {"company", "organisation", "organization", "issuer", "employer", "firm"}
_TICKER_WORDS = {"ticker", "symbol"}


@dataclass(frozen=True)
class Offer:
    connector: str
    column: str
    distinct_values: int
    # For postal codes: the countries whose codes look like these, to choose from.
    countries: tuple[str, ...] = ()


@dataclass(frozen=True)
class ColumnShape:
    """What one column's values look like. Everything detection decides from."""

    name: str
    filled: int
    distinct: int
    leading_zeros: int
    postal: dict[str, int]  # country -> values with that country's shape
    ticker_shaped: int
    company_endings: int
    # Endings only a registered company carries (Inc, Ltd, LLC), not "Group" or "Co".
    legal_endings: int
    # Among all-digit values: how many different first-three-digit areas, and
    # how many values are round numbers.
    areas: int
    round_numbers: int
    top_values: tuple[str, ...]


def measure(
    conn: duckdb.DuckDBPyConnection, column: str, kind: ValueKind = ValueKind.TEXT
) -> ColumnShape:
    # Codes that were read as numbers are judged by how they are written.
    ident = f"CAST({text_of(quote_ident(column), kind)} AS VARCHAR)"
    patterns = {f"p{i}": fmt.pattern for i, fmt in enumerate(POSTAL_FORMATS)}
    postal_counts = ", ".join(f"count_if(regexp_full_match(t, ${name}))" for name in patterns)
    values = (
        f"SELECT upper(trim({ident})) AS t, {ident} AS raw FROM {work_ref(CLEANED_TABLE)} "
        f"WHERE NOT {blank_predicate(ident, ValueKind.TEXT)}"
    )
    row = conn.execute(
        f"WITH v AS ({values}) SELECT count(*), count(DISTINCT t), "
        f"count_if(starts_with(t, '0')), count_if(regexp_full_match(t, $ticker)), "
        f"count_if(regexp_matches(raw, $ending)), count_if(regexp_matches(raw, $legal)), "
        f"count(DISTINCT left(t, 3)) FILTER (WHERE regexp_full_match(t, '[0-9]+')), "
        f"count_if(regexp_full_match(t, '[0-9]*00')), {postal_counts} FROM v",
        {
            "ticker": TICKER_PATTERN,
            "ending": COMPANY_ENDING_PATTERN,
            "legal": LEGAL_ENDING_PATTERN,
            **patterns,
        },
    ).fetchone()
    assert row is not None
    # Counting over no rows at all gives nothing rather than zero.
    counts = [int(value or 0) for value in row]
    top = conn.execute(
        f"WITH v AS ({values}) SELECT any_value(trim(raw)) FROM v GROUP BY t "
        f"ORDER BY count(*) DESC, t LIMIT {TOP_VALUES}"
    ).fetchall()
    return ColumnShape(
        name=column,
        filled=counts[0],
        distinct=counts[1],
        leading_zeros=counts[2],
        ticker_shaped=counts[3],
        company_endings=counts[4],
        legal_endings=counts[5],
        areas=counts[6],
        round_numbers=counts[7],
        postal={fmt.country: counts[8 + i] for i, fmt in enumerate(POSTAL_FORMATS)},
        top_values=tuple(str(value[0]) for value in top),
    )


def offers_for(shape: ColumnShape, companies: CompanyIndex | None) -> list[Offer]:
    """Every connector this column's values could feed. Pure: facts in, offers out."""
    if shape.filled < MIN_VALUES:
        return []
    words = set(name_words(shape.name))
    offers: list[Offer] = []

    countries = _postal_countries(shape, hinted=bool(words & _POSTAL_WORDS))
    if countries:
        offers.append(Offer("postal_geocode", shape.name, shape.distinct, countries))

    listed = _listed_share(shape, companies)
    if _is_ticker(shape, listed, hinted=bool(words & _TICKER_WORDS)):
        offers.append(Offer("stock_price", shape.name, shape.distinct))
    elif _is_company(shape, listed, hinted=bool(words & _COMPANY_WORDS)):
        offers.append(Offer("company_ticker", shape.name, shape.distinct))
    return offers


def _postal_countries(shape: ColumnShape, hinted: bool) -> tuple[str, ...]:
    repeats = shape.distinct / shape.filled < MOSTLY_UNIQUE
    fitting = []
    for fmt in POSTAL_FORMATS:
        if shape.postal[fmt.country] / shape.filled < SHAPE_SHARE:
            continue
        has_letters = "A-Z" in fmt.pattern
        if fmt.weak_shape:
            # Four digits is a year or a count far more often than a postal code.
            evidence = hinted
        elif has_letters:
            # "K1A 0B1" and "SW1A 1AA" aren't the shape of anything else.
            evidence = True
        else:
            # Five or six digits could be an id, a batch number or a quantity.
            # A leading zero settles it, and so does a telling name. Without
            # either, the values have to behave like addresses.
            like_addresses = (
                repeats
                and shape.distinct >= MIN_DIGIT_CODES
                and shape.areas / shape.distinct >= MIN_AREA_SPREAD
                and shape.round_numbers / shape.filled <= MAX_ROUND_SHARE
            )
            evidence = shape.leading_zeros > 0 or hinted or like_addresses
        if evidence:
            fitting.append(fmt.country)
    return tuple(fitting)


def _listed_share(shape: ColumnShape, companies: CompanyIndex | None) -> tuple[float, float] | None:
    """Share of the most common values that are a listed (name, symbol). None without a list."""
    if companies is None or not shape.top_values:
        return None
    symbols = {company.ticker for listed in companies.values() for company in listed}
    named = sum(1 for value in shape.top_values if company_key(value) in companies)
    symbolled = sum(1 for value in shape.top_values if value.upper() in symbols)
    return named / len(shape.top_values), symbolled / len(shape.top_values)


def _is_ticker(shape: ColumnShape, listed: tuple[float, float] | None, hinted: bool) -> bool:
    if shape.ticker_shaped / shape.filled < SHAPE_SHARE:
        return False
    if listed is None:
        # One to five capitals is also a country, a state or a grade. Without
        # the list to check against, the shape needs the name to agree.
        return hinted
    return listed[1] >= (HINTED_LISTED_SHARE if hinted else TICKER_LISTED_SHARE)


def _is_company(shape: ColumnShape, listed: tuple[float, float] | None, hinted: bool) -> bool:
    names = listed[0] if listed is not None else 0.0
    if hinted:
        any_ending = shape.company_endings / shape.filled
        return any_ending >= HINTED_ENDING_SHARE or names >= HINTED_LISTED_SHARE
    return (
        shape.legal_endings / shape.filled >= COMPANY_ENDING_SHARE or names >= COMPANY_LISTED_SHARE
    )


def find_offers(
    conn: duckdb.DuckDBPyConnection,
    columns: list[OutputColumn],
    companies: CompanyIndex | None,
) -> list[Offer]:
    offers: list[Offer] = []
    readable = [c for c in columns if c.kind in (ValueKind.TEXT, ValueKind.NUMBER)]
    for column in readable[:MAX_COLUMNS]:
        offers.extend(offers_for(measure(conn, column.name, column.kind), companies))
    return offers
