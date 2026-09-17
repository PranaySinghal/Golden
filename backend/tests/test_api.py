from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import register_error_handlers
from app.errors import FileTooLargeError
from app.main import app


def test_health() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_includes_health() -> None:
    schema = TestClient(app).get("/openapi.json").json()

    assert schema["paths"]["/api/health"]["get"]["operationId"] == "getHealth"


def test_app_errors_become_friendly_json() -> None:
    test_app = FastAPI()
    register_error_handlers(test_app)

    @test_app.get("/boom")
    def boom() -> None:
        raise FileTooLargeError(size_bytes=60 * 1024 * 1024, limit_bytes=50 * 1024 * 1024)

    response = TestClient(test_app).get("/boom")

    assert response.status_code == 413
    assert response.json() == {
        "code": "file_too_large",
        "message": "This file is 60 MB, which is over the 50 MB limit. "
        "Try a smaller file or split it up.",
    }
