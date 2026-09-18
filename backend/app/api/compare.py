"""How cleaning changed the answers, and the cleaned file itself."""

from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from app import review
from app.api.comparison import ComparisonResponse, comparison_response
from app.api.deps import StoreDep
from app.api.views import recipe_response
from app.steps.export import build_recipe_file, cleaned_csv_bytes, recipe_file_bytes
from app.store import DatasetSession

router = APIRouter(prefix="/api/datasets", tags=["compare"])

CSV_TYPE = "text/csv; charset=utf-8"
RECIPE_TYPE = "application/json"


@router.get(
    "/{dataset_id}/compare", response_model=ComparisonResponse, operation_id="getComparison"
)
def get_comparison(dataset_id: str, store: StoreDep) -> ComparisonResponse:
    session = store.get(dataset_id)
    with session.lock:
        return comparison_response(review.compare_now(session))


@router.get(
    "/{dataset_id}/export",
    operation_id="exportDataset",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}, "application/json": {}}}},
)
def export_dataset(
    dataset_id: str, store: StoreDep, format: Annotated[Literal["csv", "recipe"], Query()] = "csv"
) -> Response:
    session = store.get(dataset_id)
    with session.lock:
        # Building the panel's view is what applies the recipe, so the cleaned
        # table is the one the user has been looking at.
        recipe_response(session)
        if format == "csv":
            body, media_type, name = _cleaned_csv(session)
        else:
            body, media_type, name = _recipe_file(session)
    return Response(content=body, media_type=media_type, headers=_attachment(name))


def _cleaned_csv(session: DatasetSession) -> tuple[bytes, str, str]:
    assert session.applied is not None  # recipe_response just built it
    body = cleaned_csv_bytes(session.conn, session.applied, session.workspace)
    return body, CSV_TYPE, f"{_stem(session.filename)} (tidied).csv"


def _recipe_file(session: DatasetSession) -> tuple[bytes, str, str]:
    recipe_file = build_recipe_file(session.recipe, session.base_schema, session.filename)
    return recipe_file_bytes(recipe_file), RECIPE_TYPE, f"{_stem(session.filename)}.tidylab.json"


def _stem(filename: str) -> str:
    return filename.rsplit(".", 1)[0] or filename


def _attachment(name: str) -> dict[str, str]:
    """A filename browsers keep, including one with spaces or accents in it."""
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"}
