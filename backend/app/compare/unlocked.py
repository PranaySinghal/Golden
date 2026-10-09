"""Questions the raw file couldn't answer, that cleaning makes possible.

Two things make a new question askable:

- a column that didn't exist before, because a step split one in two;
- a column whose values only became readable, e.g. "$1,299.00" read as a number
  or "15.03.2024" read as a date, where the spreadsheet reading couldn't place
  a single value.

Both are found the same way: profile the columns the recipe created or retyped,
run the ordinary question generator over them, and keep the questions that the
raw file genuinely can't answer. A question that both sides can answer is a
changed answer, not a new one, however far it moved.

Generation reads the cleaned rows stored as text, so a created column is
profiled by exactly the same rules as a column from a file.
"""

import duckdb

from app.db import ROW_ID_COLUMN, quote_ident, work_ref
from app.profile.models import ColumnProfile, DatasetProfile
from app.profile.profiler import profile_column
from app.profile.stats import compute_column_stats, count_rows
from app.questions.generate import generate_questions
from app.questions.models import Question
from app.steps.apply import RecipePlan, chain_sql, volatile_columns
from app.steps.schema import ValueKind, text_of

# Cleaned rows as text, so the profiler and generator can read them like a file.
TEXT_TABLE = "after_text"
MAX_UNLOCKED = 6
# Candidates to weigh before the cap; more than this and the extras would be
# too far down the prominence order to show anyway.
MAX_CANDIDATES = 24


def changed_columns(plan: RecipePlan) -> list[str]:
    """Columns the recipe created, or gave a kind other than text.

    Looked-up columns are left out: their values can change from day to day, so
    a question about them would have no one answer to compare.
    """
    before = {column.name for column in plan.base.columns}
    volatile, _ = volatile_columns(plan)
    return [
        column.name
        for column in plan.output.columns
        if column.name not in volatile
        and (column.name not in before or column.kind is not ValueKind.TEXT)
    ]


def build_text_table(conn: duckdb.DuckDBPyConnection, plan: RecipePlan) -> None:
    """Materialize the recipe's rows with every value rendered as text."""
    sql, params = chain_sql(plan)
    columns = ", ".join(
        f"{text_of(quote_ident(column.name), column.kind)} AS {quote_ident(column.name)}"
        for column in plan.output.columns
    )
    conn.execute(
        f"CREATE OR REPLACE TABLE {work_ref(TEXT_TABLE)} AS "
        f"SELECT {quote_ident(ROW_ID_COLUMN)}, {columns} FROM ({sql})",
        params,
    )


def drop_text_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {work_ref(TEXT_TABLE)}")


def cleaned_profile(
    conn: duckdb.DuckDBPyConnection, plan: RecipePlan, raw: DatasetProfile, changed: list[str]
) -> DatasetProfile:
    """The cleaned table's profile: changed columns measured, the rest carried over.

    Carrying the others over keeps the cost proportional to what the recipe
    changed. Their values may have been tidied, but their role hasn't, and the
    generator only needs the role to pick questions.
    """
    table = work_ref(TEXT_TABLE)
    row_count = count_rows(conn, table)
    by_name = {column.name: column for column in raw.columns}
    columns: list[ColumnProfile] = []
    for position, column in enumerate(plan.output.columns):
        if column.name in changed:
            stats = compute_column_stats(conn, column.name, position, row_count, table)
            columns.append(profile_column(stats))
        elif column.name in by_name:
            columns.append(by_name[column.name].model_copy(update={"position": position}))
    return DatasetProfile(row_count=row_count, column_count=len(columns), columns=columns)


def candidates(
    conn: duckdb.DuckDBPyConnection,
    plan: RecipePlan,
    raw: DatasetProfile,
    asked: set[str],
) -> list[Question]:
    """Questions about created or retyped columns that weren't asked of the raw file.

    Ordered by prominence, most headline first. Whether each one is really
    unlocked is settled by answering it on both sides.
    """
    changed = changed_columns(plan)
    if not changed:
        return []
    build_text_table(conn, plan)
    try:
        profile = cleaned_profile(conn, plan, raw, changed)
        generated = generate_questions(
            conn, profile, limit=MAX_CANDIDATES, table=work_ref(TEXT_TABLE)
        )
    finally:
        drop_text_table(conn)

    new = [
        question.model_copy(update={"origin": "unlocked"})
        for question in generated
        if question.id not in asked and question.columns & set(changed)
    ]
    return sorted(new, key=lambda q: -q.prominence)
