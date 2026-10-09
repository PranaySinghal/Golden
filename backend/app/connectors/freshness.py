"""How long an answer stays good. Pure: every function takes "now".

A share price is worth fetching once per trading day, after the market opens.
There is no holiday calendar here on purpose. On a day the market is closed the
service returns the last close with its own timestamp, and that timestamp, not
ours, is what the "as of" column shows.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

MARKET_ZONE = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
POSTAL_DAYS = 90
NOT_FOUND_DAYS = 7
COMPANY_LIST_DAYS = 1


def parse(fetched_at: str | None) -> datetime | None:
    if not fetched_at:
        return None
    try:
        moment = datetime.fromisoformat(fetched_at)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def stamp(now: datetime) -> str:
    return now.astimezone(UTC).isoformat(timespec="seconds")


def last_market_open(now: datetime) -> datetime:
    """The most recent weekday 09:30 in New York at or before `now`."""
    local = now.astimezone(MARKET_ZONE)
    day = local.date()
    if local.time() < MARKET_OPEN:
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return datetime.combine(day, MARKET_OPEN, tzinfo=MARKET_ZONE)


def price_is_fresh(fetched_at: str | None, now: datetime) -> bool:
    fetched = parse(fetched_at)
    return fetched is not None and fetched >= last_market_open(now)


def within_days(fetched_at: str | None, now: datetime, days: int) -> bool:
    fetched = parse(fetched_at)
    return fetched is not None and now - fetched <= timedelta(days=days)


def as_of(epoch_seconds: int) -> str:
    """When a price was true, the way the market would say it: "2026-10-08 09:31 ET"."""
    moment = datetime.fromtimestamp(epoch_seconds, tz=MARKET_ZONE)
    return moment.strftime("%Y-%m-%d %H:%M") + " ET"
