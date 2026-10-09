"""Normalising, matching and freshness: the parts with no I/O at all."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.connectors import freshness
from app.connectors.cache import LookupCache
from app.connectors.matching import build_index, decode_candidates, match_company
from app.connectors.models import Company, LookupResult, Status
from app.connectors.normalize import company_key, postal_query, ticker_query
from tests.connector_fakes import COMPANIES

# --- what gets asked ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("country", "value", "query"),
    [
        ("US", "90210", "90210"),
        ("US", " 02134 ", "02134"),
        ("US", "90210-1234", "90210"),
        ("us", "90210", "90210"),
        ("CA", "k1a 0b1", "K1A"),
        ("CA", "K1A0B1", "K1A"),
        ("GB", "sw1a 1aa", "SW1A"),
        ("GB", "M1 1AE", "M1"),
        ("DE", "10115", "10115"),
        ("IN", "110001", "110001"),
    ],
)
def test_a_postal_code_becomes_what_the_service_indexes(
    country: str, value: str, query: str
) -> None:
    assert postal_query(country, value) == query


@pytest.mark.parametrize(
    ("country", "value"),
    [
        ("US", "9021"),
        ("US", "90210-12"),
        ("US", "K1A 0B1"),
        ("US", "90210; DROP"),
        ("US", "../90210"),
        ("CA", "90210"),
        ("ZZ", "90210"),
        ("US", ""),
    ],
)
def test_anything_else_is_never_sent(country: str, value: str) -> None:
    assert postal_query(country, value) is None


@pytest.mark.parametrize(("value", "query"), [("aapl", "AAPL"), (" BRK.B ", "BRK.B"), ("F", "F")])
def test_a_stock_symbol_is_tidied(value: str, query: str) -> None:
    assert ticker_query(value) == query


@pytest.mark.parametrize("value", ["", "TOOLONG", "AA PL", "AAPL?token=x", "123", "A/B"])
def test_what_isnt_a_stock_symbol_is_never_sent(value: str) -> None:
    assert ticker_query(value) is None


@pytest.mark.parametrize(
    "name",
    ["Apple Inc.", "APPLE INC", "apple, incorporated", " Apple  Inc ", "The Apple Company"],
)
def test_spellings_of_one_company_share_a_key(name: str) -> None:
    assert company_key(name) == "apple"


def test_company_keys_keep_what_tells_companies_apart() -> None:
    assert company_key("AT&T Inc.") == "at and t"
    assert company_key("Procter & Gamble Co") == "procter and gamble"
    assert company_key("COCA COLA CO /DE/") == "coca cola"
    assert company_key("Inc") == "inc"  # nothing left to strip it down to
    assert company_key("Berkshire Hathaway") != company_key("Berkshire Hills")


# --- company name to symbol -----------------------------------------------------------------


def test_one_match_is_used() -> None:
    found = match_company("microsoft corporation", build_index(COMPANIES))

    assert (found.status, found.value1, found.value2) == (Status.FOUND, "MSFT", "MICROSOFT CORP")


def test_two_share_classes_are_never_picked_between() -> None:
    found = match_company("Alphabet", build_index(COMPANIES))

    assert found.status is Status.AMBIGUOUS
    assert found.value1 is None
    assert [c.ticker for c in decode_candidates(found.value2)] == ["GOOG", "GOOGL"]


def test_no_match_is_not_found_rather_than_the_nearest_name() -> None:
    assert match_company("Appel", build_index(COMPANIES)).status is Status.NOT_FOUND
    assert match_company("Apple Hospitality", build_index(COMPANIES)).status is Status.NOT_FOUND


def test_a_company_listed_twice_under_one_symbol_is_one_match() -> None:
    index = build_index([Company("WMT", "Walmart Inc."), Company("WMT", "WALMART INC")])

    assert match_company("Walmart", index).status is Status.FOUND


def test_candidates_that_cant_be_read_are_no_candidates() -> None:
    assert decode_candidates("not json") == []
    assert decode_candidates(None) == []


# --- how long an answer stays good ----------------------------------------------------------


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "opened"),
    [
        ("2026-10-08T15:00", "2026-10-08T13:30"),  # Thursday 11:00 New York: today's open
        ("2026-10-08T13:29", "2026-10-07T13:30"),  # one minute before the open: yesterday's
        ("2026-10-10T18:00", "2026-10-09T13:30"),  # Saturday: Friday's
        ("2026-10-12T12:00", "2026-10-09T13:30"),  # Monday before the open: Friday's
        ("2026-12-01T15:00", "2026-12-01T14:30"),  # winter time: 09:30 is 14:30 UTC
    ],
)
def test_the_latest_market_open(now: str, opened: str) -> None:
    assert freshness.last_market_open(utc(now)).astimezone(UTC) == utc(opened)


def test_a_price_is_good_until_the_next_trading_day_opens() -> None:
    fetched = "2026-10-08T14:00:00+00:00"

    assert freshness.price_is_fresh(fetched, utc("2026-10-08T23:00"))
    assert freshness.price_is_fresh(fetched, utc("2026-10-09T13:00"))
    assert not freshness.price_is_fresh(fetched, utc("2026-10-09T13:31"))
    assert not freshness.price_is_fresh(None, utc("2026-10-08T23:00"))
    assert not freshness.price_is_fresh("garbage", utc("2026-10-08T23:00"))


def test_when_a_price_was_true_is_written_in_market_time() -> None:
    assert freshness.as_of(int(utc("2026-10-08T13:31").timestamp())) == "2026-10-08 09:31 ET"


# --- the cache ------------------------------------------------------------------------------


def test_answers_survive_a_restart(tmp_path: Path) -> None:
    path = str(tmp_path / "nested" / "cache.sqlite")
    first = LookupCache(path)
    first.put("p", "90210", LookupResult(Status.FOUND, "34.09", "-118.4", "2026-10-08T15:00:00"))
    first.put_document("list", "[1]", "2026-10-08T15:00:00")
    first.close()

    again = LookupCache(path)

    assert again.get("p", "90210") == LookupResult(
        Status.FOUND, "34.09", "-118.4", "2026-10-08T15:00:00"
    )
    assert again.get_document("list") == ("[1]", "2026-10-08T15:00:00")
    assert again.get("p", "nope") is None
    assert again.get("other", "90210") is None


def test_a_later_answer_replaces_an_earlier_one() -> None:
    cache = LookupCache()
    cache.put("p", "k", LookupResult(Status.NOT_FOUND, fetched_at="a"))
    cache.put("p", "k", LookupResult(Status.FOUND, "1", "2", "b"))

    assert cache.get("p", "k") == LookupResult(Status.FOUND, "1", "2", "b")


def test_a_place_that_cant_be_written_to_costs_only_the_persistence(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")

    cache = LookupCache(str(blocker / "cache.sqlite"))
    cache.put("p", "k", LookupResult(Status.FOUND, "1", "2", "b"))

    assert cache.get("p", "k") is not None


def test_the_cache_holds_values_and_answers_and_nothing_about_a_file(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "cache.sqlite"
    LookupCache(str(path)).close()

    columns = {
        row[1]
        for table in ("lookups", "documents")
        for row in sqlite3.connect(path).execute(f"PRAGMA table_info({table})")
    }
    assert columns == {
        "provider",
        "key",
        "status",
        "value1",
        "value2",
        "fetched_at",
        "name",
        "body",
    }
