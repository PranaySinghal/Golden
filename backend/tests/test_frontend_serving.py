"""The built frontend, served beside the API in the one-container deploy."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import health
from app.api.frontend import frontend_router


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    (tmp_path / "index.html").write_text("<p>the app</p>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("not yours")
    app = FastAPI()
    app.include_router(health.router)
    app.include_router(frontend_router(tmp_path))
    return TestClient(app)


def test_the_page_is_served_at_the_root(client: TestClient) -> None:
    assert client.get("/").text == "<p>the app</p>"


def test_built_files_are_served_as_themselves(client: TestClient) -> None:
    assert client.get("/assets/app.js").text == "console.log(1)"


def test_any_other_page_opens_the_app(client: TestClient) -> None:
    assert client.get("/review/somewhere").text == "<p>the app</p>"


def test_the_api_still_answers_first(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_a_missing_api_path_is_not_the_page(client: TestClient) -> None:
    response = client.get("/api/nope")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_nothing_outside_the_folder_is_served(client: TestClient) -> None:
    assert client.get("/../secret.txt").text == "<p>the app</p>"
    assert client.get("/%2e%2e/secret.txt").text == "<p>the app</p>"


def test_a_folder_without_a_built_page_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="build the frontend"):
        frontend_router(tmp_path)
