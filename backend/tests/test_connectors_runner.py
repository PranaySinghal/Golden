"""A lookup run: limits, the cache, and a reason for every value without an answer."""

from datetime import timedelta

from app.connectors.cache import LookupCache
from app.connectors.models import (
    LookupResult,
    Quote,
    RateLimitedError,
    Status,
    TimedOutError,
    UnavailableError,
)
from app.connectors.models import (
    NotFoundError as Missing,
)
from app.connectors.runner import look_up
from tests.connector_fakes import NOW, Clock, FakeGeocoder, FakeQuotes, FakeSymbols, runtime

LA = (34.0901, -118.4065)
NYC = (40.7128, -74.006)
STAMP = "2026-10-08T15:00:00+00:00"


def statuses(results: dict[str, object]) -> dict[str, Status]:
    return {key: result.status for key, result in results.items()}  # type: ignore[attr-defined]


def test_each_value_gets_an_answer_or_a_reason() -> None:
    geocoder = FakeGeocoder(
        {
            "90210": LA,
            "00000": Missing(),
            "11111": TimedOutError(),
            "22222": RateLimitedError(),
            "33333": UnavailableError(),
        }
    )

    found = look_up(
        "postal_geocode",
        ["90210", "00000", "11111", "22222", "33333", "not a code"],
        "US",
        runtime(postal=geocoder),
    )

    assert statuses(found) == {
        "90210": Status.FOUND,
        "00000": Status.NOT_FOUND,
        "11111": Status.TIMED_OUT,
        "22222": Status.RATE_LIMITED,
        "33333": Status.UNAVAILABLE,
        "not a code": Status.NOT_FOUND,
    }
    assert (found["90210"].value1, found["90210"].value2) == ("34.0901, -118.4065", None)
    # A failure never carries a value, so a cell can't be filled with a guess.
    assert all(
        result.value1 is None for key, result in found.items() if result.status != Status.FOUND
    )
    # A value of the wrong shape was never sent.
    assert ("US", "not a code") not in geocoder.asked


def test_values_that_mean_the_same_code_are_asked_about_once() -> None:
    geocoder = FakeGeocoder({"90210": LA})

    found = look_up("postal_geocode", ["90210", "90210-1234"], "US", runtime(postal=geocoder))

    assert geocoder.asked == [("US", "90210")]
    assert found["90210-1234"].value1 == "34.0901, -118.4065"


def test_a_second_run_asks_nothing_it_already_knows() -> None:
    cache = LookupCache()
    first = FakeGeocoder({"90210": LA, "00000": Missing()})
    look_up("postal_geocode", ["90210", "00000"], "US", runtime(postal=first, cache=cache))
    second = FakeGeocoder({})

    found = look_up("postal_geocode", ["90210", "00000"], "US", runtime(postal=second, cache=cache))

    assert second.asked == []
    assert statuses(found) == {"90210": Status.FOUND, "00000": Status.NOT_FOUND}


def test_a_failure_is_not_remembered_so_the_next_run_tries_again() -> None:
    cache = LookupCache()
    look_up(
        "postal_geocode",
        ["90210"],
        "US",
        runtime(postal=FakeGeocoder({"90210": TimedOutError()}), cache=cache),
    )
    second = FakeGeocoder({"90210": LA})

    found = look_up("postal_geocode", ["90210"], "US", runtime(postal=second, cache=cache))

    assert second.asked == [("US", "90210")]
    assert found["90210"].status is Status.FOUND


def test_the_same_code_in_another_country_is_another_question() -> None:
    cache = LookupCache()
    look_up(
        "postal_geocode", ["10115"], "DE", runtime(postal=FakeGeocoder({"10115": NYC}), cache=cache)
    )
    french = FakeGeocoder({"10115": Missing()})

    found = look_up("postal_geocode", ["10115"], "FR", runtime(postal=french, cache=cache))

    assert french.asked == [("FR", "10115")]
    assert found["10115"].status is Status.NOT_FOUND


def test_past_the_limit_the_rest_wait_for_the_next_run() -> None:
    codes = [f"{number:05d}" for number in range(10000, 10005)]
    geocoder = FakeGeocoder(dict.fromkeys(codes, LA))
    cache = LookupCache()

    found = look_up(
        "postal_geocode", codes, "US", runtime(postal=geocoder, cache=cache, max_values=2)
    )

    assert len(geocoder.asked) == 2
    assert list(statuses(found).values()) == [Status.FOUND] * 2 + [Status.PENDING] * 3

    # The next run picks up where this one stopped: cached answers don't count.
    again = look_up(
        "postal_geocode", codes, "US", runtime(postal=geocoder, cache=cache, max_values=2)
    )
    assert len(geocoder.asked) == 4
    assert list(statuses(again).values()) == [Status.FOUND] * 4 + [Status.PENDING]


def test_past_the_rate_limit_a_value_says_so_and_is_not_sent() -> None:
    geocoder = FakeGeocoder({"90210": LA, "10001": NYC})

    found = look_up(
        "postal_geocode", ["90210", "10001"], "US", runtime(postal=geocoder, calls_per_minute=1)
    )

    assert geocoder.asked == [("US", "90210")]
    assert statuses(found) == {"90210": Status.FOUND, "10001": Status.RATE_LIMITED}


def test_a_run_that_runs_out_of_time_leaves_the_rest_for_later() -> None:
    ticks = iter([0.0, 1.0, 99.0, 99.0])
    geocoder = FakeGeocoder({"90210": LA, "10001": NYC})

    found = look_up(
        "postal_geocode",
        ["90210", "10001"],
        "US",
        runtime(postal=geocoder, monotonic=lambda: next(ticks)),
    )

    assert statuses(found) == {"90210": Status.FOUND, "10001": Status.PENDING}


# --- prices ---------------------------------------------------------------------------------


def test_a_price_comes_with_when_it_was_true_and_when_it_was_fetched() -> None:
    at = int(NOW.timestamp()) - 60
    found = look_up(
        "stock_price", ["aapl"], None, runtime(quotes=FakeQuotes({"AAPL": Quote(261.74, at)}))
    )

    assert found["aapl"].value1 == "$261.74"
    assert found["aapl"].value2 == "2026-10-08 10:59 ET"
    assert found["aapl"].fetched_at == "2026-10-08T15:00:00+00:00"


def test_a_price_is_fetched_once_per_trading_day() -> None:
    cache = LookupCache()
    clock = Clock()
    quotes = FakeQuotes({"AAPL": Quote(261.74, 1791471600)})
    look_up("stock_price", ["AAPL"], None, runtime(quotes=quotes, cache=cache, clock=clock))

    clock.now = NOW + timedelta(hours=5)
    look_up("stock_price", ["AAPL"], None, runtime(quotes=quotes, cache=cache, clock=clock))
    assert quotes.asked == ["AAPL"]

    clock.now = NOW + timedelta(days=1)
    quotes.answers["AAPL"] = Quote(265.0, 1791558000)
    found = look_up("stock_price", ["AAPL"], None, runtime(quotes=quotes, cache=cache, clock=clock))
    assert quotes.asked == ["AAPL", "AAPL"]
    assert found["AAPL"].value1 == "$265.00"


def test_an_unknown_symbol_is_not_found() -> None:
    found = look_up(
        "stock_price", ["ZZZZ", "12"], None, runtime(quotes=FakeQuotes({"ZZZZ": Missing()}))
    )

    assert statuses(found) == {"ZZZZ": Status.NOT_FOUND, "12": Status.NOT_FOUND}


# --- company names --------------------------------------------------------------------------


def test_company_names_are_matched_here_and_the_list_is_downloaded_once() -> None:
    cache = LookupCache()
    symbols = FakeSymbols()

    found = look_up(
        "company_ticker",
        ["apple inc", "alphabet", "acme tools"],
        None,
        runtime(symbols=symbols, cache=cache),
    )
    look_up("company_ticker", ["walmart"], None, runtime(symbols=symbols, cache=cache))

    assert statuses(found) == {
        "apple inc": Status.FOUND,
        "alphabet": Status.AMBIGUOUS,
        "acme tools": Status.NOT_FOUND,
    }
    assert found["apple inc"].value1 == "AAPL"
    assert symbols.downloads == 1


def test_the_list_is_downloaded_again_after_a_day() -> None:
    cache = LookupCache()
    clock = Clock()
    symbols = FakeSymbols()
    look_up("company_ticker", ["apple"], None, runtime(symbols=symbols, cache=cache, clock=clock))

    clock.now = NOW + timedelta(days=2)
    look_up("company_ticker", ["apple"], None, runtime(symbols=symbols, cache=cache, clock=clock))

    assert symbols.downloads == 2


def test_without_the_list_every_name_says_why() -> None:
    found = look_up(
        "company_ticker",
        ["apple", "walmart"],
        None,
        runtime(symbols=FakeSymbols(TimedOutError())),
    )

    assert set(statuses(found).values()) == {Status.TIMED_OUT}


def test_a_price_is_written_as_dollars_and_cents() -> None:
    quotes = FakeQuotes({"BRK.A": Quote(742350.5, 1791471600), "F": Quote(9.1, 1791471600)})

    found = look_up("stock_price", ["BRK.A", "F"], None, runtime(quotes=quotes))

    assert (found["BRK.A"].value1, found["F"].value1) == ("$742,350.50", "$9.10")


def test_an_answer_cached_in_an_older_shape_is_asked_for_again() -> None:
    cache = LookupCache()
    # What this value's answer looked like before a position became one cell.
    cache.put("fake_postal", "US:90210", LookupResult(Status.FOUND, "34.0901", "-118.4065", STAMP))
    geocoder = FakeGeocoder({"90210": LA})

    found = look_up("postal_geocode", ["90210"], "US", runtime(postal=geocoder, cache=cache))

    assert geocoder.asked == [("US", "90210")]
    assert found["90210"].value1 == "34.0901, -118.4065"
