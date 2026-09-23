"""Serve the built frontend from the same process as the API, for the one-container deploy.

In development Vite serves the page and forwards /api here, so none of this is
mounted. Registered after every API router: it answers any GET the API didn't,
with the file if there is one and the page itself otherwise, so a reload on
any screen still opens the app.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

INDEX = "index.html"


def frontend_router(static_dir: Path) -> APIRouter:
    root = static_dir.resolve()
    index = root / INDEX
    if not index.is_file():
        raise RuntimeError(f"STATIC_DIR {static_dir} has no {INDEX}; build the frontend first.")

    router = APIRouter(include_in_schema=False)

    @router.get("/{path:path}")
    def serve(path: str) -> FileResponse:
        # An API path nothing answered is a missing endpoint, not a page.
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        wanted = (root / path).resolve()
        if path and wanted.is_file() and wanted.is_relative_to(root):
            return FileResponse(wanted)
        return FileResponse(index)

    return router
