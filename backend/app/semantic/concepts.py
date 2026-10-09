"""Telling when a new column would repeat one a connector already filled in.

"Map position", "Latitude and longitude" and "Geolocation" are one thing under
three names. Once a lookup has added it, offering it again as an empty column,
or letting one be added, would put the same thing in the table twice.
Matching is on the words of the name, since a name is all a new column has.
"""

from app.profile.name_hints import name_words

MAP_POSITION = "Map positions"
SHARE_PRICE = "Share prices"
STOCK_SYMBOL = "Stock symbols"

# What each connector adds, in the words used to tell the user it is already there.
CONNECTOR_CONCEPTS: dict[str, str] = {
    "postal_geocode": MAP_POSITION,
    "stock_price": SHARE_PRICE,
    "company_ticker": STOCK_SYMBOL,
}

_POSITION_WORDS = {
    "latitude", "longitude", "lat", "lng", "lon", "coordinates", "coordinate", "geolocation",
    "geocode", "geo",
}  # fmt: skip
_PLACE_WORDS = {"position", "positions", "location", "locations", "pin", "coordinates"}
_SHARE_WORDS = {"stock", "share", "shares", "quote"}
_PRICE_WORDS = {"price", "prices", "quote"}
_SYMBOL_WORDS = {"symbol", "symbols", "ticker", "tickers"}


def concept_of(name: str) -> str | None:
    """Which looked-up thing a column name means, if any."""
    words = set(name_words(name))
    if words & _POSITION_WORDS or ("map" in words and words & _PLACE_WORDS):
        return MAP_POSITION
    if words & _SHARE_WORDS and words & _PRICE_WORDS:
        return SHARE_PRICE
    if "ticker" in words or "tickers" in words or ("stock" in words and words & _SYMBOL_WORDS):
        return STOCK_SYMBOL
    return None
