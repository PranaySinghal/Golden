from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.api import datasets, health, issues, preview, recipe
from app.api.errors import ErrorResponse, register_error_handlers
from app.api.limits import UploadSizeMiddleware
from app.config import get_settings
from app.store import DatasetStore

# Declared on every route so the generated frontend types include the error shape.
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": ErrorResponse, "description": "A problem the user can fix"},
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.settings = get_settings()
    app.state.store = DatasetStore(app.state.settings)
    try:
        yield
    finally:
        # Workspaces hold raw data on disk; don't leave them behind on shutdown.
        app.state.store.close_all()


app = FastAPI(title="TidyLab", version="0.1.0", responses=_ERROR_RESPONSES, lifespan=lifespan)
register_error_handlers(app)
app.add_middleware(UploadSizeMiddleware)
app.include_router(health.router)
app.include_router(datasets.router)
app.include_router(issues.router)
app.include_router(recipe.router)
app.include_router(preview.router)
