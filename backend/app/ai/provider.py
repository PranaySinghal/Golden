"""Talking to a model service, or to none at all.

Both services are one JSON POST, so this is a small interface rather than two
SDKs. A provider takes a prompt and returns text; everything about what to ask
and whether to believe the answer lives above it.
"""

import json
from typing import Any, Protocol

import httpx

from app.config import Settings

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_OUTPUT_TOKENS = 2000
# Claude counts its own working-out against the limit, so it needs more room
# than the reply alone would take.
ANTHROPIC_MAX_TOKENS = 8000
# Wording, fixes and labels are small, well-specified jobs. Low effort keeps
# them quick and cheap; the checks on every reply are what keep them right.
ANTHROPIC_EFFORT = "low"
# Gemini only. Current Claude models refuse a request that sets a temperature.
TEMPERATURE = 0.2


class ProviderError(Exception):
    """The service couldn't be reached, or answered with something unusable."""


class Provider(Protocol):
    name: str

    def complete(self, system: str, user: str, timeout_ms: int) -> str: ...


class NoProvider:
    """What runs with LLM_PROVIDER=none: nothing is asked, nothing is sent."""

    name = "none"

    def complete(self, system: str, user: str, timeout_ms: int) -> str:
        raise ProviderError("No model service is configured.")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def request(self, system: str, user: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        """The call as data, so a test can read it without making it."""
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self._model,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            "output_config": {"effort": ANTHROPIC_EFFORT},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        return ANTHROPIC_URL, headers, body

    def complete(self, system: str, user: str, timeout_ms: int) -> str:
        url, headers, body = self.request(system, user)
        payload = _post(url, headers, body, timeout_ms)
        blocks = payload.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict))
        if not text:
            raise ProviderError("The model returned nothing.")
        return text


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def request(self, system: str, user: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = f"{GEMINI_URL}/{self._model}:generateContent"
        headers = {"x-goog-api-key": self._api_key, "content-type": "application/json"}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": TEMPERATURE,
                "maxOutputTokens": MAX_OUTPUT_TOKENS,
                "responseMimeType": "application/json",
            },
        }
        return url, headers, body

    def complete(self, system: str, user: str, timeout_ms: int) -> str:
        url, headers, body = self.request(system, user)
        payload = _post(url, headers, body, timeout_ms)
        candidates = payload.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not text:
            raise ProviderError("The model returned nothing.")
        return text


def build_provider(settings: Settings) -> Provider:
    if not settings.llm_enabled:
        return NoProvider()
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(settings.llm_api_key, settings.model_name)
    return GeminiProvider(settings.llm_api_key, settings.model_name)


def _post(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout_ms: int
) -> dict[str, Any]:
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=timeout_ms / 1000)
    except httpx.HTTPError as error:
        # The message can carry the URL but never the key or the payload.
        raise ProviderError(f"Couldn't reach the model service: {type(error).__name__}") from error
    if response.status_code >= 400:
        raise ProviderError(f"The model service answered {response.status_code}.")
    try:
        parsed: dict[str, Any] = response.json()
    except json.JSONDecodeError as error:
        raise ProviderError("The model service answered with something that isn't JSON.") from error
    return parsed
