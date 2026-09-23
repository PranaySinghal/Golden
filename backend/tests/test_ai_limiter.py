"""The ceiling on model calls: past it, the rule-based wording, never an error."""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.ai.client import ask, load_prompt
from app.ai.limiter import BudgetedProvider, CallBudget, RateLimitedError
from app.ai.provider import AnthropicProvider, NoProvider
from app.api.deps import get_provider
from app.config import Settings
from tests.test_api_ai import ScriptedProvider


class SimpleReply(BaseModel):
    pass


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_the_budget_allows_its_calls_then_stops() -> None:
    budget = CallBudget(3, clock=Clock())

    assert [budget.take() for _ in range(4)] == [True, True, True, False]


def test_the_budget_refills_evenly_over_the_minute() -> None:
    clock = Clock()
    budget = CallBudget(6, clock=clock)
    for _ in range(6):
        budget.take()

    clock.now = 10.0  # a sixth of a minute: one call back

    assert budget.take() is True
    assert budget.take() is False


def test_an_idle_minute_does_not_bank_more_than_the_budget() -> None:
    clock = Clock()
    budget = CallBudget(2, clock=clock)
    clock.now = 600.0

    assert [budget.take() for _ in range(3)] == [True, True, False]


def test_over_the_budget_the_service_is_not_asked() -> None:
    inner = ScriptedProvider({"wording": "{}"})
    provider = BudgetedProvider(inner, CallBudget(1, clock=Clock()))

    provider.complete("wording", "{}", 1000)
    with pytest.raises(RateLimitedError):
        provider.complete("wording", "{}", 1000)

    assert inner.asked == ["wording"]


def test_a_limited_call_falls_back_without_a_retry(caplog: pytest.LogCaptureFixture) -> None:
    inner = ScriptedProvider({"wording": json.dumps({})})
    provider = BudgetedProvider(inner, CallBudget(1, clock=Clock()))
    provider.complete("wording", "{}", 1000)  # spend the one call

    with caplog.at_level("INFO", logger="tidylab.ai"):
        reply = ask(provider, load_prompt("reword_issues"), {}, SimpleReply, 1000)

    assert reply is None
    assert len(inner.asked) == 1
    assert "outcome=rate_limited" in caplog.text


def _request(settings: Settings, budget: CallBudget) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings, llm_budget=budget))
    )


def test_a_configured_service_is_always_behind_the_budget() -> None:
    settings = Settings(llm_provider="anthropic", llm_api_key="test-key")

    provider = get_provider(_request(settings, CallBudget(5)))

    assert isinstance(provider, BudgetedProvider)
    assert provider.name == AnthropicProvider.name


def test_no_service_needs_no_budget() -> None:
    assert isinstance(get_provider(_request(Settings(), CallBudget(5))), NoProvider)
