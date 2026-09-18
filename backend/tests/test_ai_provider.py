"""Talking to a model service: what we send, and what we do when it goes wrong."""

import json
import logging
from typing import Any

import httpx
import pytest

from app.ai.client import ATTEMPTS, PROMPTS_DIR, ask, extract_json, load_prompt
from app.ai.provider import (
    AnthropicProvider,
    GeminiProvider,
    NoProvider,
    Provider,
    ProviderError,
    build_provider,
)
from app.ai.schemas import RewordQuestionsReply
from app.config import Settings

PROMPT = load_prompt("reword_questions")


class FakeProvider:
    """Answers with whatever a test wants, without touching the network."""

    name = "fake"

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, timeout_ms: int) -> str:
        self.calls.append((system, user))
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply


VALID = json.dumps({"items": [{"id": "q1", "label": "How many people are on the team?"}]})


# --- what gets sent -------------------------------------------------------------------------


def test_anthropic_sends_the_model_the_prompt_and_the_payload() -> None:
    provider = AnthropicProvider("secret-key", "claude-sonnet-5")

    url, headers, body = provider.request("be helpful", '{"a":1}')

    assert url.endswith("/v1/messages")
    assert headers["x-api-key"] == "secret-key"
    assert headers["anthropic-version"]
    assert body["model"] == "claude-sonnet-5"
    assert body["system"] == "be helpful"
    assert body["messages"] == [{"role": "user", "content": '{"a":1}'}]


def test_gemini_sends_the_same_two_things_its_own_way() -> None:
    provider = GeminiProvider("secret-key", "gemini-2.5-flash")

    url, headers, body = provider.request("be helpful", '{"a":1}')

    assert "gemini-2.5-flash:generateContent" in url
    assert headers["x-goog-api-key"] == "secret-key"
    assert body["systemInstruction"]["parts"][0]["text"] == "be helpful"
    assert body["contents"][0]["parts"][0]["text"] == '{"a":1}'


def test_without_a_provider_nothing_is_asked() -> None:
    settings = Settings()

    provider = build_provider(settings)

    assert isinstance(provider, NoProvider)
    with pytest.raises(ProviderError):
        provider.complete("system", "user", 1000)


def test_a_provider_without_a_key_is_no_provider() -> None:
    settings = Settings(llm_provider="anthropic", llm_api_key="")

    assert isinstance(build_provider(settings), NoProvider)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("anthropic", AnthropicProvider), ("gemini", GeminiProvider)],
)
def test_the_configured_service_is_the_one_built(provider: str, expected: type) -> None:
    settings = Settings(llm_provider=provider, llm_api_key="k")  # type: ignore[arg-type]

    assert isinstance(build_provider(settings), expected)


def test_a_service_that_cannot_be_reached_raises_without_leaking_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(httpx, "post", refuse)

    with pytest.raises(ProviderError) as raised:
        AnthropicProvider("secret-key", "m").complete("s", "u", 500)

    assert "secret-key" not in str(raised.value)


def test_an_error_status_is_a_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(500, json={}))

    with pytest.raises(ProviderError):
        AnthropicProvider("k", "m").complete("s", "u", 500)


def test_an_empty_reply_is_a_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json={"content": []}))

    with pytest.raises(ProviderError):
        AnthropicProvider("k", "m").complete("s", "u", 500)


def test_each_service_reply_shape_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: httpx.Response(200, json={"content": [{"type": "text", "text": "hi"}]}),
    )
    assert AnthropicProvider("k", "m").complete("s", "u", 500) == "hi"

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}
        ),
    )
    assert GeminiProvider("k", "m").complete("s", "u", 500) == "hi"


# --- prompts --------------------------------------------------------------------------------


def test_prompts_live_in_files_with_versions() -> None:
    files = sorted(path.name for path in PROMPTS_DIR.glob("*.md"))

    assert files == ["reword_issues.v1.md", "reword_questions.v1.md", "suggest_fixes.v1.md"]
    assert PROMPT.id == "reword_questions.v1"
    assert "JSON" in PROMPT.system


def test_every_prompt_forbids_inventing_numbers() -> None:
    for path in PROMPTS_DIR.glob("*.md"):
        assert "Never" in path.read_text()


# --- reading a reply ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"items": []}',
        'Here you go:\n```json\n{"items": []}\n```',
        'Sure! {"items": []} Hope that helps.',
    ],
)
def test_json_is_found_however_it_is_wrapped(text: str) -> None:
    assert json.loads(extract_json(text)) == {"items": []}


def test_a_good_reply_is_parsed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="tidylab.ai")
    provider = FakeProvider(VALID)

    reply = ask(provider, PROMPT, {"questions": []}, RewordQuestionsReply, 500)

    assert reply is not None
    assert reply.items[0].label == "How many people are on the team?"
    assert "outcome=ok" in caplog.text


def test_a_reply_that_isnt_json_falls_back_to_templates() -> None:
    provider = FakeProvider("I'd rather not.")

    assert ask(provider, PROMPT, {}, RewordQuestionsReply, 500) is None


def test_a_reply_of_the_wrong_shape_falls_back_to_templates() -> None:
    provider = FakeProvider(json.dumps({"items": [{"id": "q1"}]}))

    assert ask(provider, PROMPT, {}, RewordQuestionsReply, 500) is None


def test_extra_fields_are_not_accepted() -> None:
    provider = FakeProvider(json.dumps({"items": [], "run_this_sql": "DROP TABLE raw"}))

    assert ask(provider, PROMPT, {}, RewordQuestionsReply, 500) is None


def test_an_unreachable_service_is_tried_again_then_left_alone() -> None:
    provider = FakeProvider(ProviderError("down"), ProviderError("still down"))

    assert ask(provider, PROMPT, {}, RewordQuestionsReply, 500) is None
    assert len(provider.calls) == ATTEMPTS


def test_a_stumble_followed_by_an_answer_is_used() -> None:
    provider = FakeProvider(ProviderError("down"), VALID)

    assert ask(provider, PROMPT, {}, RewordQuestionsReply, 500) is not None


def test_a_reply_we_cannot_trust_is_not_asked_for_twice() -> None:
    """The model already had the schema; asking again just spends time."""
    provider = FakeProvider("not json", VALID)

    assert ask(provider, PROMPT, {}, RewordQuestionsReply, 500) is None
    assert len(provider.calls) == 1


def test_the_log_says_what_happened_and_nothing_about_the_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="tidylab.ai")
    provider: Provider = FakeProvider(VALID)

    ask(
        provider,
        PROMPT,
        {"questions": [{"id": "q1", "label": "secret-value"}]},
        RewordQuestionsReply,
        500,
    )

    assert "prompt=reword_questions.v1" in caplog.text
    assert "ms=" in caplog.text
    assert "secret-value" not in caplog.text
