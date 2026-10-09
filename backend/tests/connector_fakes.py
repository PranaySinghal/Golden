"""Stand-ins for the outside services. No test ever touches the network."""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from app.ai.limiter import CallBudget
from app.ai.provider import NoProvider
from app.connectors.cache import LookupCache
from app.connectors.http import Reply
from app.connectors.models import Company, ConnectorError, Quote
from app.connectors.runner import Runtime

# A Thursday, 15:00 UTC: 11:00 in New York, the market open since 09:30.
NOW = datetime(2026, 10, 8, 15, 0, tzinfo=UTC)

COMPANIES = [
    Company("AAPL", "Apple Inc."),
    Company("MSFT", "MICROSOFT CORP"),
    Company("GOOGL", "Alphabet Inc."),
    Company("GOOG", "Alphabet Inc."),
    Company("WMT", "Walmart Inc."),
]


class FakeGeocoder:
    name = "fake_postal"

    def __init__(self, answers: Mapping[str, tuple[float, float] | ConnectorError]) -> None:
        self.answers = answers
        self.asked: list[tuple[str, str]] = []

    def locate(self, country: str, code: str) -> tuple[float, float]:
        self.asked.append((country, code))
        answer = self.answers[code]
        if isinstance(answer, ConnectorError):
            raise answer
        return answer


class FakeSymbols:
    name = "fake_symbols"

    def __init__(self, companies: list[Company] | ConnectorError = COMPANIES) -> None:
        self.answer = companies
        self.downloads = 0

    def companies(self) -> list[Company]:
        self.downloads += 1
        if isinstance(self.answer, ConnectorError):
            raise self.answer
        return self.answer


class FakeQuotes:
    name = "fake_quotes"

    def __init__(self, answers: Mapping[str, Quote | ConnectorError]) -> None:
        self.answers = dict(answers)
        self.asked: list[str] = []

    def quote(self, symbol: str) -> Quote:
        self.asked.append(symbol)
        answer = self.answers[symbol]
        if isinstance(answer, ConnectorError):
            raise answer
        return answer


class FakeModel:
    """A model service that answers a fill request with whatever `answer` says for each row."""

    name = "anthropic"

    def __init__(
        self,
        answer: Callable[[dict[str, object]], object] | None = None,
        reply: str | Exception | None = None,
    ) -> None:
        self.answer = answer or (lambda row: None)
        self.reply = reply
        self.requests: list[dict[str, object]] = []
        self.systems: list[str] = []

    def complete(self, system: str, user: str, timeout_ms: int) -> str:
        request = json.loads(user)
        self.requests.append(request)
        self.systems.append(system)
        if isinstance(self.reply, Exception):
            raise self.reply
        if self.reply is not None:
            return self.reply
        return json.dumps(
            {"answers": [{"id": row["id"], "answer": self.answer(row)} for row in request["rows"]]}
        )

    @property
    def values_sent(self) -> list[str]:
        return [row["value"] for request in self.requests for row in request["rows"]]  # type: ignore[index, union-attr]


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now
        self.elapsed = 0.0

    def __call__(self) -> datetime:
        return self.now


def runtime(
    postal: object | None = None,
    symbols: object | None = None,
    quotes: object | None = None,
    *,
    model: object | None = None,
    fill_max_values: int = 400,
    cache: LookupCache | None = None,
    clock: Clock | None = None,
    max_values: int = 100,
    calls_per_minute: int = 1000,
    monotonic: Callable[[], float] | None = None,
) -> Runtime:
    geocoder = postal or FakeGeocoder({})
    lookup = symbols or FakeSymbols()
    prices = quotes or FakeQuotes({})
    return Runtime(
        postal=geocoder,  # type: ignore[arg-type]
        symbols=lookup,  # type: ignore[arg-type]
        quotes=prices,  # type: ignore[arg-type]
        cache=cache or LookupCache(),
        budgets={
            geocoder.name: CallBudget(calls_per_minute, clock=lambda: 0.0),  # type: ignore[attr-defined]
            prices.name: CallBudget(calls_per_minute, clock=lambda: 0.0),  # type: ignore[attr-defined]
        },
        max_values=max_values,
        model=model or NoProvider(),  # type: ignore[arg-type]
        model_id="fake-model",
        fill_max_values=fill_max_values,
        now=clock or Clock(),
        monotonic=monotonic or (lambda: 0.0),
    )


class ScriptedSend:
    """Answers each request with the next reply (or raises the next error) in a list."""

    def __init__(self, *replies: Reply | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str], timeout_seconds: float) -> Reply:
        self.requests.append((url, dict(headers)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
