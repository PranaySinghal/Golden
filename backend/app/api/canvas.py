"""The canvas: the table as it stands, columns the user adds, and ideas for more."""

from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints

from app import review
from app.api.deps import ConnectorsDep, ProviderDep, SettingsDep, StoreDep
from app.api.views import RecipeResponse, recipe_response
from app.connectors import service as connector_service
from app.connectors.runner import Runtime
from app.db import ROW_ID_COLUMN, quote_ident, work_ref
from app.semantic.models import Suggestions
from app.steps.apply import CLEANED_TABLE
from app.steps.models import AddColumnStep
from app.steps.schema import ValueKind, text_of
from app.store import DatasetSession

router = APIRouter(prefix="/api/datasets", tags=["canvas"])

# A glance at the table, not the table: enough rows to see what a new column sits beside.
PREVIEW_ROWS = 8


class NewColumn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    # Text to put in every row. Leave out for an empty column.
    value: Annotated[str, StringConstraints(max_length=1000)] | None = None
    # Leave out to put the column last.
    insert_after: str | None = None


class CanvasColumn(BaseModel):
    name: str
    kind: ValueKind
    # Set when the user added this column here, so it can be taken back out.
    step_id: str | None = None
    # For a looked-up column: when its values were true, if that matters.
    label: str | None = None


class CanvasResponse(BaseModel):
    columns: list[CanvasColumn] = Field(default_factory=list)
    # The first few rows, each in the same order as `columns`.
    rows: list[list[str | None]] = Field(default_factory=list)
    # Why a looked-up cell is empty ("not found", "rate limited"), by column
    # name, one entry per row above. Only looked-up columns appear here.
    reasons: dict[str, list[str | None]] = Field(default_factory=dict)
    row_count: int = 0
    recipe: RecipeResponse


def _canvas(session: DatasetSession, connectors: Runtime) -> CanvasResponse:
    recipe = recipe_response(session)
    added = {
        step.name: step.id
        for step in session.recipe.steps
        if isinstance(step, AddColumnStep) and step.enabled
    }
    rows: list[list[str | None]] = []
    if recipe.columns:
        selected = ", ".join(
            f"CAST({text_of(quote_ident(column.name), column.kind)} AS VARCHAR)"
            for column in recipe.columns
        )
        fetched = session.conn.execute(
            f"SELECT {selected} FROM {work_ref(CLEANED_TABLE)} "
            f"ORDER BY {quote_ident(ROW_ID_COLUMN)} LIMIT {PREVIEW_ROWS}"
        ).fetchall()
        rows = [list(row) for row in fetched]
    notes = connector_service.canvas_notes(session, connectors, PREVIEW_ROWS)
    return CanvasResponse(
        columns=[
            CanvasColumn(
                name=column.name,
                kind=column.kind,
                step_id=added.get(column.name),
                label=notes[column.name].label if column.name in notes else None,
            )
            for column in recipe.columns
        ],
        rows=rows,
        reasons={name: note.reasons for name, note in notes.items()},
        row_count=recipe.row_count,
        recipe=recipe,
    )


@router.get("/{dataset_id}/canvas", response_model=CanvasResponse, operation_id="getCanvas")
def get_canvas(dataset_id: str, store: StoreDep, connectors: ConnectorsDep) -> CanvasResponse:
    session = store.get(dataset_id)
    with session.lock:
        review.prepare(session)
        return _canvas(session, connectors)


@router.post(
    "/{dataset_id}/canvas/columns", response_model=CanvasResponse, operation_id="addCanvasColumn"
)
def add_canvas_column(
    dataset_id: str, body: NewColumn, store: StoreDep, connectors: ConnectorsDep
) -> CanvasResponse:
    session = store.get(dataset_id)
    with session.lock:
        review.add_column(session, body.name, body.value, body.insert_after)
        return _canvas(session, connectors)


@router.get(
    "/{dataset_id}/canvas/suggestions",
    response_model=Suggestions,
    operation_id="getCanvasSuggestions",
)
def get_canvas_suggestions(
    dataset_id: str,
    store: StoreDep,
    settings: SettingsDep,
    provider: ProviderDep,
    smart: bool = True,
) -> Suggestions:
    session = store.get(dataset_id)
    with session.lock:
        return review.column_suggestions(session, settings, provider, smart=smart)
