"""Connectors: what can be looked up from outside services, and doing it."""

from fastapi import APIRouter
from pydantic import BaseModel

from app import review
from app.api.deps import ConnectorsDep, StoreDep
from app.api.views import RecipeResponse, recipe_response
from app.connectors import service
from app.connectors.service import (
    ConnectorsOverview,
    ConnectorView,
    FillPreview,
    FillRequest,
)
from app.steps.models import ConnectorName

router = APIRouter(prefix="/api", tags=["connectors"])


class LookupRequest(BaseModel):
    # A new lookup names a connector and a column...
    connector: ConnectorName | None = None
    column: str | None = None
    # ...and, for postal codes, the country they are from.
    country: str | None = None
    # Looking up again, or picking up where a run stopped, names the step instead.
    step_id: str | None = None
    # The user has seen what will be sent and said yes. Needed once per connector and file.
    consent: bool = False
    # For connector "ai_fill": the new column a model should fill in.
    fill: FillRequest | None = None


class FillPreviewRequest(BaseModel):
    fill: FillRequest
    consent: bool = False


class ConnectorSwitch(BaseModel):
    active: bool


class DatasetConnectors(ConnectorsOverview):
    recipe: RecipeResponse


@router.get("/connectors", response_model=list[ConnectorView], operation_id="getConnectors")
def get_connectors(connectors: ConnectorsDep) -> list[ConnectorView]:
    return service.connector_views(connectors)


@router.get(
    "/datasets/{dataset_id}/connectors",
    response_model=DatasetConnectors,
    operation_id="getDatasetConnectors",
)
def get_dataset_connectors(
    dataset_id: str, store: StoreDep, connectors: ConnectorsDep
) -> DatasetConnectors:
    session = store.get(dataset_id)
    with session.lock:
        review.prepare(session)
        recipe = recipe_response(session)
        found = service.overview(session, connectors)
        return DatasetConnectors(**found.model_dump(), recipe=recipe)


@router.put(
    "/datasets/{dataset_id}/connectors/{connector}",
    response_model=DatasetConnectors,
    operation_id="setConnectorActive",
)
def set_connector_active(
    dataset_id: str,
    connector: ConnectorName,
    body: ConnectorSwitch,
    store: StoreDep,
    connectors: ConnectorsDep,
) -> DatasetConnectors:
    session = store.get(dataset_id)
    with session.lock:
        review.prepare(session)
        service.set_active(session, connectors, connector, body.active)
        recipe = recipe_response(session)
        found = service.overview(session, connectors)
        return DatasetConnectors(**found.model_dump(), recipe=recipe)


@router.post(
    "/datasets/{dataset_id}/connectors/lookups",
    response_model=DatasetConnectors,
    operation_id="runConnectorLookup",
)
def run_lookup(
    dataset_id: str, body: LookupRequest, store: StoreDep, connectors: ConnectorsDep
) -> DatasetConnectors:
    session = store.get(dataset_id)
    with session.lock:
        prepared = service.prepare_run(
            session,
            connectors,
            connector=body.connector,
            column=body.column,
            country=body.country,
            step_id=body.step_id,
            consent=body.consent,
            fill=body.fill,
        )
    # The slow part. No lock is held, so the rest of the page keeps working.
    results = service.answers_for(prepared, connectors)
    with session.lock:
        service.finish_run(session, prepared, results)
        recipe = recipe_response(session)
        found = service.overview(session, connectors)
        return DatasetConnectors(**found.model_dump(), recipe=recipe)


@router.post(
    "/datasets/{dataset_id}/connectors/ai-fill/preview",
    response_model=FillPreview,
    operation_id="previewAiFill",
)
def preview_ai_fill(
    dataset_id: str, body: FillPreviewRequest, store: StoreDep, connectors: ConnectorsDep
) -> FillPreview:
    """A few example answers for a column a model would fill in. Changes nothing."""
    session = store.get(dataset_id)
    with session.lock:
        prepared = service.prepare_run(
            session,
            connectors,
            connector="ai_fill",
            column=None,
            country=None,
            step_id=None,
            consent=body.consent,
            fill=body.fill,
        )
    return service.preview_answers(prepared, connectors)
