"""The canvas endpoints: the table, adding a column, and ideas for more."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.provider import Provider, ProviderError
from app.api.deps import get_provider
from app.config import Settings
from app.main import app
from tests.conftest import SAMPLES_DIR

COMPANIES = (
    "Company,Ticker,City,Employees\n"
    "Acme Tools,ACM,Leeds,120\n"
    "Birch Foods,BRF,Lyon,45\n"
    "Cobalt Air,CBA,Oslo,300\n"
)
IDEAS = json.dumps(
    {
        "about": "A list of companies and where they are based.",
        "columns": [
            {"name": "Revenue", "reason": "Shows how big each company is."},
            {"name": "Company", "reason": "Already there."},
            {"name": "Founded", "reason": "Acme Tools was founded in 1987."},
        ],
    }
)


class FakeProvider:
    name = "fake"

    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.calls = 0
        self.seen: list[str] = []

    def complete(self, system: str, user: str, timeout_ms: int) -> str:
        self.calls += 1
        self.seen.append(user)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _no_model_by_default() -> Iterator[None]:
    app.state.settings = Settings()
    yield
    app.state.settings = Settings()
    app.dependency_overrides.pop(get_provider, None)


def use_provider(provider: Provider) -> None:
    app.state.settings = Settings(llm_provider="anthropic", llm_api_key="test-key")
    app.dependency_overrides[get_provider] = lambda: provider


def upload(client: TestClient, data: bytes | str = COMPANIES, name: str = "file.csv") -> str:
    raw = data.encode() if isinstance(data, str) else data
    return str(client.post("/api/datasets", files={"file": (name, raw, "text/csv")}).json()["id"])


def add(client: TestClient, dataset: str, **body: Any) -> Any:
    return client.post(f"/api/datasets/{dataset}/canvas/columns", json=body)


def suggested(client: TestClient, dataset: str, smart: bool = True) -> dict[str, Any]:
    response = client.get(
        f"/api/datasets/{dataset}/canvas/suggestions", params={"smart": str(smart).lower()}
    )
    assert response.status_code == 200
    return dict(response.json())


def names(body: dict[str, Any]) -> list[str]:
    return [suggestion["name"] for suggestion in body["suggestions"]]


# --- the table and adding to it -------------------------------------------------------------


def test_the_canvas_shows_the_table_as_it_stands(client: TestClient) -> None:
    dataset = upload(client)

    body = client.get(f"/api/datasets/{dataset}/canvas").json()

    assert [column["name"] for column in body["columns"]] == [
        "Company",
        "Ticker",
        "City",
        "Employees",
    ]
    assert body["rows"][0][:3] == ["Acme Tools", "ACM", "Leeds"]
    assert body["row_count"] == 3
    assert all(column["step_id"] is None for column in body["columns"])


def test_adding_a_column_puts_it_in_the_table_the_recipe_and_the_download(
    client: TestClient,
) -> None:
    dataset = upload(client)

    response = add(client, dataset, name="Revenue", value="To fill in", insert_after="Ticker")

    assert response.status_code == 200
    body = response.json()
    assert [column["name"] for column in body["columns"]][:3] == ["Company", "Ticker", "Revenue"]
    assert body["rows"][0][2] == "To fill in"
    step = body["recipe"]["steps"][-1]
    assert step["type"] == "add_column"
    assert step["label"] == "Add a column"
    assert body["columns"][2]["step_id"] == step["id"]
    exported = client.get(f"/api/datasets/{dataset}/export", params={"format": "csv"})
    assert "Company,Ticker,Revenue,City" in exported.text
    saved = client.get(f"/api/datasets/{dataset}/export", params={"format": "recipe"}).json()
    assert saved["recipe"]["steps"][-1]["name"] == "Revenue"


def test_an_added_column_can_be_undone_and_removed(client: TestClient) -> None:
    dataset = upload(client)
    before = client.get(f"/api/datasets/{dataset}/canvas").json()
    step_id = add(client, dataset, name="Notes").json()["recipe"]["steps"][-1]["id"]

    client.post(f"/api/datasets/{dataset}/recipe/undo")
    assert client.get(f"/api/datasets/{dataset}/canvas").json()["columns"] == before["columns"]

    step_id = add(client, dataset, name="Notes").json()["recipe"]["steps"][-1]["id"]
    client.delete(f"/api/datasets/{dataset}/recipe/steps/{step_id}")
    assert client.get(f"/api/datasets/{dataset}/canvas").json()["columns"] == before["columns"]


def test_a_name_already_in_use_is_explained(client: TestClient) -> None:
    dataset = upload(client)

    response = add(client, dataset, name="company")

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_step"
    assert "already a column" in response.json()["message"]


@pytest.mark.parametrize("body", [{"name": "   "}, {}, {"name": "x", "value": "v" * 1001}])
def test_a_column_needs_a_name_and_a_sensible_placeholder(
    client: TestClient, body: dict[str, Any]
) -> None:
    assert add(client, upload(client), **body).status_code == 422


def test_an_unknown_file_is_a_clear_404(client: TestClient) -> None:
    assert client.get("/api/datasets/nope/canvas").status_code == 404
    assert add(client, "nope", name="Notes").status_code == 404
    assert client.get("/api/datasets/nope/canvas/suggestions").status_code == 404


def test_an_empty_added_column_moves_no_answers(client: TestClient) -> None:
    dataset = upload(client, (SAMPLES_DIR / "store_orders.csv").read_bytes(), "store_orders.csv")
    client.get(f"/api/datasets/{dataset}/issues")
    before = client.get(f"/api/datasets/{dataset}/compare").json()

    add(client, dataset, name="Notes")
    after = client.get(f"/api/datasets/{dataset}/compare").json()

    assert after["cards"] == before["cards"]


# --- ideas ----------------------------------------------------------------------------------


def test_without_a_model_the_built_in_ideas_answer(client: TestClient) -> None:
    body = suggested(client, upload(client))

    assert body["status"] == "off"
    assert 3 <= len(body["suggestions"]) <= 5
    assert names(body)[:2] == ["Stock price", "Industry"]


def test_an_idea_stops_being_offered_once_it_is_added(client: TestClient) -> None:
    dataset = upload(client)
    add(client, dataset, name="Industry")

    assert "Industry" not in names(suggested(client, dataset))


def test_a_models_ideas_are_checked_and_topped_up(client: TestClient) -> None:
    provider = FakeProvider(IDEAS)
    use_provider(provider)
    dataset = upload(client)

    body = suggested(client, dataset)

    assert body["status"] == "ready"
    assert body["about"] == "A list of companies and where they are based."
    # "Company" exists and "Founded" brought a year the file doesn't hold.
    assert names(body)[0] == "Revenue"
    assert "Company" not in names(body)
    assert "Founded" not in names(body)
    assert body["suggestions"][0]["source"] == "ai"
    assert len(body["suggestions"]) == 5


def test_a_model_is_asked_once_per_file_and_never_for_the_quick_list(client: TestClient) -> None:
    provider = FakeProvider(IDEAS)
    use_provider(provider)
    dataset = upload(client)

    quick = suggested(client, dataset, smart=False)
    assert provider.calls == 0
    assert quick["status"] == "off"

    suggested(client, dataset)
    add(client, dataset, name="Revenue")
    again = suggested(client, dataset)

    assert provider.calls == 1
    assert "Revenue" not in names(again)


def test_a_model_is_shown_no_more_than_five_rows(client: TestClient) -> None:
    provider = FakeProvider(IDEAS)
    use_provider(provider)
    rows = "".join(f"Company {i},T{i},Town {i},{i}\n" for i in range(40))

    suggested(client, upload(client, "Company,Ticker,City,Employees\n" + rows))

    sent = json.loads(provider.seen[0])
    assert len(sent["sample_rows"]) == 5
    assert "Company 30" not in provider.seen[0]


@pytest.mark.parametrize(
    "reply",
    [ProviderError("down"), "not json at all", json.dumps({"columns": [{"name": "x"}]})],
    ids=["unreachable", "not-json", "wrong-shape"],
)
def test_a_model_that_fails_leaves_the_built_in_ideas(
    client: TestClient, reply: str | Exception
) -> None:
    use_provider(FakeProvider(reply))

    body = suggested(client, upload(client))

    assert body["status"] == "failed"
    assert names(body)[:2] == ["Stock price", "Industry"]
    assert all(suggestion["source"] == "rules" for suggestion in body["suggestions"])
