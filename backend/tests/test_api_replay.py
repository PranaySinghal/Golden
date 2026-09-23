"""Uploading a file with steps saved from an earlier one, over HTTP."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import SAMPLES_DIR

EMPLOYEE = (SAMPLES_DIR / "Messy_Employee_dataset.csv").read_bytes()
MESSIER = (SAMPLES_DIR / "Messy_Employee_dataset_messier.csv").read_bytes()
ORDERS = (SAMPLES_DIR / "store_orders.csv").read_bytes()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def upload(client: TestClient, name: str, data: bytes, recipe: bytes | None = None) -> dict:
    files = {"file": (name, data, "text/csv")}
    if recipe is not None:
        files["recipe"] = ("saved.tidylab.json", recipe, "application/json")
    response = client.post("/api/datasets", files=files)
    assert response.status_code == 201, response.text
    return response.json()


def cleaned_once(client: TestClient, name: str, data: bytes) -> bytes:
    """A file taken through review, and the steps it ended up with."""
    dataset = upload(client, name, data)
    client.get(f"/api/datasets/{dataset['id']}/issues")
    saved = client.get(f"/api/datasets/{dataset['id']}/export", params={"format": "recipe"})
    assert saved.status_code == 200
    return saved.content


def test_steps_saved_from_one_file_run_on_the_next(client: TestClient) -> None:
    recipe = cleaned_once(client, "Messy_Employee_dataset.csv", EMPLOYEE)

    body = upload(client, "next-month.csv", MESSIER, recipe)

    outcome = body["recipe_outcome"]
    assert outcome["applied"] is True
    assert outcome["steps_applied"] > 0
    assert outcome["source_filename"] == "Messy_Employee_dataset.csv"
    assert outcome["problems"] == []

    panel = client.get(f"/api/datasets/{body['id']}/recipe")
    assert panel.status_code == 200
    assert panel.json()["steps"]


def test_the_review_screen_still_loads_after_a_replay(client: TestClient) -> None:
    """The steps detection proposes carry the ids a saved recipe already has.

    Adding one twice is an error, so this is the request that would never
    return if a step's identity were only its id.
    """
    recipe = cleaned_once(client, "Messy_Employee_dataset.csv", EMPLOYEE)
    body = upload(client, "next-month.csv", EMPLOYEE, recipe)

    issues = client.get(f"/api/datasets/{body['id']}/issues")

    assert issues.status_code == 200
    assert issues.json()["issues"]


def test_the_cards_whose_work_is_already_done_say_so(client: TestClient) -> None:
    recipe = cleaned_once(client, "Messy_Employee_dataset.csv", EMPLOYEE)
    body = upload(client, "next-month.csv", EMPLOYEE, recipe)

    issues = client.get(f"/api/datasets/{body['id']}/issues").json()["issues"]

    applied = [issue for issue in issues if issue["state"] == "applied"]
    assert applied
    panel_ids = {
        step["id"] for step in client.get(f"/api/datasets/{body['id']}/recipe").json()["steps"]
    }
    # The ids a card hands back point at steps really in the panel.
    for issue in applied:
        assert set(issue["step_ids"]) <= panel_ids
    # And each of those steps knows which card explains it.
    steps = client.get(f"/api/datasets/{body['id']}/recipe").json()["steps"]
    assert any(step["issue_id"] for step in steps)


def test_steps_that_dont_fit_leave_the_upload_alone(client: TestClient) -> None:
    recipe = cleaned_once(client, "Messy_Employee_dataset.csv", EMPLOYEE)

    body = upload(client, "store_orders.csv", ORDERS, recipe)

    outcome = body["recipe_outcome"]
    assert outcome["applied"] is False
    assert len(outcome["problems"]) > 1, "every reason, not just the first"
    # The file itself is perfectly usable.
    assert body["row_count"] == 64
    assert client.get(f"/api/datasets/{body['id']}/issues").status_code == 200


def test_a_file_that_isnt_a_recipe_is_explained(client: TestClient) -> None:
    body = upload(client, "people.csv", EMPLOYEE, b"not json {")

    outcome = body["recipe_outcome"]
    assert outcome["applied"] is False
    assert "isn't a recipe file" in outcome["problems"][0]


def test_reading_the_dataset_again_does_not_repeat_the_message(client: TestClient) -> None:
    recipe = cleaned_once(client, "Messy_Employee_dataset.csv", EMPLOYEE)
    body = upload(client, "next-month.csv", MESSIER, recipe)

    again = client.get(f"/api/datasets/{body['id']}").json()

    assert again["recipe_outcome"] is None


def test_saved_steps_are_attached_at_upload_only(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/datasets/{dataset_id}/recipe/replay" not in schema["paths"]
    assert "RecipeOutcomeView" in schema["components"]["schemas"]
