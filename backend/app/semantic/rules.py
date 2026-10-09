"""Column ideas that need no model: what the file holds decides what's offered.

Each idea is tied to a general kind of table (one that lists organisations,
places, money, people to contact), never to a particular file. The kind of
values in a column is the main evidence; words in a column's name are a weaker
hint, the same way `profile/name_hints.py` uses them. The last few ideas fit
any table, so there is always something to offer.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.profile.models import DatasetProfile, PatternKind, SemanticRole
from app.profile.name_hints import name_words
from app.semantic.models import ColumnSuggestion

_ORGANISATION_WORDS = {
    "company", "companies", "organisation", "organization", "org", "business", "employer",
    "vendor", "supplier", "manufacturer", "brand", "account", "client", "customer", "firm",
}  # fmt: skip
_TICKER_WORDS = {"ticker", "symbol", "stock"}
_PLACE_WORDS = {
    "address", "city", "town", "country", "state", "province", "region", "location",
    "postcode", "zip", "postal", "street", "headquarters", "hq", "site", "branch", "store",
}  # fmt: skip
_COORDINATE_WORDS = {"lat", "latitude", "lon", "lng", "long", "longitude"}
_MONEY_WORDS = {
    "price", "amount", "revenue", "sales", "cost", "salary", "pay", "total", "fee", "budget",
    "income", "spend", "value", "balance",
}  # fmt: skip


@dataclass(frozen=True)
class _Facts:
    """The few things about a file the ideas below depend on."""

    words: frozenset[str]
    roles: frozenset[SemanticRole]
    patterns: frozenset[PatternKind]

    def has_word(self, wanted: set[str]) -> bool:
        return bool(self.words & wanted)


@dataclass(frozen=True)
class _Idea:
    fits: Callable[[_Facts], bool]
    suggestion: ColumnSuggestion


def _idea(
    fits: Callable[[_Facts], bool],
    name: str,
    reason: str,
    placeholder: str | None = None,
    live_source: str | None = None,
) -> _Idea:
    return _Idea(
        fits,
        ColumnSuggestion(
            name=name, reason=reason, placeholder=placeholder, live_source=live_source
        ),
    )


def _lists_organisations(facts: _Facts) -> bool:
    return facts.has_word(_ORGANISATION_WORDS)


def _has_places(facts: _Facts) -> bool:
    return facts.has_word(_PLACE_WORDS) and not facts.has_word(_COORDINATE_WORDS)


def _has_money(facts: _Facts) -> bool:
    return PatternKind.CURRENCY in facts.patterns or (
        SemanticRole.MEASURE in facts.roles and facts.has_word(_MONEY_WORDS)
    )


def _has_contacts(facts: _Facts) -> bool:
    return SemanticRole.CONTACT in facts.roles


def _always(facts: _Facts) -> bool:
    return True


# In the order they're offered: the most specific to this kind of file first.
_IDEAS: tuple[_Idea, ...] = (
    _idea(
        lambda facts: facts.has_word(_TICKER_WORDS),
        "Stock price",
        "This file names traded companies, so their current share price can sit beside them.",
        live_source="A stock price service",
    ),
    _idea(
        _lists_organisations,
        "Industry",
        "This file lists organisations. Their line of business lets you group and compare them.",
    ),
    _idea(
        _lists_organisations,
        "Website",
        "This file lists organisations. A web address makes each one easy to look up.",
    ),
    _idea(
        _has_places,
        "Map position",
        "This file has places in it. A map position lets you plot them or measure distances.",
        live_source="A map lookup service",
    ),
    _idea(
        _has_money,
        "Currency",
        "This file has money amounts. Saying which currency they are in avoids mixing them up.",
    ),
    _idea(
        _has_contacts,
        "Last contacted",
        "This file has contact details. A date shows who you haven't been in touch with lately.",
    ),
    _idea(
        _always,
        "Status",
        "A place to mark where each row stands as you work through the file.",
        placeholder="To review",
    ),
    _idea(_always, "Owner", "A place to say who looks after each row."),
    _idea(_always, "Notes", "A place for comments that don't belong in any other column."),
)


def rule_suggestions(profile: DatasetProfile) -> list[ColumnSuggestion]:
    """Every built-in idea that fits this file, most specific first."""
    facts = _Facts(
        words=frozenset(word for column in profile.columns for word in name_words(column.name)),
        roles=frozenset(column.semantic_role for column in profile.columns),
        patterns=frozenset(
            pattern.kind for column in profile.columns for pattern in column.patterns
        ),
    )
    return [idea.suggestion for idea in _IDEAS if idea.fits(facts)]
