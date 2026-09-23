import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.ai.limiter import CallBudget
from app.api import ai, compare, datasets, health, issues, preview, recipe
from app.api.errors import ErrorResponse, register_error_handlers
from app.api.frontend import frontend_router
from app.api.limits import UploadSizeMiddleware
from app.config import get_settings
from app.store import DatasetStore

# Declared on every route so the generated frontend types include the error shape.
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": ErrorResponse, "description": "A problem the user can fix"},
}


def _setup_logging() -> None:
    """Send our own log lines somewhere. The server configures its loggers, not ours."""
    logger = logging.getLogger("tidylab")
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _setup_logging()
    app.state.settings = get_settings()
    app.state.store = DatasetStore(app.state.settings)
    app.state.llm_budget = CallBudget(app.state.settings.llm_max_calls_per_minute)
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
app.include_router(compare.router)
app.include_router(ai.router)

# Last, so it only answers what no API route did.
_static_dir = get_settings().static_dir
if _static_dir:
    app.include_router(frontend_router(Path(_static_dir)))
