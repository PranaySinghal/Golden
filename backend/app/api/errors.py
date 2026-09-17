from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.errors import AppError


class ErrorResponse(BaseModel):
    code: str
    message: str


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        body = ErrorResponse(code=exc.code, message=exc.message)
        return JSONResponse(status_code=exc.http_status, content=body.model_dump())
