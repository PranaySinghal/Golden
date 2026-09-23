"""A ceiling on model calls per minute, shared by every request to this server.

Past it, a call fails the way an unreachable service does, and the caller keeps
the rule-based wording it would have used anyway (CLAUDE.md principle 8). The
user sees the same "couldn't answer" note, not an error.
"""

import threading
import time
from collections.abc import Callable

from app.ai.provider import Provider, ProviderError

SECONDS_PER_MINUTE = 60.0


class RateLimitedError(ProviderError):
    """Too many calls this minute. Not worth retrying straight away."""


class CallBudget:
    """A token bucket: `per_minute` calls, refilled evenly over the minute."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._capacity = float(per_minute)
        self._rate = per_minute / SECONDS_PER_MINUTE
        self._tokens = self._capacity
        self._clock = clock
        self._last = clock()
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            now = self._clock()
            self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens < 1:
                return False
            self._tokens -= 1
            return True


class BudgetedProvider:
    """A provider that asks the budget before every call."""

    def __init__(self, inner: Provider, budget: CallBudget) -> None:
        self.name = inner.name
        self._inner = inner
        self._budget = budget

    def complete(self, system: str, user: str, timeout_ms: int) -> str:
        if not self._budget.take():
            raise RateLimitedError("Too many model calls this minute.")
        return self._inner.complete(system, user, timeout_ms)
