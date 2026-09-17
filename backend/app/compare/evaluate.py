"""Answer a question with one aggregate SQL query, under either reading."""

import re
from collections.abc import Mapping
from typing import Any

import duckdb

from app.compare.reading import ColumnReading, Reading
from app.questions.models import Answer, DateGrain, GroupValue, Measure, Question

# Groups returned per answer; any beyond this are rolled into one "other" group in
# SQL, so a column with many values never pulls a big result into Python.
MAX_GROUPS = 1000
OTHER_KEY = "__other__"
_PARAM = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def evaluate(conn: duckdb.DuckDBPyConnection, question: Question, reading: Reading) -> Answer:
    columns: dict[str, ColumnReading] = {}
    for name in question.columns:
        column = reading.column(name)
        if column is None:
            return Answer(answerable=False, note=f'There\'s no column called "{name}".')
        columns[name] = column

    source = reading.rows()
    params: dict[str, object] = {**reading.params(), **source.params}
    where = "TRUE"
    if question.filter is not None:
        where = f"{columns[question.filter.column].key} = lower($filter_value)"
        params["filter_value"] = question.filter.equals

    if question.group_by is None:
        return _scalar(conn, question, columns, source.sql, where, params)
    return _grouped(conn, question, columns, source.sql, where, params)


def _run(
    conn: duckdb.DuckDBPyConnection, sql: str, params: Mapping[str, object]
) -> list[tuple[Any, ...]]:
    # DuckDB rejects parameters a statement doesn't use, so bind only those it names.
    used = set(_PARAM.findall(sql))
    return conn.execute(sql, {k: v for k, v in params.items() if k in used}).fetchall()


def _value_sql(question: Question, columns: dict[str, ColumnReading]) -> tuple[str, str]:
    """(aggregate, count of values it used) for the question's measure."""
    match question.measure:
        case Measure.COUNT:
            return "CAST(count(*) AS DOUBLE)", "count(*)"
        case Measure.COUNT_DISTINCT:
            key = columns[question.column or ""].key
            return f"CAST(count(DISTINCT {key}) AS DOUBLE)", f"count({key})"
        case Measure.SUM:
            number = columns[question.column or ""].number
            return f"sum({number})", f"count({number})"
        case Measure.AVG:
            number = columns[question.column or ""].number
            return f"avg({number})", f"count({number})"


def _skipped_sql(question: Question, columns: dict[str, ColumnReading], used: str) -> str:
    if question.measure in (Measure.SUM, Measure.AVG):
        filled = columns[question.column or ""].filled
        return f"count_if({filled}) - {used}"
    return "0"


def _scalar(
    conn: duckdb.DuckDBPyConnection,
    question: Question,
    columns: dict[str, ColumnReading],
    source: str,
    where: str,
    params: dict[str, object],
) -> Answer:
    value, used = _value_sql(question, columns)
    skipped = _skipped_sql(question, columns, used)
    row = _run(
        conn,
        f"SELECT {value}, {used}, {skipped} FROM {source} AS rows WHERE {where}",
        params,
    )[0]
    result, rows_used, rows_skipped = row
    answerable = question.measure is Measure.COUNT or int(rows_used or 0) > 0
    return Answer(
        answerable=answerable,
        value=float(result) if answerable and result is not None else None,
        rows_used=int(rows_used or 0),
        rows_skipped=int(rows_skipped or 0),
        note=None if answerable else _unreadable_note(question),
    )


def _unreadable_note(question: Question) -> str:
    if question.measure in (Measure.SUM, Measure.AVG):
        return f'No "{question.column}" values could be read as numbers.'
    return f'"{question.column}" has no values.'


def _grouped(
    conn: duckdb.DuckDBPyConnection,
    question: Question,
    columns: dict[str, ColumnReading],
    source: str,
    where: str,
    params: dict[str, object],
) -> Answer:
    group = columns[question.group_by or ""]
    if question.grain is not None:
        pattern = "%Y-%m" if question.grain is DateGrain.MONTH else "%Y"
        unit = question.grain.value
        key = f"strftime(date_trunc('{unit}', {group.date}), '{pattern}')"
        label = key
        placed = f"{group.date} IS NOT NULL"
    else:
        key, label, placed = group.key, group.label, "TRUE"

    value, used = _value_sql(question, columns)
    if question.measure is Measure.AVG:
        number = columns[question.column or ""].number
        total, counted = f"sum({number})", f"count({number})"
    else:
        total, counted = value, "count(*)"
    rank_order = "g_key" if question.grain is not None else "g_rows DESC, g_key"
    other_value = (
        "sum(g_total) / nullif(sum(g_counted), 0)"
        if question.measure is Measure.AVG
        else "sum(g_value)"
    )
    filters = f"WHERE {where} AND {placed}"

    sql = f"""
        WITH grouped AS (
            SELECT {key} AS g_key, {value} AS g_value, {total} AS g_total,
                   {counted} AS g_counted, count(*) AS g_rows, {used} AS g_used
            FROM {source} AS rows {filters} GROUP BY 1
        ),
        spellings AS (
            SELECT {key} AS g_key, {label} AS g_label, count(*) AS n
            FROM {source} AS rows {filters} GROUP BY 1, 2
        ),
        labels AS (
            SELECT g_key, first(g_label ORDER BY n DESC, g_label) AS g_label
            FROM spellings GROUP BY g_key
        ),
        ranked AS (
            SELECT g.*, l.g_label, row_number() OVER (ORDER BY {rank_order}) AS g_rank
            FROM grouped AS g LEFT JOIN labels AS l USING (g_key)
        )
        SELECT g_key, g_label, g_value, g_rows, g_used FROM ranked WHERE g_rank <= {MAX_GROUPS}
        UNION ALL
        SELECT '{OTHER_KEY}', 'All other groups', {other_value}, sum(g_rows), sum(g_used)
        FROM ranked WHERE g_rank > {MAX_GROUPS} HAVING count(*) > 0
    """
    rows = _run(conn, sql, params)
    if question.grain is None:
        # Biggest groups first; the blank group goes last among equals.
        rows.sort(key=lambda r: (r[0] == OTHER_KEY, -int(r[3]), r[0] is None, str(r[0])))
    else:
        rows.sort(key=lambda r: (r[0] == OTHER_KEY, str(r[0])))

    totals = _run(
        conn,
        f"SELECT count(*), count_if({placed}) FROM {source} AS rows WHERE {where}",
        params,
    )[0]
    all_rows, placed_rows = int(totals[0]), int(totals[1])

    groups = [
        GroupValue(
            key=None if key is None else str(key),
            label=None if label is None else str(label),
            value=None if group_value is None else float(group_value),
            rows=int(group_rows),
        )
        for key, label, group_value, group_rows, _ in rows
        if not (question.measure is Measure.AVG and group_value is None and key is None)
    ]
    used_total = sum(int(r[4] or 0) for r in rows)
    answerable = bool(groups) and (question.measure is not Measure.AVG or used_total > 0)
    skipped = all_rows - placed_rows
    if question.measure is Measure.AVG:
        skipped += placed_rows - used_total
    return Answer(
        answerable=answerable,
        groups=groups if answerable else [],
        rows_used=used_total if question.measure is Measure.AVG else placed_rows,
        rows_skipped=skipped,
        note=None if answerable else _grouped_note(question),
    )


def _grouped_note(question: Question) -> str:
    if question.grain is not None:
        return f'No "{question.group_by}" values could be read as dates.'
    return _unreadable_note(question)
