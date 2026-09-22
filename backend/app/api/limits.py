"""Keeping an upload within its size, before the body is read and while reading it."""

from typing import BinaryIO

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.errors import ErrorResponse
from app.config import MAX_RECIPE_BYTES, Settings
from app.errors import FileTooLargeError

# Room for the multipart envelope, and for saved steps sent alongside the file.
# Without the second allowance, attaching a recipe to a near-limit file would be
# turned away for a size the data itself is under.
MULTIPART_OVERHEAD_BYTES = 64 * 1024 + MAX_RECIPE_BYTES

_CHUNK_BYTES = 1024 * 1024


def read_within_limit(stream: BinaryIO, limit: int) -> bytes:
    """Read an upload, stopping as soon as it goes over `limit`."""
    chunks: list[bytes] = []
    size = 0
    while chunk := stream.read(_CHUNK_BYTES):
        size += len(chunk)
        if size > limit:
            raise FileTooLargeError(size, limit)
        chunks.append(chunk)
    return b"".join(chunks)


class UploadSizeMiddleware(BaseHTTPMiddleware):
    """Reject uploads that declare a size over the limit before reading the body.

    Without this, the multipart parser spools the whole request to disk first.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "POST" and request.url.path == "/api/datasets":
            settings: Settings = request.app.state.settings
            declared = request.headers.get("content-length", "")
            limit = settings.max_upload_bytes
            if declared.isdigit() and int(declared) > limit + MULTIPART_OVERHEAD_BYTES:
                error = FileTooLargeError(int(declared), limit)
                body = ErrorResponse(code=error.code, message=error.message)
                return JSONResponse(status_code=error.http_status, content=body.model_dump())
        return await call_next(request)
