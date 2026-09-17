from typing import Any

from fastapi import FastAPI

from app.api import health
from app.api.errors import ErrorResponse, register_error_handlers

# Declared on every route so the generated frontend types include the error shape.
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": ErrorResponse, "description": "A problem the user can fix"},
}

app = FastAPI(title="Golden Analytics", version="0.1.0", responses=_ERROR_RESPONSES)
register_error_handlers(app)
app.include_router(health.router)
