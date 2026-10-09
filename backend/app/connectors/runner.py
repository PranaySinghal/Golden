"""One lookup run: a list of values in, one answer or one reason per value out.

No HTTP here and no database: the providers, the cache, the rate limits and the
clock are all handed in, so every path can be driven by a test.

The order of checks for each value is what keeps a run cheap and honest:
a value of the wrong shape is "not found" without a call; an answer still good
in the cache is reused; past this run's limit or its time, the value waits for
the next run; past the provider's rate limit it says so. Only then is the
service asked, and only a definite answer (found, or not found) is remembered.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.ai.limiter import CallBudget
from app.ai.provider import NoProvider, Provider
from app.connectors import freshness
from app.connectors.cache import LookupCache
from app.connectors.matching import build_index, match_company
from app.connectors.models import Company, ConnectorError, LookupResult, Status
from app.connectors.normalize import postal_query, ticker_query
from app.connectors.providers.postal import PostalGeocoder
from app.connectors.providers.quotes import QuoteProvider
from app.connectors.providers.symbols import SymbolLookup, parse_companies

COMPANY_LIST = "sec_company_tickers"
# Bumped whenever what an answer is stored as changes, so an answer cached in
# the old shape is asked for again instead of being shown wrongly.
ANSWER_FORMAT = "v2"


@dataclass
class Runtime:
    """Everything a run needs from outside. One per server; tests build their own."""

    postal: PostalGeocoder
    symbols: SymbolLookup
    quotes: QuoteProvider
    cache: LookupCache
    budgets: dict[str, CallBudget]
    max_values: int = 100
    run_seconds: float = 25.0
    # The model service that fills in AI columns, if one is set up ("none" otherwise).
    model: Provider = field(default_factory=NoProvider)
    # Which model answers. Part of the cache key: another model may answer differently.
    model_id: str = ""
    fill_max_values: int = 400
    fill_timeout_ms: int = 20000
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    monotonic: Callable[[], float] = time.monotonic


def cached_companies(runtime: Runtime) -> list[Company] | None:
    """The companies list if we already hold a current copy. Never calls out."""
    held = runtime.cache.get_document(COMPANY_LIST)
    if held is None or not freshness.within_days(
        held[1], runtime.now(), freshness.COMPANY_LIST_DAYS
    ):
        return None
    try:
        return parse_companies(json.loads(held[0]))
    except (ValueError, ConnectorError):
        return None


def load_companies(runtime: Runtime) -> list[Company]:
    """The companies list, downloaded at most once a day. Raises ConnectorError."""
    held = cached_companies(runtime)
    if held is not None:
        return held
    companies = runtime.symbols.companies()
    body = json.dumps([{"ticker": c.ticker, "title": c.title} for c in companies])
    runtime.cache.put_document(COMPANY_LIST, body, freshness.stamp(runtime.now()))
    return companies


def look_up(
    connector: str, keys: list[str], country: str | None, runtime: Runtime
) -> dict[str, LookupResult]:
    """An answer or a reason for every key. `keys` come most common first."""
    if connector == "company_ticker":
        return _match_companies(keys, runtime)
    if connector == "postal_geocode":
        assert country is not None
        return _call_each(
            keys,
            runtime,
            provider=runtime.postal.name,
            to_query=lambda key: postal_query(country, key),
            cache_key=lambda query: f"{country.upper()}:{query}",
            fetch=lambda query: _position(runtime, country, query),
            fresh=lambda held, now: freshness.within_days(
                held.fetched_at, now, freshness.POSTAL_DAYS
            ),
        )
    return _call_each(
        keys,
        runtime,
        provider=runtime.quotes.name,
        to_query=ticker_query,
        cache_key=lambda query: query,
        fetch=lambda query: _price(runtime, query),
        fresh=lambda held, now: freshness.price_is_fresh(held.fetched_at, now),
    )


def _position(runtime: Runtime, country: str, query: str) -> tuple[str, str | None]:
    latitude, longitude = runtime.postal.locate(country, query)
    # One cell: "34.0901, -118.4065", the way a map search takes it.
    return f"{latitude!r}, {longitude!r}", None


def _price(runtime: Runtime, symbol: str) -> tuple[str, str | None]:
    quote = runtime.quotes.quote(symbol)
    # The service gives no currency; symbols from the companies list are US
    # listings, so prices are shown in dollars. When the price was true rides
    # along as the second value: shown beside the column, not in one.
    return f"${quote.price:,.2f}", freshness.as_of(quote.at)


def _match_companies(keys: list[str], runtime: Runtime) -> dict[str, LookupResult]:
    try:
        index = build_index(load_companies(runtime))
    except ConnectorError as error:
        return {key: LookupResult(error.status) for key in keys}
    fetched_at = freshness.stamp(runtime.now())
    results = {}
    for key in keys:
        matched = match_company(key, index)
        results[key] = LookupResult(
            matched.status, matched.value1, matched.value2, fetched_at=fetched_at
        )
    return results


def _call_each(
    keys: list[str],
    runtime: Runtime,
    *,
    provider: str,
    to_query: Callable[[str], str | None],
    cache_key: Callable[[str], str],
    fetch: Callable[[str], tuple[str, str | None]],
    fresh: Callable[[LookupResult, datetime], bool],
) -> dict[str, LookupResult]:
    results: dict[str, LookupResult] = {}
    asked: dict[str, LookupResult] = {}
    budget = runtime.budgets.get(provider)
    deadline = runtime.monotonic() + runtime.run_seconds
    cached_as = f"{provider}:{ANSWER_FORMAT}"
    # Only values a service is actually asked about count towards the limit.
    calls = 0

    for key in keys:
        query = to_query(key)
        now = runtime.now()
        if query is None:
            # Not the shape of a postal code or a symbol, so there's nothing to ask.
            results[key] = LookupResult(Status.NOT_FOUND, fetched_at=freshness.stamp(now))
            continue
        if query in asked:
            results[key] = asked[query]
            continue

        held = runtime.cache.get(cached_as, cache_key(query))
        if held is not None and _still_good(held, now, fresh):
            results[key] = asked[query] = held
            continue

        if calls >= runtime.max_values or runtime.monotonic() >= deadline:
            results[key] = LookupResult(Status.PENDING)
            continue
        if budget is not None and not budget.take():
            results[key] = LookupResult(Status.RATE_LIMITED)
            continue

        calls += 1
        fetched_at = freshness.stamp(now)
        try:
            value1, value2 = fetch(query)
            result = LookupResult(Status.FOUND, value1, value2, fetched_at)
        except ConnectorError as error:
            result = LookupResult(error.status, fetched_at=fetched_at)
        # Only a definite answer is worth remembering. A service that was busy
        # or down gets asked again next time.
        if result.status in (Status.FOUND, Status.NOT_FOUND):
            runtime.cache.put(cached_as, cache_key(query), result)
        results[key] = asked[query] = result
    return results


def _still_good(
    held: LookupResult, now: datetime, fresh: Callable[[LookupResult, datetime], bool]
) -> bool:
    if held.status is Status.NOT_FOUND:
        return freshness.within_days(held.fetched_at, now, freshness.NOT_FOUND_DAYS)
    return held.status is Status.FOUND and fresh(held, now)
