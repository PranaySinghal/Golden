"""Apply a recipe: raw + enabled steps → cleaned rows, set-aside rows, and a change log.

The recipe compiles to one chain of CTEs (s0 = the raw table, sN = after the
Nth applied step). Three statements run over that chain:

- work.cleaned    the rows that remain, with every applied step's changes
- work.set_aside  (_row_id, step, reason) for rows a step set aside
- work.changes    one row per changed cell: (row, column, step, before, after)

Only changed cells are stored, so lineage costs what the recipe changes, not a
copy of the table per step. Disabled steps never enter the chain, so a
disabled step and a step that was never added produce identical SQL.
"""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

import duckdb
from pydantic import BaseModel

from app.db import RAW_REF, ROW_ID_COLUMN, quote_ident, work_ref
from app.profile.patterns import PLAIN_NUMBER
from app.steps.compile import ChangeMode, ChangeSpec, CompiledStep, compile_step
from app.steps.errors import StepValidationError
from app.steps.models import Recipe
from app.steps.schema import StageColumn, StageSchema, ValueKind, text_of, trimmed

CLEANED_TABLE = "cleaned"
SET_ASIDE_TABLE = "set_aside"
CHANGES_TABLE = "changes"
ROW_ID = quote_ident(ROW_ID_COLUMN)


class StepStatus(StrEnum):
    APPLIED = "applied"
    DISABLED = "disabled"
    BLOCKED = "blocked"


class StepOutcome(BaseModel):
    step_id: str
    status: StepStatus
    reason: str | None = None
    rows_set_aside: int = 0
    # Only known when the change log was built.
    cells_changed: int | None = None
    values_unreadable: int | None = None


class OutputColumn(BaseModel):
    name: str
    kind: ValueKind


class ApplyResult(BaseModel):
    fingerprint: str
    lineage: bool
    row_count: int
    set_aside_count: int
    columns: list[OutputColumn]
    outcomes: list[StepOutcome]

    def output_schema(self) -> StageSchema:
        return StageSchema(tuple(StageColumn(c.name, c.kind) for c in self.columns))


@dataclass(frozen=True)
class PlannedStep:
    index: int
    compiled: CompiledStep
    source: str
    target: str


@dataclass(frozen=True)
class RecipePlan:
    base: StageSchema
    stages: list[PlannedStep]
    outcomes: list[StepOutcome]
    output: StageSchema


def plan_recipe(recipe: Recipe, base: StageSchema) -> RecipePlan:
    """Compile every enabled step in order, marking steps that can't run as blocked."""
    schema = base
    # The table as it would look if every step ran. Used to tell "this step is
    # broken" apart from "this step needs a step that's turned off".
    everything_on = base
    stages: list[PlannedStep] = []
    outcomes: list[StepOutcome] = []
    current = "s0"

    for index, step in enumerate(recipe.steps):
        works_with_everything_on = True
        try:
            everything_on = compile_step(step, everything_on, index=index, source="s").output
        except StepValidationError:
            works_with_everything_on = False

        if not step.enabled:
            outcomes.append(StepOutcome(step_id=step.id, status=StepStatus.DISABLED))
            continue
        try:
            compiled = compile_step(step, schema, index=index, source=current)
        except StepValidationError as error:
            reason = error.message
            if works_with_everything_on:
                reason = "It depends on an earlier step that's turned off or can't run. " + reason
            outcomes.append(StepOutcome(step_id=step.id, status=StepStatus.BLOCKED, reason=reason))
            continue

        target = f"s{len(stages) + 1}"
        stages.append(PlannedStep(index=index, compiled=compiled, source=current, target=target))
        outcomes.append(StepOutcome(step_id=step.id, status=StepStatus.APPLIED))
        schema = compiled.output
        current = target

    return RecipePlan(base=base, stages=stages, outcomes=outcomes, output=schema)


def fingerprint(plan: RecipePlan, recipe: Recipe) -> str:
    applied = {stage.compiled.step_id for stage in plan.stages}
    payload = {
        "base": plan.base.names(),
        "steps": [step.model_dump(mode="json") for step in recipe.steps if step.id in applied],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def apply_recipe(
    conn: duckdb.DuckDBPyConnection,
    recipe: Recipe,
    base: StageSchema,
    *,
    lineage: bool = True,
    previous: ApplyResult | None = None,
) -> ApplyResult:
    """Build the work tables. `previous` is reused when nothing that matters changed."""
    plan = plan_recipe(recipe, base)
    key = fingerprint(plan, recipe)
    if previous is not None and previous.fingerprint == key and (previous.lineage or not lineage):
        return previous

    _build_cleaned(conn, plan)
    _build_set_aside(conn, plan)
    if lineage:
        _build_changes(conn, plan)
    else:
        conn.execute(f"DROP TABLE IF EXISTS {work_ref(CHANGES_TABLE)}")

    return ApplyResult(
        fingerprint=key,
        lineage=lineage,
        row_count=_scalar(conn, f"SELECT count(*) FROM {work_ref(CLEANED_TABLE)}"),
        set_aside_count=_scalar(conn, f"SELECT count(*) FROM {work_ref(SET_ASIDE_TABLE)}"),
        columns=[OutputColumn(name=c.name, kind=c.kind) for c in plan.output.columns],
        outcomes=_with_counts(conn, plan, lineage),
    )


def _chain(plan: RecipePlan, stage_count: int, materialized: bool) -> tuple[str, dict[str, object]]:
    keyword = "MATERIALIZED " if materialized else ""
    base_columns = ", ".join([ROW_ID, *(quote_ident(name) for name in plan.base.names())])
    parts = [f"s0 AS {keyword}(SELECT {base_columns} FROM {RAW_REF})"]
    params: dict[str, object] = {}
    for stage in plan.stages[:stage_count]:
        parts.append(f"{stage.target} AS {keyword}({stage.compiled.kept.sql})")
        params.update(stage.compiled.kept.params)
    return "WITH " + ", ".join(parts), params


def _build_cleaned(conn: duckdb.DuckDBPyConnection, plan: RecipePlan) -> None:
    chain, params = _chain(plan, len(plan.stages), materialized=False)
    last = plan.stages[-1].target if plan.stages else "s0"
    conn.execute(
        f"CREATE OR REPLACE TABLE {work_ref(CLEANED_TABLE)} AS "
        f"{chain} SELECT * FROM {last} ORDER BY {ROW_ID}",
        params,
    )


def _build_set_aside(conn: duckdb.DuckDBPyConnection, plan: RecipePlan) -> None:
    table = work_ref(SET_ASIDE_TABLE)
    removal_positions = [
        position for position, stage in enumerate(plan.stages) if stage.compiled.removed
    ]
    if not removal_positions:
        conn.execute(
            f"CREATE OR REPLACE TABLE {table} "
            f"({ROW_ID} BIGINT, step_id VARCHAR, step_index INTEGER, reason VARCHAR)"
        )
        return

    # A removal at stage k reads stage k-1, so the chain only needs to reach there.
    chain, params = _chain(plan, max(removal_positions), materialized=True)
    selects = []
    for position in removal_positions:
        stage = plan.stages[position]
        removed = stage.compiled.removed
        assert removed is not None
        params.update(removed.params)
        step_param, reason_param = f"a{stage.index}_step", f"a{stage.index}_reason"
        params[step_param] = stage.compiled.step_id
        params[reason_param] = stage.compiled.removal_reason
        selects.append(
            f"SELECT {ROW_ID}, CAST(${step_param} AS VARCHAR) AS step_id, "
            f"CAST({stage.index} AS INTEGER) AS step_index, "
            f"CAST(${reason_param} AS VARCHAR) AS reason FROM ({removed.sql})"
        )
    conn.execute(
        f"CREATE OR REPLACE TABLE {table} AS {chain} {' UNION ALL '.join(selects)} "
        f"ORDER BY step_index, {ROW_ID}",
        params,
    )


def _build_changes(conn: duckdb.DuckDBPyConnection, plan: RecipePlan) -> None:
    table = work_ref(CHANGES_TABLE)
    positions = [position for position, stage in enumerate(plan.stages) if stage.compiled.changes]
    if not positions:
        conn.execute(
            f"CREATE OR REPLACE TABLE {table} (row_id BIGINT, column_name VARCHAR, "
            "step_id VARCHAR, step_index INTEGER, before VARCHAR, after VARCHAR, kind VARCHAR)"
        )
        return

    chain, params = _chain(plan, max(positions) + 1, materialized=True)
    selects = []
    for position in positions:
        stage = plan.stages[position]
        for number, spec in enumerate(stage.compiled.changes):
            prefix = f"l{stage.index}_{number}_"
            selects.append(_change_select(stage, spec, prefix, params))
    conn.execute(
        f"CREATE OR REPLACE TABLE {table} AS {chain} {' UNION ALL '.join(selects)} "
        "ORDER BY step_index, row_id, column_name",
        params,
    )


def _change_select(
    stage: PlannedStep, spec: ChangeSpec, prefix: str, params: dict[str, object]
) -> str:
    before = f"b.{quote_ident(spec.source_column)}"
    after = f"a.{quote_ident(spec.output_column)}"
    before_text = text_of(before, spec.source_kind)
    after_text = text_of(after, spec.output_kind)

    match spec.mode:
        case ChangeMode.TEXT:
            changed = f"({before_text}) IS DISTINCT FROM ({after_text})"
        case ChangeMode.NUMBER_FROM_TEXT:
            params[prefix + "plain"] = PLAIN_NUMBER
            t = trimmed(before)
            same_number = (
                f"({before} IS NULL AND {after} IS NULL) OR "
                f"(regexp_full_match({t}, ${prefix}plain) AND TRY_CAST({t} AS DOUBLE) = {after})"
            )
            changed = f"NOT coalesce({same_number}, false)"
        case ChangeMode.ANY_FILLED:
            changed = f"NOT ({before} IS NULL AND {after} IS NULL)"
        case ChangeMode.CREATED:
            changed = f"{after} IS NOT NULL"

    if spec.mode is ChangeMode.CREATED:
        kind = "'created'"
    else:
        kind = (
            f"CASE WHEN ({before_text}) IS NULL THEN 'filled' "
            f"WHEN ({after_text}) IS NULL THEN 'cleared' ELSE 'changed' END"
        )

    params[prefix + "column"] = spec.output_column
    params[prefix + "step"] = stage.compiled.step_id
    return (
        f"SELECT a.{ROW_ID} AS row_id, CAST(${prefix}column AS VARCHAR) AS column_name, "
        f"CAST(${prefix}step AS VARCHAR) AS step_id, "
        f"CAST({stage.index} AS INTEGER) AS step_index, "
        f"CAST({before_text} AS VARCHAR) AS before, CAST({after_text} AS VARCHAR) AS after, "
        f"{kind} AS kind "
        f"FROM {stage.target} AS a JOIN {stage.source} AS b ON a.{ROW_ID} = b.{ROW_ID} "
        f"WHERE {changed}"
    )


def _with_counts(
    conn: duckdb.DuckDBPyConnection, plan: RecipePlan, lineage: bool
) -> list[StepOutcome]:
    set_aside = dict(
        conn.execute(
            f"SELECT step_id, count(*) FROM {work_ref(SET_ASIDE_TABLE)} GROUP BY step_id"
        ).fetchall()
    )
    changed: dict[str, tuple[int, int]] = {}
    if lineage:
        rows = conn.execute(
            f"SELECT step_id, count(*), count_if(kind = 'cleared') "
            f"FROM {work_ref(CHANGES_TABLE)} GROUP BY step_id"
        ).fetchall()
        changed = {str(step): (int(total), int(cleared)) for step, total, cleared in rows}

    reading_steps = {
        stage.compiled.step_id
        for stage in plan.stages
        if any(
            spec.mode in (ChangeMode.NUMBER_FROM_TEXT, ChangeMode.ANY_FILLED)
            for spec in stage.compiled.changes
        )
    }
    outcomes = []
    for outcome in plan.outcomes:
        if outcome.status is not StepStatus.APPLIED:
            outcomes.append(outcome)
            continue
        total, cleared = changed.get(outcome.step_id, (0, 0))
        outcomes.append(
            outcome.model_copy(
                update={
                    "rows_set_aside": int(set_aside.get(outcome.step_id, 0)),
                    "cells_changed": total if lineage else None,
                    "values_unreadable": (
                        cleared if lineage and outcome.step_id in reading_steps else None
                    ),
                }
            )
        )
    return outcomes


def _scalar(conn: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row else 0
