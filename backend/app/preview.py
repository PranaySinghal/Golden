"""A handful of rows as they are now and as a step would leave them.

Two versions of the recipe are built — with the steps and without them — and
joined on the row id, so a preview shows exactly what the engine would do, not
a re-implementation of it. Only the columns the steps touch are returned, and
only rows where something actually changes.
"""

from dataclasses import dataclass

import duckdb
from pydantic import BaseModel, Field

from app.db import ROW_ID_COLUMN, quote_ident, work_ref
from app.steps.apply import RecipePlan, StepStatus, chain_sql, plan_recipe
from app.steps.models import Recipe
from app.steps.schema import StageSchema, text_of

BEFORE_TABLE = "preview_before"
AFTER_TABLE = "preview_after"
DEFAULT_ROWS = 5
# A preview is a glance, not a spreadsheet: too many columns and nothing stands out.
MAX_COLUMNS = 6


class PreviewCell(BaseModel):
    before: str | None
    after: str | None
    changed: bool


class PreviewRow(BaseModel):
    row_id: int
    cells: dict[str, PreviewCell]
    set_aside: bool = False


class Preview(BaseModel):
    columns: list[str]
    rows: list[PreviewRow] = Field(default_factory=list)
    changed_rows: int = 0
    set_aside_rows: int = 0
    note: str | None = None


@dataclass(frozen=True)
class _Side:
    plan: RecipePlan
    table: str


def touched_columns(plan: RecipePlan, step_ids: set[str]) -> list[str]:
    """The columns those steps write, create or read, in the table's own order."""
    wanted: set[str] = set()
    for stage in plan.stages:
        if stage.compiled.step_id not in step_ids:
            continue
        wanted |= {spec.output_column for spec in stage.compiled.changes}
        wanted |= set(stage.compiled.creates)
        wanted |= set(stage.compiled.reads)
    return [column.name for column in plan.output.columns if column.name in wanted]


def preview(
    conn: duckdb.DuckDBPyConnection,
    base: StageSchema,
    without: Recipe,
    with_steps: Recipe,
    step_ids: set[str],
    limit: int = DEFAULT_ROWS,
) -> Preview:
    """Rows before and after `step_ids`, which `with_steps` has and `without` doesn't."""
    after = _Side(plan_recipe(with_steps, base), AFTER_TABLE)
    blocked = [
        outcome
        for outcome in after.plan.outcomes
        if outcome.step_id in step_ids and outcome.status is StepStatus.BLOCKED
    ]
    if blocked:
        return Preview(columns=[], note=blocked[0].reason)

    columns = touched_columns(after.plan, step_ids)[:MAX_COLUMNS]
    if not columns:
        return Preview(columns=[], note="This step doesn't change any values.")

    before = _Side(plan_recipe(without, base), BEFORE_TABLE)
    try:
        _build(conn, before)
        _build(conn, after)
        return _read(conn, before, after, columns, limit)
    finally:
        for table in (BEFORE_TABLE, AFTER_TABLE):
            conn.execute(f"DROP TABLE IF EXISTS {work_ref(table)}")


def _build(conn: duckdb.DuckDBPyConnection, side: _Side) -> None:
    # Built as two statements rather than one query, so each side's bound
    # parameters stay in their own statement and can't collide.
    sql, params = chain_sql(side.plan)
    conn.execute(f"CREATE OR REPLACE TABLE {work_ref(side.table)} AS {sql}", dict(params))


def _text(side: _Side, alias: str, column: str) -> str:
    stage = side.plan.output.get(column)
    if stage is None:
        return "CAST(NULL AS VARCHAR)"
    return text_of(f"{alias}.{quote_ident(column)}", stage.kind)


def _read(
    conn: duckdb.DuckDBPyConnection,
    before: _Side,
    after: _Side,
    columns: list[str],
    limit: int,
) -> Preview:
    row_id = quote_ident(ROW_ID_COLUMN)
    selects = ["b." + row_id, "a." + row_id + " IS NULL AS set_aside"]
    differs = []
    for column in columns:
        old, new = _text(before, "b", column), _text(after, "a", column)
        selects += [f"{old} AS b_{len(selects)}", f"{new} AS a_{len(selects)}"]
        differs.append(f"({old}) IS DISTINCT FROM ({new})")

    joined = (
        f"FROM {work_ref(before.table)} AS b "
        f"LEFT JOIN {work_ref(after.table)} AS a USING ({row_id})"
    )
    moved = f"(a.{row_id} IS NULL OR {' OR '.join(differs)})"
    rows = conn.execute(
        f"SELECT {', '.join(selects)} {joined} WHERE {moved} ORDER BY b.{row_id} LIMIT {limit}"
    ).fetchall()
    # coalesce because count_if answers NULL over no rows, as in a file with
    # column names and nothing under them.
    totals = conn.execute(
        f"SELECT coalesce(count_if({moved}), 0), coalesce(count_if(a.{row_id} IS NULL), 0) {joined}"
    ).fetchone()
    changed_rows, set_aside_rows = (int(totals[0]), int(totals[1])) if totals else (0, 0)

    return Preview(
        columns=columns,
        rows=[_row(values, columns) for values in rows],
        changed_rows=changed_rows,
        set_aside_rows=set_aside_rows,
        note=None if changed_rows else "Nothing in this file changes.",
    )


def _row(values: tuple[object, ...], columns: list[str]) -> PreviewRow:
    row_id, set_aside = int(str(values[0])), bool(values[1])
    cells: dict[str, PreviewCell] = {}
    for index, column in enumerate(columns):
        old, new = values[2 + index * 2], values[3 + index * 2]
        before = None if old is None else str(old)
        # A row that was set aside keeps its values; it's the row that goes, not
        # the cells, so it reads as unchanged and is marked instead.
        after = before if set_aside else (None if new is None else str(new))
        cells[column] = PreviewCell(before=before, after=after, changed=before != after)
    return PreviewRow(row_id=row_id, cells=cells, set_aside=set_aside)
