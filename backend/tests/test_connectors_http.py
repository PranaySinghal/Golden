"""Calling out: retries, pauses, and turning every failure into a typed reason."""

import json

import pytest

from app.connectors.http import MAX_WAIT_SECONDS, RETRIES, Reply, get_json
from app.connectors.models import (
    NotFoundError,
    RateLimitedError,
    TimedOutError,
    UnavailableError,
)
from app.connectors.providers.postal import Zippopotam
from app.connectors.providers.quotes import Finnhub
from app.connectors.providers.symbols import Sec
from tests.connector_fakes import ScriptedSend

OK = Reply(200, json.dumps({"fine": True}))


def ask(send: ScriptedSend, pauses: list[float] | None = None) -> object:
    waited = pauses if pauses is not None else []
    return get_json("https://example.test/x", timeout_ms=1000, send=send, sleep=waited.append)


def test_a_good_answer_comes_back_parsed_after_one_call() -> None:
    send = ScriptedSend(OK)

    assert ask(send) == {"fine": True}
    assert len(send.requests) == 1


def test_a_missing_page_is_not_found_and_not_asked_again() -> None:
    send = ScriptedSend(Reply(404, "{}"))

    with pytest.raises(NotFoundError):
        ask(send)
    assert len(send.requests) == 1


def test_a_service_that_stumbles_is_tried_again_with_a_growing_pause() -> None:
    send = ScriptedSend(Reply(503, ""), TimedOutError("slow"), OK)
    pauses: list[float] = []

    assert ask(send, pauses) == {"fine": True}
    assert len(pauses) == RETRIES
    assert pauses[1] > pauses[0]


def test_a_service_that_never_answers_in_time_times_out() -> None:
    send = ScriptedSend(*[TimedOutError("slow")] * (RETRIES + 1))

    with pytest.raises(TimedOutError):
        ask(send)
    assert len(send.requests) == RETRIES + 1


def test_being_told_to_slow_down_is_rate_limited_after_the_retries() -> None:
    send = ScriptedSend(*[Reply(429, "", {"retry-after": "2"})] * (RETRIES + 1))
    pauses: list[float] = []

    with pytest.raises(RateLimitedError):
        ask(send, pauses)
    assert all(pause >= 2 for pause in pauses)


def test_a_long_requested_wait_is_capped() -> None:
    send = ScriptedSend(Reply(429, "", {"retry-after": "3600"}), OK)
    pauses: list[float] = []

    ask(send, pauses)

    assert pauses == [MAX_WAIT_SECONDS]


def test_a_wait_given_as_a_date_falls_back_to_our_own_pause() -> None:
    send = ScriptedSend(Reply(429, "", {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}), OK)
    pauses: list[float] = []

    ask(send, pauses)

    assert 0 < pauses[0] < MAX_WAIT_SECONDS


@pytest.mark.parametrize("body", ["<html>busy</html>", "", "{not json"])
def test_an_answer_that_isnt_json_is_unavailable_and_not_retried(body: str) -> None:
    send = ScriptedSend(Reply(200, body))

    with pytest.raises(UnavailableError):
        ask(send)
    assert len(send.requests) == 1


def test_a_refused_request_is_unavailable_and_not_retried() -> None:
    send = ScriptedSend(Reply(401, "{}"))

    with pytest.raises(UnavailableError):
        ask(send)
    assert len(send.requests) == 1


def test_a_service_that_stays_down_is_unavailable() -> None:
    send = ScriptedSend(*[Reply(500, "")] * (RETRIES + 1))

    with pytest.raises(UnavailableError):
        ask(send)


# --- postal codes ---------------------------------------------------------------------------


def postal(body: object, status: int = 200) -> tuple[Zippopotam, ScriptedSend]:
    send = ScriptedSend(Reply(status, json.dumps(body)))
    return Zippopotam(1000, send=send, sleep=lambda _: None), send


def test_a_postal_code_gives_a_position() -> None:
    service, send = postal({"places": [{"latitude": "34.0901", "longitude": "-118.4065"}]})

    assert service.locate("US", "90210") == (34.0901, -118.4065)
    assert send.requests[0][0] == "https://api.zippopotam.us/us/90210"


def test_only_the_code_and_country_are_in_the_address() -> None:
    service, send = postal({"places": [{"latitude": "1", "longitude": "2"}]})

    service.locate("GB", "SW1A/../x?y")

    assert send.requests[0][0] == "https://api.zippopotam.us/gb/SW1A%2F..%2Fx%3Fy"


@pytest.mark.parametrize("body", [{}, {"places": []}])
def test_an_unknown_postal_code_is_not_found(body: object) -> None:
    service, _ = postal(body)

    with pytest.raises(NotFoundError):
        service.locate("US", "00000")


def test_a_404_from_the_postal_service_is_not_found() -> None:
    service, _ = postal({}, status=404)

    with pytest.raises(NotFoundError):
        service.locate("US", "00000")


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"places": "nope"},
        {"places": [{}]},
        {"places": [{"latitude": "north", "longitude": "2"}]},
        {"places": [None]},
    ],
)
def test_a_postal_answer_of_the_wrong_shape_is_never_guessed_at(body: object) -> None:
    service, _ = postal(body)

    with pytest.raises(UnavailableError):
        service.locate("US", "90210")


def test_a_position_that_cant_be_real_is_not_found_rather_than_shown() -> None:
    # What the live service returns for some German codes: another field where
    # the latitude should be.
    service, _ = postal({"places": [{"latitude": "05315", "longitude": "50.9384"}]})

    with pytest.raises(NotFoundError):
        service.locate("DE", "50667")


# --- the companies list ---------------------------------------------------------------------


def test_the_companies_list_is_read_and_we_say_who_is_asking() -> None:
    body = {
        "0": {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    }
    send = ScriptedSend(Reply(200, json.dumps(body)))

    found = Sec("Tidy Lab test@example.com", 1000, send=send).companies()

    assert [(company.ticker, company.title) for company in found] == [
        ("AAPL", "Apple Inc."),
        ("MSFT", "MICROSOFT CORP"),
    ]
    assert send.requests[0][1]["User-Agent"] == "Tidy Lab test@example.com"


@pytest.mark.parametrize("body", [{}, {"0": "nope"}, "text", {"0": {"ticker": 5, "title": None}}])
def test_a_companies_list_of_the_wrong_shape_is_unavailable(body: object) -> None:
    send = ScriptedSend(Reply(200, json.dumps(body)))

    with pytest.raises(UnavailableError):
        Sec("x", 1000, send=send).companies()


# --- prices ---------------------------------------------------------------------------------


def prices(body: object) -> tuple[Finnhub, ScriptedSend]:
    send = ScriptedSend(Reply(200, json.dumps(body)))
    return Finnhub("secret-key", 1000, send=send, sleep=lambda _: None), send


def test_a_symbol_gives_a_price_and_when_it_was_true() -> None:
    service, send = prices({"c": 261.74, "pc": 259.45, "t": 1791471600})

    found = service.quote("AAPL")

    assert (found.price, found.at) == (261.74, 1791471600)
    url, headers = send.requests[0]
    assert url == "https://finnhub.io/api/v1/quote?symbol=AAPL"
    assert headers["X-Finnhub-Token"] == "secret-key"
    assert "secret-key" not in url


def test_an_unknown_symbol_comes_back_as_zeros_which_means_not_found() -> None:
    service, _ = prices({"c": 0, "d": None, "t": 0})

    with pytest.raises(NotFoundError):
        service.quote("ZZZZZ")


@pytest.mark.parametrize(
    "body", [[], {}, {"c": "261", "t": 1}, {"c": 261.0}, {"c": True, "t": 1}, {"c": 1, "t": "x"}]
)
def test_a_price_answer_of_the_wrong_shape_is_unavailable(body: object) -> None:
    service, _ = prices(body)

    with pytest.raises(UnavailableError):
        service.quote("AAPL")
