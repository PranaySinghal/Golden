"""What a lookup can come back with: an answer, or a plain reason there isn't one."""

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "several_matches"
    # A model was asked and said it didn't know, or gave an answer we wouldn't accept.
    NOT_SURE = "not_sure"
    RATE_LIMITED = "rate_limited"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"
    # Nobody has asked yet: over this run's limit, or the run ran out of time.
    PENDING = "not_looked_up"


# How each outcome is said to a user. A cell without an answer always has one of these.
REASONS: dict[Status, str] = {
    Status.FOUND: "found",
    Status.NOT_FOUND: "not found",
    Status.AMBIGUOUS: "several matches",
    Status.NOT_SURE: "not sure",
    Status.RATE_LIMITED: "rate limited",
    Status.TIMED_OUT: "timed out",
    Status.UNAVAILABLE: "service unavailable",
    Status.PENDING: "not looked up yet",
}


@dataclass(frozen=True)
class LookupResult:
    """One value's answer. `value1`/`value2` are only set when it was found,
    except that an ambiguous match lists its candidates in `value2`."""

    status: Status
    value1: str | None = None
    value2: str | None = None
    # When the answer was fetched, ISO 8601 in UTC.
    fetched_at: str | None = None


@dataclass(frozen=True)
class Company:
    ticker: str
    title: str


@dataclass(frozen=True)
class Quote:
    price: float
    # When the price was true, seconds since 1970 as the service reports it.
    at: int


class ConnectorError(Exception):
    """A lookup that produced no answer. `status` says which kind, for the cell's reason."""

    status: Status = Status.UNAVAILABLE


class NotFoundError(ConnectorError):
    status = Status.NOT_FOUND


class RateLimitedError(ConnectorError):
    status = Status.RATE_LIMITED


class TimedOutError(ConnectorError):
    status = Status.TIMED_OUT


class UnavailableError(ConnectorError):
    """The service is off, down, or answered with something we can't read."""

    status = Status.UNAVAILABLE
