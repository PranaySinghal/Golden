"""Collect value statistics for one column of the raw table, entirely in SQL.

Only aggregates and a handful of top values come back to Python, so profiling
stays cheap on large files.
"""

from dataclasses import dataclass, field

import duckdb

from app.db import RAW_REF, quote_ident
from app.profile import patterns as p
from app.profile.patterns import DATE_FORMATS

# Share of filled values that must look like dates before min/max is worth computing.
_DATE_RANGE_MIN_SHARE = 0.5


@dataclass(frozen=True)
class ColumnStats:
    name: str
    position: int
    row_count: int
    non_blank: int = 0
    distinct: int = 0
    avg_length: float = 0.0
    with_whitespace: int = 0
    integer: int = 0
    decimal: int = 0
    plain_number: int = 0
    lenient_number: int = 0
    with_fraction: int = 0
    currency: int = 0
    percent: int = 0
    thousands_separator: int = 0
    leading_zeros: int = 0
    date_year_first: int = 0
    date_numeric: int = 0
    date_text: int = 0
    date_with_time: int = 0
    email: int = 0
    url: int = 0
    phone_formatted: int = 0
    phone_digits: int = 0
    boolean_token: int = 0
    boolean_distinct: int = 0
    zero_one: int = 0
    zero_one_distinct: int = 0
    placeholder: int = 0
    placeholder_examples: list[str] = field(default_factory=list)
    code_shape_count: int = 0
    code_shape_has_digit: bool = False
    code_shape_example: str | None = None
    integer_width: int | None = None
    integer_width_count: int = 0
    integer_min: float | None = None
    integer_max: float | None = None
    number_min: float | None = None
    number_max: float | None = None
    date_min: str | None = None
    date_max: str | None = None
    delimiter_counts: dict[str, int] = field(default_factory=dict)
    top_values: list[tuple[str, int]] = field(default_factory=list)

    @property
    def date_any(self) -> int:
        return self.date_year_first + self.date_numeric + self.date_text


def count_rows(conn: duckdb.DuckDBPyConnection, table: str = RAW_REF) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    return int(row[0]) if row else 0


def compute_column_stats(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    position: int,
    row_count: int,
    table: str = RAW_REF,
) -> ColumnStats:
    """`name` must be a column of `table`; callers take it from that table's schema.

    `table` is the raw table unless a caller is profiling columns a recipe
    produced, which it stores as text so the same rules apply.
    """
    source = _filled_values_cte(name, table)
    params = _pattern_params()

    main = conn.execute(
        source + _MAIN_SELECT.format(delims=_delimiter_selects()), params
    ).fetchone()
    assert main is not None  # an aggregate query always returns one row
    (
        non_blank,
        distinct,
        avg_length,
        with_whitespace,
        integer,
        decimal,
        plain_number,
        lenient_number,
        with_fraction,
        currency,
        percent,
        thousands_separator,
        leading_zeros,
        date_year_first,
        date_numeric,
        date_text,
        date_with_time,
        email,
        url,
        phone_formatted,
        phone_digits,
        boolean_token,
        boolean_distinct,
        zero_one,
        zero_one_distinct,
        placeholder,
        integer_min,
        integer_max,
        number_min,
        number_max,
        *delimiter_values,
    ) = main

    if non_blank == 0:
        return ColumnStats(name=name, position=position, row_count=row_count)

    shape = conn.execute(source + _SHAPE_SELECT).fetchone()
    width = conn.execute(source + _WIDTH_SELECT, {"integer": p.INTEGER}).fetchone()
    top = conn.execute(source + _TOP_VALUES_SELECT).fetchall()
    placeholders = (
        conn.execute(source + _PLACEHOLDER_SELECT, {"placeholder": p.PLACEHOLDER}).fetchall()
        if placeholder
        else []
    )
    date_min = date_max = None
    if (date_year_first + date_numeric + date_text) / non_blank >= _DATE_RANGE_MIN_SHARE:
        date_min, date_max = _date_range(conn, source)

    return ColumnStats(
        name=name,
        position=position,
        row_count=row_count,
        non_blank=non_blank,
        distinct=distinct,
        avg_length=float(avg_length or 0.0),
        with_whitespace=with_whitespace,
        integer=integer,
        decimal=decimal,
        plain_number=plain_number,
        lenient_number=lenient_number,
        with_fraction=with_fraction,
        currency=currency,
        percent=percent,
        thousands_separator=thousands_separator,
        leading_zeros=leading_zeros,
        date_year_first=date_year_first,
        date_numeric=date_numeric,
        date_text=date_text,
        date_with_time=date_with_time,
        email=email,
        url=url,
        phone_formatted=phone_formatted,
        phone_digits=phone_digits,
        boolean_token=boolean_token,
        boolean_distinct=boolean_distinct,
        zero_one=zero_one,
        zero_one_distinct=zero_one_distinct,
        placeholder=placeholder,
        placeholder_examples=[str(row[0]) for row in placeholders],
        code_shape_count=int(shape[1]) if shape else 0,
        code_shape_has_digit=bool(shape and "9" in str(shape[0])),
        code_shape_example=p.value_shape(str(shape[2])) if shape else None,
        integer_width=int(width[0]) if width else None,
        integer_width_count=int(width[1]) if width else 0,
        integer_min=integer_min,
        integer_max=integer_max,
        number_min=number_min,
        number_max=number_max,
        date_min=date_min,
        date_max=date_max,
        delimiter_counts=dict(zip(p.DELIMITERS, delimiter_values, strict=True)),
        top_values=[(str(value), int(count)) for value, count in top],
    )


def _filled_values_cte(name: str, table: str = RAW_REF) -> str:
    col = quote_ident(name)
    # `raw` keeps the value exactly as stored; `t` is trimmed for pattern checks.
    return (
        "WITH vals AS ("
        f"  SELECT {col} AS raw, regexp_replace({col}, '^\\s+|\\s+$', '', 'g') AS t"
        f"  FROM {table}"
        "), nb AS (SELECT raw, t FROM vals WHERE t IS NOT NULL AND t <> '') "
    )


def _pattern_params() -> dict[str, str]:
    params = {
        "integer": p.INTEGER,
        "decimal": p.DECIMAL,
        "plain_number": p.PLAIN_NUMBER,
        "lenient_number": p.LENIENT_NUMBER,
        "currency": p.CURRENCY,
        "percent": p.PERCENT,
        "thousands": p.THOUSANDS_SEPARATOR,
        "leading_zeros": p.LEADING_ZEROS,
        "date_year_first": p.DATE_YEAR_FIRST,
        "date_numeric": p.DATE_NUMERIC,
        "date_text": p.DATE_TEXT,
        "has_time": p.HAS_TIME,
        "email": p.EMAIL,
        "url": p.URL,
        "phone_formatted": p.PHONE_FORMATTED,
        "phone_digits": p.PHONE_DIGITS_ONLY,
        "boolean": p.BOOLEAN_TOKEN,
        "zero_one": p.ZERO_ONE,
        "placeholder": p.PLACEHOLDER,
    }
    for index, pattern in enumerate(p.DELIMITERS.values()):
        params[f"delim_{index}"] = pattern
    return params


def _delimiter_selects() -> str:
    return "".join(
        f", count_if(regexp_full_match(t, $delim_{index}))" for index in range(len(p.DELIMITERS))
    )


_MAIN_SELECT = """
, flagged AS (
  SELECT raw, t,
    regexp_full_match(t, $integer) AS is_integer,
    regexp_full_match(t, $decimal) AS is_decimal,
    regexp_full_match(t, $plain_number) AS is_plain,
    regexp_full_match(t, $lenient_number) AS is_lenient,
    regexp_full_match(t, $date_year_first) AS is_date_year_first,
    regexp_full_match(t, $date_numeric) AS is_date_numeric,
    regexp_full_match(t, $date_text) AS is_date_text,
    regexp_full_match(t, $boolean) AS is_boolean,
    regexp_full_match(t, $zero_one) AS is_zero_one,
    length(regexp_replace(t, '[^0-9]', '', 'g')) AS digit_count
  FROM nb
), parsed AS (
  SELECT *,
    is_date_year_first OR is_date_numeric OR is_date_text AS is_date,
    CASE WHEN is_lenient THEN
      (CASE WHEN starts_with(t, '(') AND ends_with(t, ')') THEN -1 ELSE 1 END)
      * TRY_CAST(regexp_replace(t, '[$€£¥₹,%()\\s]', '', 'g') AS DOUBLE)
    END AS lenient_value
  FROM flagged
)
SELECT
  count(*),
  count(DISTINCT raw),
  avg(length(raw)),
  count_if(regexp_matches(t, '\\s')),
  count_if(is_integer),
  count_if(is_decimal),
  count_if(is_plain),
  count_if(is_lenient),
  count_if(is_lenient AND regexp_matches(t, '\\.[0-9]')),
  count_if(is_lenient AND regexp_full_match(t, $currency)),
  count_if(is_lenient AND regexp_full_match(t, $percent)),
  count_if(is_lenient AND regexp_full_match(t, $thousands)),
  count_if(regexp_full_match(t, $leading_zeros)),
  count_if(is_date_year_first),
  count_if(is_date_numeric AND NOT is_date_year_first),
  count_if(is_date_text AND NOT is_date_year_first AND NOT is_date_numeric),
  count_if(is_date AND regexp_full_match(t, $has_time)),
  count_if(regexp_full_match(t, $email)),
  count_if(regexp_full_match(t, $url)),
  count_if(regexp_full_match(t, $phone_formatted) AND NOT is_plain AND NOT is_date
           AND digit_count BETWEEN 7 AND 15),
  count_if(regexp_full_match(t, $phone_digits)),
  count_if(is_boolean),
  count(DISTINCT lower(t)) FILTER (WHERE is_boolean),
  count_if(is_zero_one),
  count(DISTINCT t) FILTER (WHERE is_zero_one),
  count_if(regexp_full_match(t, $placeholder)),
  min(TRY_CAST(t AS DOUBLE)) FILTER (WHERE is_integer),
  max(TRY_CAST(t AS DOUBLE)) FILTER (WHERE is_integer),
  min(lenient_value),
  max(lenient_value)
  {delims}
FROM parsed
"""

# Letter runs become A and digit runs become 9, so EMP1000 and EMP10000 share
# a shape. The example is re-shaped in Python without collapsing runs.
_SHAPE_SELECT = """
SELECT regexp_replace(regexp_replace(t, '[A-Za-z]+', 'A', 'g'), '[0-9]+', '9', 'g') AS shape,
       count(*) AS n, min(t) AS example
FROM nb GROUP BY shape ORDER BY n DESC, shape LIMIT 1
"""

_WIDTH_SELECT = """
SELECT length(regexp_replace(t, '^[-+]', '')) AS width, count(*) AS n
FROM nb WHERE regexp_full_match(t, $integer)
GROUP BY width ORDER BY n DESC, width DESC LIMIT 1
"""

_TOP_VALUES_SELECT = """
SELECT raw, count(*) AS n FROM nb GROUP BY raw ORDER BY n DESC, raw LIMIT 5
"""

_PLACEHOLDER_SELECT = """
SELECT t, count(*) AS n FROM nb WHERE regexp_full_match(t, $placeholder)
GROUP BY t ORDER BY n DESC, t LIMIT 3
"""


def _date_range(conn: duckdb.DuckDBPyConnection, source: str) -> tuple[str | None, str | None]:
    """Earliest and latest date, using the format that reads the most values.

    When several formats read equally many values (for example every day is 12
    or less, so month/day and day/month both work) and they disagree about the
    range, the order is ambiguous and no range is reported rather than guessing.
    """
    params = {f"f{index}": fmt for index, fmt in enumerate(DATE_FORMATS)}
    counts_sql = ", ".join(
        f"count(try_strptime(t, $f{index}))" for index in range(len(DATE_FORMATS))
    )
    counts = conn.execute(source + f"SELECT {counts_sql} FROM nb", params).fetchone()
    if counts is None or max(counts) == 0:
        return None, None
    best = max(counts)
    tied = [fmt for count, fmt in zip(counts, DATE_FORMATS, strict=True) if count == best]
    ranges = {_range_for_format(conn, source, fmt) for fmt in tied}
    if len(ranges) != 1:
        return None, None
    return ranges.pop()


def _range_for_format(
    conn: duckdb.DuckDBPyConnection, source: str, fmt: str
) -> tuple[str | None, str | None]:
    row = conn.execute(
        source + "SELECT min(d), max(d), bool_and(d::TIME = TIME '00:00:00') "
        "FROM (SELECT try_strptime(t, $fmt) AS d FROM nb) WHERE d IS NOT NULL",
        {"fmt": fmt},
    ).fetchone()
    if row is None or row[0] is None:
        return None, None
    earliest, latest, date_only = row
    if date_only:
        return earliest.date().isoformat(), latest.date().isoformat()
    return earliest.isoformat(sep=" "), latest.isoformat(sep=" ")
