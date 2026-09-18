from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.errors import AppError

INVALID_REQUEST = "The page asked for something we couldn't make sense of. Try reloading it."


class ErrorResponse(BaseModel):
    code: str
    message: str


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        body = ErrorResponse(code=exc.code, message=exc.message)
        return JSONResponse(status_code=exc.http_status, content=body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI's own body lists field paths, which mean nothing to a business
        # user; the frontend gets the same {code, message} shape as everything else.
        body = ErrorResponse(code="invalid_request", message=INVALID_REQUEST)
        return JSONResponse(status_code=422, content=body.model_dump())
