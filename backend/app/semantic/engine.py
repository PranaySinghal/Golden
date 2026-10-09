"""Working out which columns to offer on the canvas.

Two sources, one list. The built-in ideas (`rules.py`) always answer. When a
model service is configured it is shown the column names, what each column
holds and the first few rows, and asked what the file is about and what would
be worth adding. Its ideas are checked here before anyone sees them, and the
built-in ones fill whatever space is left, so the list is never short.

A suggestion is only ever a name and a sentence. Adding one makes an ordinary
recipe step, so nothing a model says reaches the data on its own.
"""

import logging
from collections.abc import Iterable
from typing import Any

import duckdb

from app.ai import payload as payloads
from app.ai.client import ask, load_prompt
from app.ai.provider import Provider, build_provider
from app.ai.schemas import ProposedColumn, SuggestColumnsReply
from app.ai.wording import MARKDOWN, is_acceptable, uses_jargon
from app.config import Settings
from app.db import ROW_ID_COLUMN
from app.profile.models import DatasetProfile, SemanticRole
from app.semantic.concepts import concept_of
from app.semantic.models import (
    MAX_SUGGESTIONS,
    ColumnIdeas,
    ColumnSuggestion,
    FillPlan,
    Suggestions,
)
from app.semantic.rules import rule_suggestions

logger = logging.getLogger("tidylab.ai")

# Enough rows to see what kind of thing each row is; far fewer than the general cap.
SAMPLE_ROWS = 5
# v2 also asks whether each column could be filled in by a model, and from what.
PROMPT_VERSION = "v2"
# A label list shorter than this isn't a list of labels.
MIN_CHOICES = 2


def columns_payload(conn: duckdb.DuckDBPyConnection, profile: DatasetProfile) -> dict[str, Any]:
    """What the "suggest columns" prompt gets: the header, what each column holds, five rows."""
    return payloads.within_limit(
        {
            "columns": [payloads.column_facts(column).model_dump() for column in profile.columns],
            "sample_rows": payloads.sample_rows(conn, profile, SAMPLE_ROWS),
        }
    )


def ask_for_ideas(
    conn: duckdb.DuckDBPyConnection,
    profile: DatasetProfile,
    settings: Settings,
    provider: Provider | None = None,
) -> ColumnIdeas:
    """A model's reading of the file, checked. Asked once per file by the caller."""
    if not settings.llm_enabled:
        return ColumnIdeas(status="off")
    payload = columns_payload(conn, profile)
    reply = ask(
        provider or build_provider(settings),
        load_prompt("suggest_columns", PROMPT_VERSION),
        payload,
        SuggestColumnsReply,
        settings.llm_timeout_ms,
    )
    if reply is None:
        return ColumnIdeas(status="failed")
    return accepted_ideas(profile, reply, source_text=str(payload))


def accepted_ideas(
    profile: DatasetProfile, reply: SuggestColumnsReply, source_text: str
) -> ColumnIdeas:
    """Keep the ideas that are safe to show; drop the rest one at a time.

    `source_text` is everything the model was shown. A suggestion may only use
    figures that appear in it, so no number reaches the screen that the file
    didn't already hold.
    """
    existing = {column.name.casefold() for column in profile.columns}
    existing.add(ROW_ID_COLUMN.casefold())
    kept: list[ColumnSuggestion] = []
    for proposed in reply.columns:
        folded = proposed.name.casefold()
        if folded in existing:
            logger.info("ai column rejected reason=already in the file")
            continue
        if folded in {suggestion.name.casefold() for suggestion in kept}:
            logger.info("ai column rejected reason=suggested twice")
            continue
        why = _first_problem(
            source_text,
            [proposed.name, proposed.reason, proposed.placeholder, proposed.live_source],
        )
        if why:
            logger.info("ai column rejected reason=%s", why)
            continue
        kept.append(
            ColumnSuggestion(
                name=proposed.name,
                reason=proposed.reason,
                placeholder=proposed.placeholder or None,
                live_source=proposed.live_source or None,
                source="ai",
                fill=_fill_plan(profile, proposed),
            )
        )

    about = reply.about or None
    if about and _first_problem(source_text, [about]):
        about = None
    logger.info("ai columns kept=%d/%d", len(kept), len(reply.columns))
    return ColumnIdeas(status="ready", about=about, suggestions=kept[:MAX_SUGGESTIONS])


def _fill_plan(profile: DatasetProfile, proposed: ProposedColumn) -> FillPlan | None:
    """How a model could fill this column in, if what it proposed holds together.

    A plan that doesn't (a column that isn't there, a label column with no
    labels) is dropped quietly: the suggestion is still good as an empty column.
    """
    if proposed.kind == "none":
        return None
    source = next((c for c in profile.columns if c.name == proposed.based_on), None)
    if source is None:
        return None
    if source.semantic_role in (SemanticRole.MEASURE, SemanticRole.DATE):
        # A band from a salary or a weekday from a date is arithmetic. That is
        # the engine's to work out exactly, not a model's to estimate.
        return None
    choices: list[str] = []
    if proposed.kind == "label":
        for choice in proposed.choices:
            folded = {kept.casefold() for kept in choices}
            if choice and choice.casefold() not in folded and not _unreadable(choice):
                choices.append(choice)
        if len(choices) < MIN_CHOICES:
            return None
    return FillPlan(based_on=proposed.based_on, kind=proposed.kind, choices=choices)


def _unreadable(label: str) -> bool:
    return uses_jargon(label) or any(mark in label for mark in MARKDOWN)


def _first_problem(source_text: str, texts: Iterable[str | None]) -> str:
    for text in texts:
        if not text:
            continue
        ok, why = is_acceptable(source_text, text)
        if not ok:
            return why
    return ""


def suggestions_for(
    profile: DatasetProfile,
    taken: Iterable[str],
    ideas: ColumnIdeas | None = None,
    covered: Iterable[str] = (),
) -> Suggestions:
    """Up to five columns worth adding that the table doesn't already have.

    A model's ideas come first because they were written for this file; the
    built-in ones fill the rest. `taken` is every column name in use, including
    ones the user has already added. `covered` is what connectors have already
    looked up (see concepts.py): an idea for the same thing under another name
    is a duplicate, and is not offered.
    """
    used = {name.casefold() for name in taken}
    already = set(covered)
    offered: list[ColumnSuggestion] = []
    for suggestion in [*(ideas.suggestions if ideas else []), *rule_suggestions(profile)]:
        folded = suggestion.name.casefold()
        if folded in used or len(offered) == MAX_SUGGESTIONS:
            continue
        concept = concept_of(suggestion.name)
        if concept in already:
            continue
        if concept is not None:
            # "Share price" from a model and "Stock price" from the built-in list
            # are one idea; whichever comes first stands for both.
            already.add(concept)
        used.add(folded)
        offered.append(suggestion)
    return Suggestions(
        status=ideas.status if ideas else "off",
        about=ideas.about if ideas else None,
        suggestions=offered,
    )
