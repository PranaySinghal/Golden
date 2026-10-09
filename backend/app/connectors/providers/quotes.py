"""Stock symbol to latest price."""

import time
from typing import Protocol
from urllib.parse import quote as url_quote

from app.connectors.http import Send, Sleep, get_json, httpx_send
from app.connectors.models import NotFoundError, Quote, UnavailableError


class QuoteProvider(Protocol):
    name: str

    def quote(self, symbol: str) -> Quote:
        """The latest price for a symbol, or raise a ConnectorError."""
        ...


class NoQuotes:
    name = "none"

    def quote(self, symbol: str) -> Quote:
        raise UnavailableError("No price service is set up.")


class Finnhub:
    """https://finnhub.io/docs/api/quote — free tier, needs a key."""

    name = "finnhub"
    BASE = "https://finnhub.io/api/v1/quote"

    def __init__(
        self, api_key: str, timeout_ms: int, send: Send = httpx_send, sleep: Sleep = time.sleep
    ):
        self._api_key = api_key
        self._timeout_ms = timeout_ms
        self._send = send
        self._sleep = sleep

    def quote(self, symbol: str) -> Quote:
        body = get_json(
            f"{self.BASE}?symbol={url_quote(symbol, safe='')}",
            # In a header, never the address: addresses end up in logs.
            {"X-Finnhub-Token": self._api_key},
            timeout_ms=self._timeout_ms,
            send=self._send,
            sleep=self._sleep,
        )
        if not isinstance(body, dict):
            raise UnavailableError("unreadable answer")
        price, at = body.get("c"), body.get("t")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise UnavailableError("unreadable answer")
        if isinstance(at, bool) or not isinstance(at, (int, float)):
            raise UnavailableError("unreadable answer")
        # The service answers an unknown symbol with zeros rather than an error.
        if price <= 0 or at <= 0:
            raise NotFoundError("not found")
        return Quote(price=float(price), at=int(at))
