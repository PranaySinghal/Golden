"""Connectors end to end through the API, with stand-in services."""

import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.provider import ProviderError
from app.api.deps import get_connectors
from app.config import Settings
from app.connectors.models import NotFoundError, Quote, TimedOutError
from app.connectors.runner import Runtime
from app.main import app
from tests.conftest import SAMPLES_DIR
from tests.connector_fakes import (
    NOW,
    Clock,
    FakeGeocoder,
    FakeModel,
    FakeQuotes,
    FakeSymbols,
    runtime,
)

SHOPS = "Shop,Zip\nNorth,90210\nSouth,90210\nEast,10001\nWest,99999\nMid,10001\n"
FIRMS = "Firm\nApple Inc.\nAlphabet Inc\nAcme Tools Ltd\nMicrosoft Corp\napple inc\n"
OPENING = int(NOW.timestamp()) - 3600


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _defaults() -> Iterator[None]:
    app.state.settings = Settings()
    yield
    app.state.settings = Settings()
    app.dependency_overrides.pop(get_connectors, None)


def use(services: Runtime) -> Runtime:
    app.dependency_overrides[get_connectors] = lambda: services
    return services


def upload(client: TestClient, data: bytes | str, name: str = "file.csv") -> str:
    raw = data.encode() if isinstance(data, str) else data
    return str(client.post("/api/datasets", files={"file": (name, raw, "text/csv")}).json()["id"])


def switch(client: TestClient, dataset: str, connector: str, active: bool = True) -> Any:
    return client.put(f"/api/datasets/{dataset}/connectors/{connector}", json={"active": active})


def switch_all_on(client: TestClient, dataset: str) -> str:
    for connector in ("postal_geocode", "company_ticker", "stock_price"):
        assert switch(client, dataset, connector).status_code == 200
    return dataset


def look_up(client: TestClient, dataset: str, **body: Any) -> Any:
    return client.post(f"/api/datasets/{dataset}/connectors/lookups", json=body)


def overview(client: TestClient, dataset: str) -> dict[str, Any]:
    response = client.get(f"/api/datasets/{dataset}/connectors")
    assert response.status_code == 200
    return dict(response.json())


def canvas(client: TestClient, dataset: str) -> dict[str, Any]:
    return dict(client.get(f"/api/datasets/{dataset}/canvas").json())


def column(body: dict[str, Any], name: str) -> list[Any]:
    position = [c["name"] for c in body["columns"]].index(name)
    return [row[position] for row in body["rows"]]


# --- with nothing set up --------------------------------------------------------------------


def test_with_no_services_set_up_everything_is_listed_as_off(client: TestClient) -> None:
    listed = client.get("/api/connectors").json()

    assert [c["id"] for c in listed] == [
        "postal_geocode",
        "company_ticker",
        "stock_price",
        "ai_fill",
    ]
    assert all(c["enabled"] is False for c in listed)
    assert all(c["sends"] and c["adds"] for c in listed)


def test_with_no_services_an_offer_is_shown_but_cant_be_run(client: TestClient) -> None:
    dataset = upload(client, SHOPS)

    found = overview(client, dataset)

    assert [(o["connector"], o["column"], o["enabled"]) for o in found["offers"]] == [
        ("postal_geocode", "Zip", False)
    ]
    refused = look_up(
        client, dataset, connector="postal_geocode", column="Zip", country="US", consent=True
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "connector_off"
    assert overview(client, dataset)["recipe"]["steps"] == found["recipe"]["steps"]
    # A service the server doesn't have can't be switched on either.
    assert switch(client, dataset, "postal_geocode").json()["code"] == "connector_off"


# --- switching a service on for a file ------------------------------------------------------


def test_every_service_starts_off_for_a_new_file_and_nothing_runs_until_it_is_on(
    client: TestClient,
) -> None:
    geocoder = FakeGeocoder(
        {"90210": (34.0901, -118.4065), "10001": (1.0, 2.0), "99999": (3.0, 4.0)}
    )
    use(runtime(postal=geocoder))
    dataset = upload(client, SHOPS)

    found = overview(client, dataset)
    # The three lookup services are set up here; no model service is.
    assert [(c["enabled"], c["active"]) for c in found["connectors"]] == [
        *[(True, False)] * 3,
        (False, False),
    ]
    refused = look_up(
        client, dataset, connector="postal_geocode", column="Zip", country="US", consent=True
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "connector_inactive"
    assert geocoder.asked == []

    on = switch(client, dataset, "postal_geocode").json()
    assert [c["active"] for c in on["connectors"]] == [True, False, False, False]
    # Switching on sends nothing by itself.
    assert geocoder.asked == []
    done = look_up(
        client, dataset, connector="postal_geocode", column="Zip", country="US", consent=True
    )
    assert done.status_code == 200


def test_a_service_is_switched_on_for_one_file_not_for_every_file(client: TestClient) -> None:
    use(runtime())
    first, second = upload(client, SHOPS), upload(client, SHOPS)

    switch(client, first, "postal_geocode")

    assert overview(client, first)["connectors"][0]["active"] is True
    assert overview(client, second)["connectors"][0]["active"] is False
    assert all(c["active"] is False for c in client.get("/api/connectors").json())


def test_switching_off_keeps_what_was_looked_up_and_stops_further_lookups(
    client: TestClient,
) -> None:
    dataset, _ = shops(client)
    body = look_up(
        client, dataset, connector="postal_geocode", column="Zip", country="US", consent=True
    ).json()

    off = switch(client, dataset, "postal_geocode", active=False)

    assert off.status_code == 200
    assert column(canvas(client, dataset), "Geolocation")[0] == "34.0901, -118.4065"
    again = look_up(client, dataset, step_id=body["enrichments"][0]["step_id"])
    assert again.json()["code"] == "connector_inactive"


def test_an_unknown_service_cant_be_switched(client: TestClient) -> None:
    assert switch(client, upload(client, SHOPS), "weather").status_code == 422
    assert switch(client, "nope", "postal_geocode").status_code == 404


# --- postal codes ---------------------------------------------------------------------------


def shops(client: TestClient) -> tuple[str, FakeGeocoder]:
    geocoder = FakeGeocoder(
        {"90210": (34.0901, -118.4065), "10001": TimedOutError(), "99999": NotFoundError()}
    )
    use(runtime(postal=geocoder))
    return switch_all_on(client, upload(client, SHOPS)), geocoder


def test_nothing_is_sent_until_the_user_agrees(client: TestClient) -> None:
    dataset, geocoder = shops(client)

    refused = look_up(client, dataset, connector="postal_geocode", column="Zip", country="US")

    assert refused.status_code == 409
    assert refused.json()["code"] == "consent_required"
    assert geocoder.asked == []
    assert overview(client, dataset)["consented"] == []


def test_postal_codes_need_a_country_before_anything_is_sent(client: TestClient) -> None:
    dataset, geocoder = shops(client)
    assert overview(client, dataset)["offers"][0]["countries"][0]["code"] == "US"

    for country in (None, "ZZ", ""):
        refused = look_up(
            client,
            dataset,
            connector="postal_geocode",
            column="Zip",
            country=country,
            consent=True,
        )
        assert refused.status_code == 422

    assert geocoder.asked == []


def test_a_lookup_adds_columns_and_says_what_happened_to_each_value(
    client: TestClient,
) -> None:
    dataset, geocoder = shops(client)

    done = look_up(
        client, dataset, connector="postal_geocode", column="Zip", country="US", consent=True
    )

    assert done.status_code == 200
    body = done.json()
    # Three different codes were asked about, however many rows hold them.
    assert sorted(code for _, code in geocoder.asked) == ["10001", "90210", "99999"]
    [found] = body["enrichments"]
    assert found["into"] == ["Geolocation"]
    assert found["counts"] == {"found": 1, "timed out": 1, "not found": 1}
    assert found["examples"] == {"timed out": ["10001"], "not found": ["99999"]}
    assert found["remaining"] == 1
    assert body["offers"] == []
    assert body["consented"] == ["postal_geocode"]
    step = body["recipe"]["steps"][-1]
    assert (step["type"], step["label"]) == ("enrich_column", "Look up new columns")

    table = canvas(client, dataset)
    here = "34.0901, -118.4065"
    assert column(table, "Geolocation") == [here, here, None, None, None]
    assert table["reasons"]["Geolocation"] == [None, None, "timed out", "not found", "timed out"]

    exported = client.get(f"/api/datasets/{dataset}/export", params={"format": "csv"}).text
    assert "Shop,Zip,Geolocation" in exported
    assert 'North,90210,"34.0901, -118.4065"' in exported
    assert "East,10001," in exported


def test_looking_up_again_fills_in_what_failed_and_undo_brings_the_old_answers_back(
    client: TestClient,
) -> None:
    dataset, geocoder = shops(client)
    first = look_up(
        client, dataset, connector="postal_geocode", column="Zip", country="US", consent=True
    ).json()
    step_id = first["enrichments"][0]["step_id"]
    geocoder.answers = {**geocoder.answers, "10001": (40.7128, -74.006)}
    geocoder.asked.clear()

    # Consent was given for this connector on this file; it isn't asked for twice.
    again = look_up(client, dataset, step_id=step_id).json()

    # Only the value that failed is asked about again.
    assert geocoder.asked == [("US", "10001")]
    assert again["enrichments"][0]["counts"] == {"found": 2, "not found": 1}
    assert again["enrichments"][0]["remaining"] == 0
    assert len(again["recipe"]["steps"]) == len(first["recipe"]["steps"])
    assert column(canvas(client, dataset), "Geolocation")[2] == "40.7128, -74.006"

    client.post(f"/api/datasets/{dataset}/recipe/undo")
    assert column(canvas(client, dataset), "Geolocation")[2] is None

    client.post(f"/api/datasets/{dataset}/recipe/undo")
    assert "Geolocation" not in [c["name"] for c in canvas(client, dataset)["columns"]]


def test_a_lookup_that_isnt_there_or_cant_run_is_explained(client: TestClient) -> None:
    dataset, _ = shops(client)

    assert look_up(client, dataset, step_id="000000000000", consent=True).status_code == 404
    assert look_up(client, dataset, connector="postal_geocode", consent=True).status_code == 422
    missing = look_up(
        client, dataset, connector="postal_geocode", column="Nope", country="US", consent=True
    )
    assert missing.status_code == 422
    assert client.get("/api/datasets/nope/connectors").status_code == 404


def test_new_columns_get_a_free_name(client: TestClient) -> None:
    geocoder = FakeGeocoder({"90210": (1.0, 2.0), "10001": (3.0, 4.0)})
    use(runtime(postal=geocoder))
    dataset = switch_all_on(client, upload(client, "Geolocation,Zip\nx,90210\ny,90210\nz,10001\n"))

    body = look_up(
        client, dataset, connector="postal_geocode", column="Zip", country="US", consent=True
    ).json()

    assert body["enrichments"][0]["into"] == ["Geolocation 2"]


# --- company names, symbols and prices ------------------------------------------------------


def firms(client: TestClient, clock: Clock | None = None) -> tuple[str, FakeQuotes, FakeSymbols]:
    quotes = FakeQuotes(
        {
            "AAPL": Quote(261.74, OPENING),
            "MSFT": Quote(410.5, OPENING),
            "GOOGL": Quote(170.25, OPENING),
        }
    )
    symbols = FakeSymbols()
    use(runtime(symbols=symbols, quotes=quotes, clock=clock))
    return switch_all_on(client, upload(client, FIRMS)), quotes, symbols


def test_company_names_become_symbols_without_a_silent_pick(client: TestClient) -> None:
    dataset, _, symbols = firms(client)
    assert [(o["connector"], o["column"]) for o in overview(client, dataset)["offers"]] == [
        ("company_ticker", "Firm")
    ]
    # Finding the offer downloaded nothing.
    assert symbols.downloads == 0

    body = look_up(client, dataset, connector="company_ticker", column="Firm", consent=True).json()

    assert body["enrichments"][0]["counts"] == {
        "not found": 1,
        "several matches": 1,
        # "Apple Inc." and "apple inc" are two spellings, each with its own answer.
        "found": 3,
    }
    table = canvas(client, dataset)
    assert column(table, "Ticker") == ["AAPL", None, None, "MSFT", "AAPL"]
    assert table["reasons"]["Ticker"] == [None, "several matches", "not found", None, None]

    issues = client.get(f"/api/datasets/{dataset}/issues").json()["issues"]
    [question] = [issue for issue in issues if issue["detector"] == "connector_match"]
    assert question["tier"] == "ask"
    assert question["title"] == '"Alphabet Inc" matches more than one listed company'
    assert [choice["label"] for choice in question["ask"]["choices"]] == [
        "GOOG",
        "GOOGL",
        "Leave it empty",
    ]
    assert not any(choice["recommended"] for choice in question["ask"]["choices"])


def answer(client: TestClient, dataset: str, label: str) -> None:
    issues = client.get(f"/api/datasets/{dataset}/issues").json()["issues"]
    [question] = [issue for issue in issues if issue["detector"] == "connector_match"]
    [choice] = [c for c in question["ask"]["choices"] if c["label"] == label]
    accepted = client.post(
        f"/api/datasets/{dataset}/issues/{question['id']}/accept", json={"choice_id": choice["id"]}
    )
    assert accepted.status_code == 200


def test_picking_a_match_fills_it_in_and_prices_follow(client: TestClient) -> None:
    dataset, quotes, _ = firms(client)
    look_up(client, dataset, connector="company_ticker", column="Firm", consent=True)

    # The new symbols column is itself something prices can be looked up from.
    offered = overview(client, dataset)["offers"]
    assert [(o["connector"], o["column"]) for o in offered] == [("stock_price", "Ticker")]
    priced = look_up(client, dataset, connector="stock_price", column="Ticker", consent=True).json()
    prices = next(e for e in priced["enrichments"] if e["connector"] == "stock_price")
    assert prices["into"] == ["Price"]
    assert prices["as_of"] == "2026-10-08 10:00 ET"
    assert prices["out_of_date"] is False
    assert sorted(quotes.asked) == ["AAPL", "MSFT"]

    answer(client, dataset, "GOOGL")

    steps = [step["type"] for step in client.get(f"/api/datasets/{dataset}/recipe").json()["steps"]]
    # The pick sits between the symbols and the prices, so the prices read it.
    assert steps[-3:] == ["enrich_column", "resolve_match", "enrich_column"]
    table = canvas(client, dataset)
    assert column(table, "Ticker")[1] == "GOOGL"
    assert column(table, "Price")[1] is None
    assert table["reasons"]["Price"][1] == "not looked up yet"

    again = look_up(client, dataset, step_id=prices["step_id"]).json()
    assert quotes.asked[-1] == "GOOGL"
    assert column(canvas(client, dataset), "Price")[1] == "$170.25"
    assert (
        next(e for e in again["enrichments"] if e["connector"] == "stock_price")["remaining"] == 0
    )


def test_prices_say_when_they_were_true_and_go_out_of_date(client: TestClient) -> None:
    clock = Clock()
    dataset, quotes, _ = firms(client, clock)
    look_up(client, dataset, connector="company_ticker", column="Firm", consent=True)
    priced = look_up(client, dataset, connector="stock_price", column="Ticker", consent=True).json()
    step_id = next(e for e in priced["enrichments"] if e["connector"] == "stock_price")["step_id"]

    table = canvas(client, dataset)
    labels = {c["name"]: c["label"] for c in table["columns"]}
    assert labels["Price"] == "Prices as of 2026-10-08 10:00 ET"
    assert labels["Firm"] is None
    assert column(table, "Price")[0] == "$261.74"
    # The time is something to hover over, not a column, on screen or in the file.
    exported = client.get(f"/api/datasets/{dataset}/export", params={"format": "csv"}).text
    assert exported.splitlines()[0].endswith("Firm,Ticker,Price")

    # The next trading day opens. Nothing is fetched on its own.
    clock.now = NOW + timedelta(days=1)
    asked_before = len(quotes.asked)
    stale = next(
        e for e in overview(client, dataset)["enrichments"] if e["connector"] == "stock_price"
    )
    assert stale["out_of_date"] is True
    assert len(quotes.asked) == asked_before
    assert canvas(client, dataset)["columns"][2]["label"].count("Out of date") == 1

    quotes.answers["AAPL"] = Quote(270.0, OPENING + 86400)
    fresh = look_up(client, dataset, step_id=step_id).json()
    assert (
        next(e for e in fresh["enrichments"] if e["connector"] == "stock_price")["out_of_date"]
        is False
    )
    assert column(canvas(client, dataset), "Price")[0] == "$270.00"


def test_removing_a_lookup_takes_its_question_with_it(client: TestClient) -> None:
    dataset, _, _ = firms(client)
    body = look_up(client, dataset, connector="company_ticker", column="Firm", consent=True).json()

    client.delete(f"/api/datasets/{dataset}/recipe/steps/{body['enrichments'][0]['step_id']}")

    issues = client.get(f"/api/datasets/{dataset}/issues").json()["issues"]
    assert [issue for issue in issues if issue["detector"] == "connector_match"] == []


# --- answers stay reproducible --------------------------------------------------------------


def test_looked_up_columns_never_move_or_add_an_answer(client: TestClient) -> None:
    geocoder = FakeGeocoder({})
    use(runtime(postal=geocoder))
    dataset = upload(client, (SAMPLES_DIR / "store_orders.csv").read_bytes(), "store_orders.csv")
    switch_all_on(client, dataset)
    client.get(f"/api/datasets/{dataset}/issues")
    before = client.get(f"/api/datasets/{dataset}/compare").json()
    offer = next(
        (o for o in overview(client, dataset)["offers"] if o["connector"] == "postal_geocode"),
        None,
    )
    if offer is None:
        pytest.skip("this sample has no postal-code column")
    geocoder.answers = EverywhereTheSame((12.5, 45.5))

    done = look_up(
        client,
        dataset,
        connector="postal_geocode",
        column=offer["column"],
        country=offer["countries"][0]["code"],
        consent=True,
    )
    assert done.status_code == 200
    after = client.get(f"/api/datasets/{dataset}/compare").json()

    assert after["cards"] == before["cards"]


class EverywhereTheSame(dict[str, tuple[float, float]]):
    """A geocoder's answers where every code is in the same place."""

    def __init__(self, position: tuple[float, float]) -> None:
        super().__init__()
        self.position = position

    def __missing__(self, key: str) -> tuple[float, float]:
        return self.position


def test_a_recipe_from_another_file_arrives_with_nothing_looked_up(client: TestClient) -> None:
    dataset, geocoder = shops(client)
    look_up(client, dataset, connector="postal_geocode", column="Zip", country="US", consent=True)
    saved = client.get(f"/api/datasets/{dataset}/export", params={"format": "recipe"}).content
    assert b'"snapshot": null' in saved
    geocoder.asked.clear()

    created = client.post(
        "/api/datasets",
        files={
            "file": ("next.csv", SHOPS.encode(), "text/csv"),
            "recipe": ("steps.json", saved, "application/json"),
        },
    ).json()

    # The step came along; the values did not, and nothing was sent to get them.
    assert geocoder.asked == []
    [waiting] = overview(client, created["id"])["enrichments"]
    assert waiting["looked_up"] is False
    assert overview(client, created["id"])["consented"] == []
    assert column(canvas(client, created["id"]), "Geolocation") == [None] * 5
    # Nothing carries over: the service is off for the new file, and once it is
    # switched on the user is still asked before anything is sent.
    retry = look_up(client, created["id"], step_id=waiting["step_id"])
    assert retry.json()["code"] == "connector_inactive"
    switch(client, created["id"], "postal_geocode")
    retry = look_up(client, created["id"], step_id=waiting["step_id"])
    assert retry.json()["code"] == "consent_required"
    assert geocoder.asked == []


# --- a model filling in a column ------------------------------------------------------------

INDUSTRY = {
    "name": "Industry",
    "based_on": "Firm",
    "instruction": "What line of business the company is in.",
    "kind": "label",
    "choices": ["Technology", "Tools", "Other"],
}
KNOWN = {"Apple Inc.": "Technology", "apple inc": "technology", "Microsoft Corp": "Technology"}


def filling(client: TestClient, **more: Any) -> tuple[str, FakeModel]:
    model = FakeModel(lambda row: KNOWN.get(str(row["value"]), "Hardware"), **more)
    use(runtime(model=model))
    dataset = upload(client, FIRMS)
    assert switch(client, dataset, "ai_fill").status_code == 200
    return dataset, model


def preview(client: TestClient, dataset: str, consent: bool = True, **fill: Any) -> Any:
    return client.post(
        f"/api/datasets/{dataset}/connectors/ai-fill/preview",
        json={"fill": {**INDUSTRY, **fill}, "consent": consent},
    )


def test_ai_fill_is_only_there_when_a_model_service_is(client: TestClient) -> None:
    use(runtime())
    dataset = upload(client, FIRMS)

    listed = {c["id"]: c for c in overview(client, dataset)["connectors"]}

    assert listed["ai_fill"]["enabled"] is False
    assert switch(client, dataset, "ai_fill").json()["code"] == "connector_off"
    assert preview(client, dataset).json()["code"] == "connector_off"


def test_nothing_is_sent_to_a_model_until_it_is_switched_on_and_agreed_to(
    client: TestClient,
) -> None:
    model = FakeModel()
    use(runtime(model=model))
    dataset = upload(client, FIRMS)

    assert preview(client, dataset).json()["code"] == "connector_inactive"
    switch(client, dataset, "ai_fill")
    assert preview(client, dataset, consent=False).json()["code"] == "consent_required"
    assert model.requests == []


def test_a_preview_shows_a_few_answers_and_adds_nothing(client: TestClient) -> None:
    dataset, _ = filling(client)
    before = overview(client, dataset)["recipe"]["steps"]

    shown = preview(client, dataset)

    assert shown.status_code == 200
    body = shown.json()
    assert body["total_values"] == 5
    answers = {row["value"]: (row["answer"], row["reason"]) for row in body["rows"]}
    assert answers["Apple Inc."] == ("Technology", None)
    # "Hardware" isn't one of this column's labels, so it is never shown as an answer.
    assert answers["Acme Tools Ltd"] == (None, "not sure")
    assert overview(client, dataset)["recipe"]["steps"] == before
    assert "Industry" not in [c["name"] for c in canvas(client, dataset)["columns"]]


def test_filling_adds_a_marked_column_and_reuses_what_the_preview_learned(
    client: TestClient,
) -> None:
    dataset, model = filling(client)
    preview(client, dataset)
    asked = len(model.requests)

    done = look_up(client, dataset, connector="ai_fill", fill=INDUSTRY)

    assert done.status_code == 200
    # Every value was already answered for the preview.
    assert len(model.requests) == asked
    [filled] = done.json()["enrichments"]
    assert (filled["connector"], filled["column"], filled["into"]) == (
        "ai_fill",
        "Firm",
        ["Industry"],
    )
    assert filled["counts"] == {"not sure": 2, "found": 3}
    table = canvas(client, dataset)
    assert column(table, "Industry") == ["Technology", None, None, "Technology", "Technology"]
    assert table["reasons"]["Industry"] == [None, "not sure", "not sure", None, None]
    labels = {c["name"]: c["label"] for c in table["columns"]}
    assert "not verified" in labels["Industry"]
    step = done.json()["recipe"]["steps"][-1]
    assert step["description"] == 'Fill "Industry" with AI, from "Firm" (unverified)'


def test_an_ai_filled_column_can_be_undone_and_never_moves_an_answer(client: TestClient) -> None:
    dataset, _ = filling(client)
    client.get(f"/api/datasets/{dataset}/issues")
    before = client.get(f"/api/datasets/{dataset}/compare").json()

    look_up(client, dataset, connector="ai_fill", fill=INDUSTRY, consent=True)
    assert client.get(f"/api/datasets/{dataset}/compare").json()["cards"] == before["cards"]

    client.post(f"/api/datasets/{dataset}/recipe/undo")
    assert "Industry" not in [c["name"] for c in canvas(client, dataset)["columns"]]


def test_a_saved_recipe_keeps_what_the_column_means_but_not_the_answers(
    client: TestClient,
) -> None:
    dataset, _ = filling(client)
    look_up(client, dataset, connector="ai_fill", fill=INDUSTRY, consent=True)

    saved = client.get(f"/api/datasets/{dataset}/export", params={"format": "recipe"}).json()

    step = saved["recipe"]["steps"][-1]
    assert step["instruction"] == INDUSTRY["instruction"]
    assert step["choices"] == INDUSTRY["choices"]
    assert step["snapshot"] is None


def test_what_sits_beside_a_value_is_sent_to_help_tell_it_apart(client: TestClient) -> None:
    model = FakeModel(lambda row: "Other")
    use(runtime(model=model))
    dataset = upload(
        client, "Firm,City,Notes\nAcme Ltd,Leeds,x\nAcme Ltd,Leeds,y\nBirch Inc,Lyon,z\n"
    )
    switch(client, dataset, "ai_fill")

    preview(client, dataset, context=["City"])

    rows = model.requests[0]["rows"]
    assert rows[0] == {"id": 1, "value": "Acme Ltd", "context": {"City": "Leeds"}}
    # Only the column it is based on and the one named beside it. Nothing else leaves.
    assert "Notes" not in json.dumps(model.requests)


@pytest.mark.parametrize(
    "fill",
    [
        {"based_on": "Nope"},
        {"kind": "label", "choices": []},
        {"kind": "text"},  # text with a label list
        {"context": ["Nope"]},
        {"instruction": ""},
    ],
    ids=["no-such-column", "label-without-labels", "text-with-labels", "bad-context",
         "no-meaning"],
)  # fmt: skip
def test_a_column_that_cant_be_filled_this_way_is_refused_before_anything_is_sent(
    client: TestClient, fill: dict[str, Any]
) -> None:
    dataset, model = filling(client)

    refused = look_up(client, dataset, connector="ai_fill", fill={**INDUSTRY, **fill}, consent=True)

    assert refused.status_code == 422
    assert model.requests == []


def test_a_model_that_cant_be_reached_leaves_an_empty_column_that_says_why(
    client: TestClient,
) -> None:
    dataset, _ = filling(client, reply=ProviderError("down"))

    body = look_up(client, dataset, connector="ai_fill", fill=INDUSTRY, consent=True).json()

    [filled] = body["enrichments"]
    assert filled["counts"] == {"service unavailable": 5}
    assert filled["remaining"] == 5
    assert column(canvas(client, dataset), "Industry") == [None] * 5


# --- no second copy of what a connector already added ---------------------------------------


def test_once_looked_up_the_same_thing_isnt_offered_or_added_again(client: TestClient) -> None:
    dataset, _ = shops(client)
    ideas = f"/api/datasets/{dataset}/canvas/suggestions"
    assert "Map position" in [s["name"] for s in client.get(ideas).json()["suggestions"]]
    look_up(client, dataset, connector="postal_geocode", column="Zip", country="US", consent=True)
    before = canvas(client, dataset)

    # The idea picker no longer offers it...
    assert "Map position" not in [s["name"] for s in client.get(ideas).json()["suggestions"]]
    # ...and asking for it by any of its names adds nothing and says where it already is.
    for name in ("Map position", "Latitude and longitude", "geolocation 2"):
        refused = client.post(f"/api/datasets/{dataset}/canvas/columns", json={"name": name})
        assert refused.status_code == 409
        assert refused.json()["code"] == "already_looked_up"
        assert refused.json()["message"] == (
            'Map positions are already in "Geolocation", so nothing was added.'
        )
    assert canvas(client, dataset)["columns"] == before["columns"]
    # Something else is still welcome.
    added = client.post(f"/api/datasets/{dataset}/canvas/columns", json={"name": "Opening hours"})
    assert added.status_code == 200


def test_removing_the_lookup_makes_the_idea_available_again(client: TestClient) -> None:
    dataset, _ = shops(client)
    body = look_up(
        client, dataset, connector="postal_geocode", column="Zip", country="US", consent=True
    ).json()
    client.delete(f"/api/datasets/{dataset}/recipe/steps/{body['enrichments'][0]['step_id']}")

    offered = client.get(f"/api/datasets/{dataset}/canvas/suggestions").json()["suggestions"]
    added = client.post(f"/api/datasets/{dataset}/canvas/columns", json={"name": "Map position"})

    assert "Map position" in [s["name"] for s in offered]
    assert added.status_code == 200
