"""Answer "what was this cell before, and which step changed it?" from the change log."""

import duckdb
from pydantic import BaseModel

from app.db import RAW_REF, ROW_ID_COLUMN, quote_ident, raw_columns, work_ref
from app.errors import AppError
from app.steps.apply import CHANGES_TABLE, CLEANED_TABLE, SET_ASIDE_TABLE, ApplyResult
from app.steps.schema import text_of

ROW_ID = quote_ident(ROW_ID_COLUMN)


class CellNotFoundError(AppError):
    code = "cell_not_found"
    http_status = 404


class CellChange(BaseModel):
    step_id: str
    step_index: int
    before: str | None
    after: str | None
    kind: str


class SetAsideNote(BaseModel):
    step_id: str
    reason: str


class CellHistory(BaseModel):
    row_id: int
    column: str
    # The value in the uploaded file; None when the column was created by a step.
    original: str | None
    in_original_file: bool
    changes: list[CellChange]
    set_aside: SetAsideNote | None
    # The value in the cleaned table; None if blank or if the row was set aside.
    current: str | None


class StepChange(BaseModel):
    row_id: int
    column: str
    before: str | None
    after: str | None
    kind: str


class SetAsideRow(BaseModel):
    row_id: int
    step_id: str
    reason: str
    values: dict[str, str | None]


def cell_history(
    conn: duckdb.DuckDBPyConnection, result: ApplyResult, row_id: int, column: str
) -> CellHistory:
    if not result.lineage:
        raise ValueError("Apply the recipe with lineage=True before asking for cell history")

    raw_names = raw_columns(conn)
    output_kinds = {c.name: c.kind for c in result.columns}
    in_original = column in raw_names
    if not in_original and column not in output_kinds:
        raise CellNotFoundError(f'There\'s no column called "{column}".')

    raw_row = conn.execute(f"SELECT 1 FROM {RAW_REF} WHERE {ROW_ID} = $row", {"row": row_id})
    if raw_row.fetchone() is None:
        raise CellNotFoundError(f"There's no row {row_id} in this file.")

    original = None
    if in_original:
        original = _single(
            conn,
            f"SELECT {quote_ident(column)} FROM {RAW_REF} WHERE {ROW_ID} = $row",
            {"row": row_id},
        )

    changes = [
        CellChange(step_id=step, step_index=index, before=before, after=after, kind=kind)
        for step, index, before, after, kind in conn.execute(
            f"SELECT step_id, step_index, before, after, kind FROM {work_ref(CHANGES_TABLE)} "
            "WHERE row_id = $row AND column_name = $column ORDER BY step_index",
            {"row": row_id, "column": column},
        ).fetchall()
    ]

    set_aside_row = conn.execute(
        f"SELECT step_id, reason FROM {work_ref(SET_ASIDE_TABLE)} WHERE {ROW_ID} = $row",
        {"row": row_id},
    ).fetchone()
    set_aside = (
        SetAsideNote(step_id=str(set_aside_row[0]), reason=str(set_aside_row[1]))
        if set_aside_row
        else None
    )

    current = None
    if set_aside is None and column in output_kinds:
        current = _single(
            conn,
            f"SELECT {text_of(quote_ident(column), output_kinds[column])} "
            f"FROM {work_ref(CLEANED_TABLE)} WHERE {ROW_ID} = $row",
            {"row": row_id},
        )

    return CellHistory(
        row_id=row_id,
        column=column,
        original=original,
        in_original_file=in_original,
        changes=changes,
        set_aside=set_aside,
        current=current,
    )


def step_changes(
    conn: duckdb.DuckDBPyConnection, step_id: str, limit: int = 50
) -> list[StepChange]:
    rows = conn.execute(
        f"SELECT row_id, column_name, before, after, kind FROM {work_ref(CHANGES_TABLE)} "
        "WHERE step_id = $step ORDER BY row_id, column_name LIMIT $limit",
        {"step": step_id, "limit": limit},
    ).fetchall()
    return [
        StepChange(row_id=row, column=name, before=before, after=after, kind=kind)
        for row, name, before, after, kind in rows
    ]


def set_aside_rows(
    conn: duckdb.DuckDBPyConnection, limit: int = 50, offset: int = 0
) -> list[SetAsideRow]:
    """Set-aside rows with their values as uploaded."""
    names = [name for name in raw_columns(conn) if name != ROW_ID_COLUMN]
    value_columns = ", ".join(f"r.{quote_ident(name)}" for name in names)
    select_values = f", {value_columns}" if value_columns else ""
    rows = conn.execute(
        f"SELECT s.{ROW_ID}, s.step_id, s.reason{select_values} "
        f"FROM {work_ref(SET_ASIDE_TABLE)} AS s JOIN {RAW_REF} AS r ON s.{ROW_ID} = r.{ROW_ID} "
        f"ORDER BY s.step_index, s.{ROW_ID} LIMIT $limit OFFSET $offset",
        {"limit": limit, "offset": offset},
    ).fetchall()
    return [
        SetAsideRow(
            row_id=row[0],
            step_id=row[1],
            reason=row[2],
            values=dict(zip(names, row[3:], strict=True)),
        )
        for row in rows
    ]


def _single(conn: duckdb.DuckDBPyConnection, sql: str, params: dict[str, object]) -> str | None:
    row = conn.execute(sql, params).fetchone()
    return None if row is None or row[0] is None else str(row[0])
