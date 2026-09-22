"""Turning proposed fixes into real issues, or throwing them away.

A model's suggestion is a claim about someone's data. Before it reaches the
screen it has to survive every check here: the columns must exist, the steps
must be steps the engine knows, they must compile, every value they match on
must actually occur in that column, and they must change something. How many
rows a fix touches is counted by us, never taken from the model.

What survives is built with the same IssueBuilder the detectors use, so it
carries stable ids and behaves like any other issue from then on.
"""

import logging
from datetime import date

import duckdb
from pydantic import TypeAdapter, ValidationError

from app.ai.schemas import ProposedFix, SuggestFixesReply
from app.db import RAW_REF, quote_ident
from app.detectors.base import DetectorContext, IssueBuilder
from app.detectors.models import DetectorName, Issue, Tier
from app.preview import preview
from app.profile.models import DatasetProfile
from app.steps.compile import compile_step
from app.steps.errors import StepValidationError
from app.steps.identity import work_key
from app.steps.models import (
    EqualsCondition,
    MapValuesStep,
    NullPlaceholdersStep,
    OneOfCondition,
    Recipe,
    SplitColumnStep,
    Step,
)
from app.steps.schema import StageSchema, base_schema, match_key

logger = logging.getLogger("tidylab.ai")

_STEP = TypeAdapter[Step](Step)


class RejectedError(Exception):
    """Why a fix didn't make it. The reason is logged, never shown to the user."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def accepted_fixes(
    conn: duckdb.DuckDBPyConnection,
    profile: DatasetProfile,
    reply: SuggestFixesReply,
    known: list[Issue],
    today: date | None = None,
) -> list[Issue]:
    """Every proposed fix that survives checking, as issues ready to show."""
    ctx = DetectorContext(conn=conn, profile=profile, today=today or date.today())
    base = base_schema(profile)
    seen = {_signature(step) for issue in known for step in _all_steps(issue)}
    issues: list[Issue] = []

    for position, fix in enumerate(reply.fixes):
        try:
            issues.append(_to_issue(ctx, base, fix, position, seen))
        except RejectedError as rejection:
            logger.info("ai fix rejected reason=%s", rejection.reason)
    return issues


def _to_issue(
    ctx: DetectorContext,
    base: StageSchema,
    fix: ProposedFix,
    position: int,
    seen: set[str],
) -> Issue:
    _check_columns(ctx.profile, fix)
    steps = _check_steps(base, fix)
    if any(_signature(step) in seen for step in steps):
        raise RejectedError("already suggested by a detector")
    for step in steps:
        _check_values_exist(ctx.conn, step)

    affected, examples = _count_affected(ctx.conn, base, steps)
    if affected == 0:
        raise RejectedError("changes nothing")

    builder = IssueBuilder(ctx, DetectorName.AI_SUGGESTION, fix.columns, f"ai-{position}")
    with_ids = [builder.step(step) for step in steps]
    return builder.build(
        title=fix.title,
        explanation=fix.explanation,
        affected_rows=affected,
        # However sure a model sounds, nothing it proposes is applied unasked.
        tier=Tier.LIKELY,
        steps=with_ids,
        examples=examples,
    ).model_copy(update={"source": "ai"})


def _check_columns(profile: DatasetProfile, fix: ProposedFix) -> None:
    names = {column.name for column in profile.columns}
    missing = [name for name in fix.columns if name not in names]
    if missing:
        raise RejectedError(f"column doesn't exist ({len(missing)})")


def _check_steps(base: StageSchema, fix: ProposedFix) -> list[Step]:
    """Each step must be one the engine knows, and must compile where it would run."""
    steps: list[Step] = []
    schema = base
    for index, proposed in enumerate(fix.steps):
        try:
            step = _STEP.validate_python({**proposed.arguments, "type": proposed.type})
        except ValidationError as error:
            raise RejectedError(f"step {index} isn't a step we can run") from error
        try:
            schema = compile_step(step, schema, index=index, source="s").output
        except StepValidationError as error:
            raise RejectedError(f"step {index} can't run on this file") from error
        steps.append(step)
    return steps


def _check_values_exist(conn: duckdb.DuckDBPyConnection, step: Step) -> None:
    """A value a step matches on has to be in the column, or it was invented."""
    for column, value in _referenced_values(step):
        ident = quote_ident(column)
        if isinstance(value, _Contains):
            found = conn.execute(
                f"SELECT count(*) FROM {RAW_REF} WHERE contains({ident}, $needle)",
                {"needle": value.text},
            ).fetchone()
        else:
            found = conn.execute(
                f"SELECT count(*) FROM {RAW_REF} WHERE {match_key(ident)} = {match_key('$value')}",
                {"value": value},
            ).fetchone()
        if not found or int(found[0]) == 0:
            raise RejectedError("matches a value that isn't in the column")


class _Contains(str):
    """A value that only has to appear inside a cell, such as a separator."""

    @property
    def text(self) -> str:
        return str(self)


def _referenced_values(step: Step) -> list[tuple[str, str]]:
    match step:
        case NullPlaceholdersStep():
            return [(column, token) for column in step.columns for token in step.placeholders]
        case MapValuesStep():
            return [(step.column, mapping.from_value) for mapping in step.mappings]
        case SplitColumnStep():
            return [(step.column, _Contains(step.delimiter))]
        case _:
            condition = getattr(step, "condition", None)
            if isinstance(condition, EqualsCondition):
                return [(condition.column, str(condition.value))]
            if isinstance(condition, OneOfCondition):
                return [(condition.column, str(value)) for value in condition.values]
            return []


def _count_affected(
    conn: duckdb.DuckDBPyConnection, base: StageSchema, steps: list[Step]
) -> tuple[int, list[str]]:
    """Our own count of what a fix touches, with an example or two from the rows."""
    shown = preview(conn, base, Recipe(), Recipe(steps=steps), {step.id for step in steps}, limit=2)
    examples = [
        cell.before
        for row in shown.rows
        for cell in row.cells.values()
        if cell.changed and cell.before
    ]
    return shown.changed_rows, examples[:2]


def _all_steps(issue: Issue) -> list[Step]:
    steps = list(issue.steps)
    if issue.ask is not None:
        steps += [step for choice in issue.ask.choices for step in choice.steps]
    return steps


def _signature(step: Step) -> str:
    """What a step does, ignoring which object did it."""
    return work_key(step)
