"""The one place a connector touches the network.

Every call is bounded in time and tried again a couple of times with a growing
pause when the service stumbles. Whatever goes wrong comes out as one of four
typed errors, so the caller can leave the cell empty with the right reason
instead of guessing. Nothing here logs a URL: the value being looked up is in it.
"""

import json
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.connectors.models import (
    NotFoundError,
    RateLimitedError,
    TimedOutError,
    UnavailableError,
)

RETRIES = 2
BACKOFF_SECONDS = 0.5
# However long a service asks us to wait, a person is watching a spinner.
MAX_WAIT_SECONDS = 5.0


@dataclass(frozen=True)
class Reply:
    status: int
    text: str
    headers: Mapping[str, str] = field(default_factory=dict)


Send = Callable[[str, Mapping[str, str], float], Reply]
Sleep = Callable[[float], None]


def httpx_send(url: str, headers: Mapping[str, str], timeout_seconds: float) -> Reply:
    try:
        response = httpx.get(url, headers=dict(headers), timeout=timeout_seconds)
    except httpx.TimeoutException as error:
        raise TimedOutError("no answer in time") from error
    except httpx.HTTPError as error:
        raise UnavailableError("could not be reached") from error
    return Reply(response.status_code, response.text, dict(response.headers))


def _seconds(retry_after: str | None) -> float:
    """What a service asked us to wait, when it said so in seconds."""
    try:
        return float(retry_after or 0)
    except ValueError:
        # A date instead of a number; our own pause stands.
        return 0.0


def _pause(attempt: int, retry_after: str | None = None) -> float:
    wait = BACKOFF_SECONDS * (2**attempt) + random.uniform(0, BACKOFF_SECONDS / 2)
    return float(min(max(wait, _seconds(retry_after)), MAX_WAIT_SECONDS))


def get_json(
    url: str,
    headers: Mapping[str, str] | None = None,
    *,
    timeout_ms: int,
    send: Send = httpx_send,
    sleep: Sleep = time.sleep,
) -> Any:
    """GET a URL and parse its JSON, or raise a ConnectorError saying why not."""
    last: Exception = UnavailableError("no answer")
    retry_after: str | None = None
    for attempt in range(RETRIES + 1):
        if attempt:
            sleep(_pause(attempt - 1, retry_after))
        retry_after = None
        try:
            reply = send(url, headers or {}, timeout_ms / 1000)
        except (TimedOutError, UnavailableError) as error:
            last = error
            continue
        if reply.status == 404:
            raise NotFoundError("not found")
        if reply.status == 429:
            last = RateLimitedError("asked too often")
            retry_after = reply.headers.get("retry-after")
            continue
        if reply.status >= 500:
            last = UnavailableError(f"service error {reply.status}")
            continue
        if reply.status >= 400:
            # Our request was refused (a bad key, say). Asking again won't help.
            raise UnavailableError(f"refused {reply.status}")
        try:
            return json.loads(reply.text)
        except json.JSONDecodeError as error:
            raise UnavailableError("unreadable answer") from error
    raise last
