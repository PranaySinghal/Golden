"""The list of listed companies and their stock symbols.

Nothing from a user's file is sent to get it: it is one public document,
downloaded whole and matched against here (matching.py).
"""

import time
from typing import Protocol

from app.connectors.http import Send, Sleep, get_json, httpx_send
from app.connectors.models import Company, UnavailableError


class SymbolLookup(Protocol):
    name: str

    def companies(self) -> list[Company]:
        """Every listed company, or raise a ConnectorError."""
        ...


class NoSymbols:
    name = "none"

    def companies(self) -> list[Company]:
        raise UnavailableError("No company list is set up.")


class Sec:
    """https://www.sec.gov/files/company_tickers.json — free; asks callers to say who they are."""

    name = "sec"
    URL = "https://www.sec.gov/files/company_tickers.json"

    def __init__(
        self, user_agent: str, timeout_ms: int, send: Send = httpx_send, sleep: Sleep = time.sleep
    ):
        self._user_agent = user_agent
        self._timeout_ms = timeout_ms
        self._send = send
        self._sleep = sleep

    def companies(self) -> list[Company]:
        body = get_json(
            self.URL,
            {"User-Agent": self._user_agent},
            timeout_ms=self._timeout_ms,
            send=self._send,
            sleep=self._sleep,
        )
        return parse_companies(body)


def parse_companies(body: object) -> list[Company]:
    entries = list(body.values()) if isinstance(body, dict) else body
    if not isinstance(entries, list):
        raise UnavailableError("unreadable answer")
    companies: list[Company] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise UnavailableError("unreadable answer")
        ticker, title = entry.get("ticker"), entry.get("title")
        if isinstance(ticker, str) and isinstance(title, str) and ticker and title:
            companies.append(Company(ticker.upper(), title))
    if not companies:
        raise UnavailableError("empty list")
    return companies
