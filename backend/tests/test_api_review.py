"""The review endpoints: what the screen asks for, and what it gets back."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import SAMPLES_DIR

EMPLOYEE = (SAMPLES_DIR / "Messy_Employee_dataset.csv").read_bytes()


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def upload(client: TestClient) -> str:
    response = client.post(
        "/api/datasets", files={"file": ("Messy_Employee_dataset.csv", EMPLOYEE, "text/csv")}
    )
    return str(response.json()["id"])


@pytest.fixture(scope="module")
def findings(client: TestClient) -> tuple[list[Any], list[Any]]:
    """Detect and score once; every test then starts from the same findings."""
    dataset = upload(client)
    client.get(f"/api/datasets/{dataset}/issues")
    session = app.state.store.get(dataset)
    return list(session.issues or []), list(session.questions or [])


@pytest.fixture
def dataset_id(client: TestClient, findings: tuple[list[Any], list[Any]]) -> str:
    """A fresh file per test, so one test's decisions can't reach another."""
    dataset = upload(client)
    session = app.state.store.get(dataset)
    session.issues, session.questions = list(findings[0]), list(findings[1])
    return dataset


@pytest.fixture
def review(client: TestClient, dataset_id: str) -> dict[str, Any]:
    """The review as the page first sees it."""
    body: dict[str, Any] = client.get(f"/api/datasets/{dataset_id}/issues").json()
    return body


def issue_of(review: dict[str, Any], tier: str, state: str = "available") -> dict[str, Any]:
    return next(i for i in review["issues"] if i["tier"] == tier and i["state"] == state)


# --- the list ------------------------------------------------------------------------------


def test_the_list_groups_and_ranks_what_it_found(review: dict[str, Any]) -> None:
    assert set(review["counts"]) == {"safe", "likely", "ask"}
    impacts = [issue["impact"] for issue in review["issues"]]
    assert impacts == sorted(impacts, reverse=True)
    assert review["needs_decision"] == sum(
        1 for i in review["issues"] if i["tier"] == "ask" and i["state"] == "available"
    )


def test_safe_fixes_come_back_already_applied(review: dict[str, Any]) -> None:
    safe = [issue for issue in review["issues"] if issue["tier"] == "safe"]

    assert safe
    assert all(issue["state"] == "applied" for issue in safe)
    assert all(issue["step_ids"] for issue in safe)


def test_the_list_carries_the_recipe_so_the_page_needs_one_call(review: dict[str, Any]) -> None:
    recipe = review["recipe"]

    assert recipe["row_count"] == 1020
    assert recipe["can_undo"] is False
    assert [step["description"] for step in recipe["steps"]]
    assert all(step["status"] == "applied" for step in recipe["steps"])


def test_every_question_offers_its_choices(review: dict[str, Any]) -> None:
    for issue in review["issues"]:
        if issue["tier"] == "ask":
            assert len(issue["ask"]["choices"]) >= 2
            assert issue["ask"]["prompt"]


def test_an_unknown_file_is_a_clear_404(client: TestClient) -> None:
    response = client.get("/api/datasets/nope/issues")

    assert response.status_code == 404
    assert response.json()["code"] == "dataset_not_found"


# --- acting on a card ----------------------------------------------------------------------


def test_accepting_a_suggestion_returns_the_new_recipe(
    client: TestClient, dataset_id: str, review: dict[str, Any]
) -> None:
    issue = issue_of(review, "likely")
    before = len(review["recipe"]["steps"])

    response = client.post(f"/api/datasets/{dataset_id}/issues/{issue['id']}/accept", json={})

    assert response.status_code == 200
    body = response.json()
    assert len(body["steps"]) > before
    assert body["can_undo"] is True
    assert any(step["issue_id"] == issue["id"] for step in body["steps"])


def test_answering_a_question_and_changing_the_answer(
    client: TestClient, dataset_id: str, review: dict[str, Any]
) -> None:
    issue = issue_of(review, "ask")
    first, second = issue["ask"]["choices"][0], issue["ask"]["choices"][1]

    client.post(
        f"/api/datasets/{dataset_id}/issues/{issue['id']}/accept", json={"choice_id": first["id"]}
    )
    client.post(
        f"/api/datasets/{dataset_id}/issues/{issue['id']}/accept", json={"choice_id": second["id"]}
    )

    listed = client.get(f"/api/datasets/{dataset_id}/issues").json()
    answered = next(i for i in listed["issues"] if i["id"] == issue["id"])
    assert (answered["state"], answered["chosen_choice_id"]) == ("applied", second["id"])


def test_turning_a_suggestion_down_keeps_it_out(
    client: TestClient, dataset_id: str, review: dict[str, Any]
) -> None:
    issue = issue_of(review, "likely")

    client.post(f"/api/datasets/{dataset_id}/issues/{issue['id']}/reject")

    listed = client.get(f"/api/datasets/{dataset_id}/issues").json()
    turned_down = next(i for i in listed["issues"] if i["id"] == issue["id"])
    assert turned_down["state"] == "rejected"
    assert all(step["issue_id"] != issue["id"] for step in listed["recipe"]["steps"])


def test_a_question_without_an_answer_is_refused(
    client: TestClient, dataset_id: str, review: dict[str, Any]
) -> None:
    issue = issue_of(review, "ask")

    response = client.post(f"/api/datasets/{dataset_id}/issues/{issue['id']}/accept", json={})

    assert response.status_code == 422
    assert response.json()["code"] == "choice_required"


def test_an_answer_that_isnt_offered_is_refused(
    client: TestClient, dataset_id: str, review: dict[str, Any]
) -> None:
    issue = issue_of(review, "ask")

    response = client.post(
        f"/api/datasets/{dataset_id}/issues/{issue['id']}/accept", json={"choice_id": "nope"}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "choice_not_found"


def test_an_unknown_suggestion_is_a_404(client: TestClient, dataset_id: str) -> None:
    response = client.post(f"/api/datasets/{dataset_id}/issues/nope/reject")

    assert response.status_code == 404
    assert response.json()["code"] == "issue_not_found"


# --- the recipe panel ----------------------------------------------------------------------


def test_turning_a_step_off_and_undoing_it(client: TestClient, dataset_id: str) -> None:
    recipe = client.get(f"/api/datasets/{dataset_id}/recipe").json()
    step = recipe["steps"][0]

    off = client.patch(
        f"/api/datasets/{dataset_id}/recipe/steps/{step['id']}", json={"enabled": False}
    ).json()
    assert off["steps"][0]["enabled"] is False
    assert off["steps"][0]["status"] == "disabled"

    back = client.post(f"/api/datasets/{dataset_id}/recipe/undo").json()
    assert back["steps"][0]["enabled"] is True


def test_removing_a_step_and_undoing_it(client: TestClient, dataset_id: str) -> None:
    recipe = client.get(f"/api/datasets/{dataset_id}/recipe").json()
    step = recipe["steps"][-1]

    gone = client.delete(f"/api/datasets/{dataset_id}/recipe/steps/{step['id']}").json()
    assert all(other["id"] != step["id"] for other in gone["steps"])

    back = client.post(f"/api/datasets/{dataset_id}/recipe/undo").json()
    assert any(other["id"] == step["id"] for other in back["steps"])


def test_a_step_that_isnt_there_is_a_404(client: TestClient, dataset_id: str) -> None:
    response = client.patch(
        f"/api/datasets/{dataset_id}/recipe/steps/nope", json={"enabled": False}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "step_not_found"


def test_undo_with_nothing_to_undo_is_not_an_error(client: TestClient, dataset_id: str) -> None:
    while client.get(f"/api/datasets/{dataset_id}/recipe").json()["can_undo"]:
        client.post(f"/api/datasets/{dataset_id}/recipe/undo")

    response = client.post(f"/api/datasets/{dataset_id}/recipe/undo")

    assert response.status_code == 200
    assert response.json()["can_undo"] is False


# --- previews ------------------------------------------------------------------------------


def test_previewing_a_suggestion(
    client: TestClient, dataset_id: str, review: dict[str, Any]
) -> None:
    issue = next(i for i in review["issues"] if i["detector"] == "contact_formats")

    response = client.get(f"/api/datasets/{dataset_id}/preview", params={"issue_id": issue["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["columns"]
    assert len(body["rows"]) <= 5
    for row in body["rows"]:
        assert set(row["cells"]) == set(body["columns"])


def test_previewing_one_answer_to_a_question(
    client: TestClient, dataset_id: str, review: dict[str, Any]
) -> None:
    issue = issue_of(review, "ask")
    choice = issue["ask"]["choices"][-1]

    response = client.get(
        f"/api/datasets/{dataset_id}/preview",
        params={"issue_id": issue["id"], "choice_id": choice["id"]},
    )

    assert response.status_code == 200


def test_previewing_a_step_that_is_already_in_the_recipe(
    client: TestClient, dataset_id: str
) -> None:
    recipe = client.get(f"/api/datasets/{dataset_id}/recipe").json()
    step = next(s for s in recipe["steps"] if s["cells_changed"])

    response = client.get(
        f"/api/datasets/{dataset_id}/preview", params={"step_id": step["id"], "limit": 2}
    )

    body = response.json()
    assert len(body["rows"]) <= 2
    assert body["changed_rows"] > 0


def test_a_preview_needs_something_to_preview(client: TestClient, dataset_id: str) -> None:
    response = client.get(f"/api/datasets/{dataset_id}/preview")

    assert response.status_code == 422
    assert response.json()["code"] == "preview_target_required"


def test_a_preview_row_limit_is_checked(client: TestClient, dataset_id: str) -> None:
    response = client.get(
        f"/api/datasets/{dataset_id}/preview", params={"step_id": "x", "limit": 999}
    )

    assert response.status_code == 422
