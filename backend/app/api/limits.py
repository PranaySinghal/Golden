from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.errors import ErrorResponse
from app.config import Settings
from app.errors import FileTooLargeError

# Room for the multipart envelope around the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


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
