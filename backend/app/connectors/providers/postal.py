"""Postal code to map position."""

import time
from typing import Protocol
from urllib.parse import quote

from app.connectors.http import Send, Sleep, get_json, httpx_send
from app.connectors.models import NotFoundError, UnavailableError


class PostalGeocoder(Protocol):
    name: str

    def locate(self, country: str, code: str) -> tuple[float, float]:
        """(latitude, longitude) for a postal code, or raise a ConnectorError."""
        ...


class NoGeocoder:
    name = "none"

    def locate(self, country: str, code: str) -> tuple[float, float]:
        raise UnavailableError("No postal lookup is set up.")


class Zippopotam:
    """https://api.zippopotam.us — free, no key."""

    name = "zippopotam"
    BASE = "https://api.zippopotam.us"

    def __init__(self, timeout_ms: int, send: Send = httpx_send, sleep: Sleep = time.sleep):
        self._timeout_ms = timeout_ms
        self._send = send
        self._sleep = sleep

    def locate(self, country: str, code: str) -> tuple[float, float]:
        url = f"{self.BASE}/{quote(country.lower(), safe='')}/{quote(code, safe='')}"
        body = get_json(url, timeout_ms=self._timeout_ms, send=self._send, sleep=self._sleep)
        places = body.get("places") if isinstance(body, dict) else None
        if places == [] or (isinstance(body, dict) and not body):
            raise NotFoundError("not found")
        try:
            place = places[0]  # type: ignore[index]
            latitude, longitude = float(place["latitude"]), float(place["longitude"])
        except (TypeError, KeyError, IndexError, ValueError) as error:
            raise UnavailableError("unreadable answer") from error
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            # The service has an entry for this code but not a usable position
            # (some German codes come back with another field in its place).
            # Asking again won't change that, so it is "not found", not "try later".
            raise NotFoundError("no usable position")
        return latitude, longitude
