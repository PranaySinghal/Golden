"""The "what changed" endpoint, and the two downloads."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.compare.before import RULES
from app.main import app
from app.steps.models import RecipeFile
from tests.conftest import SAMPLES_DIR

EMPLOYEE = (SAMPLES_DIR / "Messy_Employee_dataset.csv").read_bytes()
UTF8_BOM = b"\xef\xbb\xbf"


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def upload(client: TestClient, data: bytes | str, name: str = "file.csv") -> str:
    raw = data.encode() if isinstance(data, str) else data
    response = client.post("/api/datasets", files={"file": (name, raw, "text/csv")})
    return str(response.json()["id"])


def accept_all(client: TestClient, dataset: str) -> dict[str, Any]:
    """Take every suggestion, answering each question the way it recommends."""
    listed = client.get(f"/api/datasets/{dataset}/issues").json()
    for issue in listed["issues"]:
        if issue["state"] != "available":
            continue
        choice = None
        if issue["ask"]:
            wanted = [c for c in issue["ask"]["choices"] if c["recommended"]] or issue["ask"][
                "choices"
            ]
            choice = wanted[0]["id"]
        client.post(
            f"/api/datasets/{dataset}/issues/{issue['id']}/accept", json={"choice_id": choice}
        )
    return dict(client.get(f"/api/datasets/{dataset}/issues").json())


def compare(client: TestClient, dataset: str) -> dict[str, Any]:
    response = client.get(f"/api/datasets/{dataset}/compare")
    assert response.status_code == 200
    return dict(response.json())


def card_for(body: dict[str, Any], label_part: str) -> dict[str, Any]:
    everything = [*body["cards"], *body["unlocked"]]
    return next(card for card in everything if label_part in card["label"])


@pytest.fixture(scope="module")
def employee(client: TestClient) -> dict[str, Any]:
    """The employee file with every suggestion taken, compared once."""
    dataset = upload(client, EMPLOYEE, "Messy_Employee_dataset.csv")
    accept_all(client, dataset)
    return {"id": dataset, "body": compare(client, dataset)}


# --- the shape of the answer ----------------------------------------------------------------


def test_cards_are_ranked_by_impact(employee: dict[str, Any]) -> None:
    impacts = [card["impact"] for card in employee["body"]["cards"]]

    assert impacts == sorted(impacts, reverse=True)


def test_every_question_is_accounted_for(employee: dict[str, Any]) -> None:
    body = employee["body"]

    assert body["questions_asked"] == len(body["cards"]) + len(body["unlocked"]) + len(
        body["unchanged"]
    )


def test_the_explainer_rules_come_from_the_one_place_they_live(
    employee: dict[str, Any],
) -> None:
    assert employee["body"]["before_rules"] == list(RULES)


def test_a_changed_answer_carries_both_sides_and_the_change(employee: dict[str, Any]) -> None:
    card = card_for(employee["body"], 'different "Phone"')

    assert card["kind"] == "headline"
    assert (card["before"]["value"], card["after"]["value"]) == (1020.0, 928.0)
    assert card["change"] == -92.0
    assert card["relative_change"] == pytest.approx(-0.0902, abs=1e-4)
    assert card["changed"] is True


def test_a_changed_answer_says_which_steps_moved_it(
    client: TestClient, employee: dict[str, Any]
) -> None:
    card = card_for(employee["body"], 'different "Phone"')
    recipe = client.get(f"/api/datasets/{employee['id']}/recipe").json()

    assert card["why"]["method"] == "exact"
    assert card["why"]["step_ids"]
    assert set(card["why"]["step_ids"]) <= {step["id"] for step in recipe["steps"]}
    assert [group["step_ids"] for group in card["why"]["groups"]]


def test_questions_the_raw_file_couldnt_answer_are_kept_apart(employee: dict[str, Any]) -> None:
    unlocked = employee["body"]["unlocked"]

    assert [card["label"] for card in unlocked]
    assert all(card["unlocked"] for card in unlocked)
    assert all(card["before"]["answerable"] is False for card in unlocked)
    assert all(card not in employee["body"]["cards"] for card in unlocked)


def test_a_breakdown_card_carries_its_groups(employee: dict[str, Any]) -> None:
    card = card_for(employee["body"], 'each "Department"')

    assert card["kind"] == "breakdown"
    assert len(card["groups"]) == 6
    assert all(group["label"] for group in card["groups"])


def test_a_trend_card_is_marked_as_one(client: TestClient) -> None:
    """Store orders' dates are day-first, so reading them moves the months."""
    orders = (SAMPLES_DIR / "store_orders.csv").read_bytes()
    dataset = upload(client, orders, "store_orders.csv")
    accept_all(client, dataset)

    trend = next(card for card in compare(client, dataset)["cards"] if card["kind"] == "trend")

    assert 'by "Order Date"' in trend["label"]
    assert trend["groups"]


# --- what the charts need -------------------------------------------------------------------


def test_merged_spellings_are_a_note_not_a_vanishing_bar(client: TestClient) -> None:
    """ "Sales " folding into "Sales" isn't rows going missing, so it gets no bar.

    Spacing is what a spreadsheet sees as a different value (rule B5), so that's
    what makes two groups become one.
    """
    rows = [f"{i},{['Sales', 'Sales ', 'Sales', 'Support'][i % 4]}" for i in range(40)]
    dataset = upload(client, "id,team\n" + "\n".join(rows) + "\n")
    accept_all(client, dataset)

    card = card_for(compare(client, dataset), 'each "team"')

    assert [(note["label"], note["into"]) for note in card["merged"]] == [("Sales ", "Sales")]
    assert all(group["label"] != "Sales " for group in card["groups"])
    sales = next(group for group in card["groups"] if group["label"] == "Sales")
    assert (sales["before"], sales["after"]) == (20.0, 30.0)


def test_a_group_that_appears_in_a_count_starts_at_zero(client: TestClient) -> None:
    """Splitting a column makes groups that had no rows before, which is a real zero."""
    dataset = upload(client, EMPLOYEE, "Messy_Employee_dataset.csv")
    accept_all(client, dataset)

    card = card_for(compare(client, dataset), 'each "Region"')

    assert card["measure"] == "count"
    assert all(group["before"] == 0 for group in card["groups"])
    assert all(group["status"] == "appeared" for group in card["groups"])


def test_a_group_that_appears_in_an_average_has_no_before_value(client: TestClient) -> None:
    """An average over no values has no answer; zero would be a different claim."""
    dataset = upload(client, EMPLOYEE, "Messy_Employee_dataset.csv")
    accept_all(client, dataset)

    card = card_for(compare(client, dataset), 'average "Salary" for each "Region"')

    assert card["measure"] == "avg"
    assert all(group["before"] is None for group in card["groups"])
    assert all(group["after"] is not None for group in card["groups"])


# --- changing an answer ---------------------------------------------------------------------


def test_changing_an_answer_only_re_asks_what_it_reaches(client: TestClient) -> None:
    dataset = upload(client, EMPLOYEE, "Messy_Employee_dataset.csv")
    listed = accept_all(client, dataset)
    compare(client, dataset)
    placeholders = next(i for i in listed["issues"] if i["detector"] == "placeholders")
    other = next(
        c for c in placeholders["ask"]["choices"] if c["id"] != placeholders["chosen_choice_id"]
    )

    client.post(
        f"/api/datasets/{dataset}/issues/{placeholders['id']}/accept",
        json={"choice_id": other["id"]},
    )
    again = compare(client, dataset)

    assert 0 < again["recomputed"] < again["questions_asked"]
    salary = card_for(again, 'average "Salary"?')
    assert salary["changed"] is True


def test_going_back_to_an_earlier_answer_costs_nothing(client: TestClient) -> None:
    dataset = upload(client, EMPLOYEE, "Messy_Employee_dataset.csv")
    listed = accept_all(client, dataset)
    first = compare(client, dataset)
    placeholders = next(i for i in listed["issues"] if i["detector"] == "placeholders")
    chosen = placeholders["chosen_choice_id"]
    other = next(c for c in placeholders["ask"]["choices"] if c["id"] != chosen)

    for choice in (other["id"], chosen):
        client.post(
            f"/api/datasets/{dataset}/issues/{placeholders['id']}/accept",
            json={"choice_id": choice},
        )
        back = compare(client, dataset)

    assert back["recomputed"] == 0
    assert back["recipe_key"] == first["recipe_key"]
    assert [card["label"] for card in back["cards"]] == [card["label"] for card in first["cards"]]


def test_the_recipe_carries_the_key_the_screen_watches(client: TestClient) -> None:
    dataset = upload(client, EMPLOYEE, "Messy_Employee_dataset.csv")

    recipe = client.get(f"/api/datasets/{dataset}/recipe").json()

    assert recipe["recipe_key"]
    assert compare(client, dataset)["recipe_key"] == recipe["recipe_key"]


# --- nothing to show ------------------------------------------------------------------------


def test_a_file_with_nothing_applied_says_so(client: TestClient) -> None:
    dataset = upload(client, "Name,City\nAnn,Paris\nBo,Rome\nCy,Lyon\n")

    body = compare(client, dataset)

    assert body["has_steps"] is False
    assert body["cards"] == []
    assert body["unchanged"]


def test_cleaning_that_changes_no_answer_still_reports_what_it_checked(
    client: TestClient,
) -> None:
    rows = [f"{i}, Paris " for i in range(20)]
    dataset = upload(client, "id,city\n" + "\n".join(rows) + "\n")
    accept_all(client, dataset)

    body = compare(client, dataset)

    assert body["has_steps"] is True
    assert body["cards"] == []
    assert body["unchanged"]
    assert body["questions_asked"] == len(body["unchanged"])


def test_an_unknown_file_is_a_clear_404(client: TestClient) -> None:
    response = client.get("/api/datasets/nope/compare")

    assert response.status_code == 404
    assert response.json()["code"] == "dataset_not_found"


# --- downloads ------------------------------------------------------------------------------


def test_the_cleaned_file_downloads_as_a_spreadsheet_would_want_it(
    client: TestClient, employee: dict[str, Any]
) -> None:
    response = client.get(f"/api/datasets/{employee['id']}/export", params={"format": "csv"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "Messy_Employee_dataset%20%28tidied%29.csv" in response.headers["content-disposition"]
    assert response.content.startswith(UTF8_BOM)
    header = response.content[len(UTF8_BOM) :].split(b"\n")[0].decode()
    assert "Employee_ID" in header
    assert "_row_id" not in header


def test_the_recipe_downloads_as_a_file_that_can_be_replayed(
    client: TestClient, employee: dict[str, Any]
) -> None:
    response = client.get(f"/api/datasets/{employee['id']}/export", params={"format": "recipe"})

    assert response.status_code == 200
    assert "Messy_Employee_dataset.tidylab.json" in response.headers["content-disposition"]
    recipe_file = RecipeFile.model_validate(json.loads(response.content))
    assert recipe_file.source.filename == "Messy_Employee_dataset.csv"
    assert recipe_file.recipe.steps
    assert recipe_file.requires_columns


def test_a_download_format_we_dont_have_is_refused(
    client: TestClient, employee: dict[str, Any]
) -> None:
    response = client.get(f"/api/datasets/{employee['id']}/export", params={"format": "pdf"})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
