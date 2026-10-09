"""Connectors as a user meets them: what could be looked up, doing it, and what came back.

A lookup happens in three parts so that the slow one holds no lock:

1. `prepare_run` (under the session lock) checks the request, records consent
   and reads the different values to ask about.
2. `runner.look_up` (no lock) asks the services.
3. `finish_run` (under the lock again) stores the answers as a new snapshot and
   points the recipe step at it. That is an ordinary recipe edit: undo brings
   the previous answers back.

Nothing is ever sent without the user saying so for that connector on that
file. A recipe replayed from another file arrives with its lookup steps empty.
"""

from dataclasses import dataclass
from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, ValidationError

from app import review
from app.connectors import freshness
from app.connectors.ai_fill import FillItem, FillSpec, fill_values
from app.connectors.detect import Offer, find_offers
from app.connectors.matching import build_index, decode_candidates
from app.connectors.models import REASONS, LookupResult, Status
from app.connectors.normalize import POSTAL_BY_COUNTRY
from app.connectors.runner import Runtime, cached_companies, look_up
from app.db import ENRICHMENTS_REF, quote_ident, work_ref
from app.detectors.base import DetectorContext, IssueBuilder
from app.detectors.models import AskQuestion, DetectorName, Issue, Tier
from app.errors import AppError
from app.steps import recipe_ops
from app.steps.apply import CLEANED_TABLE, StepStatus, chain_sql, plan_recipe
from app.steps.errors import StepNotFoundError, StepValidationError
from app.steps.models import (
    MAX_FILL_CHOICES,
    ConnectorName,
    EnrichColumnStep,
    FillKind,
    Recipe,
    ResolveMatchStep,
    new_step_id,
)
from app.steps.schema import ValueKind, match_key, text_of, trimmed
from app.store import DatasetSession

# Cards for names with several matches, most rows first. More than this is noise.
MAX_MATCH_QUESTIONS = 10
# An ask question takes at most four choices; one of them is "leave it empty".
MAX_CANDIDATES = 3
EXAMPLES_PER_REASON = 3
DEFAULT_NAMES: dict[str, list[str]] = {
    "postal_geocode": ["Geolocation"],
    "company_ticker": ["Ticker"],
    "stock_price": ["Price"],
}
# What a looked-up column may hold: text, or codes already read as numbers.
LOOKUP_KINDS = (ValueKind.TEXT, ValueKind.NUMBER)
# Outcomes worth another run. "Not found" and "several matches" are answers.
_UNFINISHED = (Status.PENDING, Status.RATE_LIMITED, Status.TIMED_OUT, Status.UNAVAILABLE)


class ConsentRequiredError(AppError):
    code = "consent_required"
    http_status = 409

    def __init__(self) -> None:
        super().__init__("Please confirm what will be sent before anything is looked up.")


class ConnectorOffError(AppError):
    code = "connector_off"
    http_status = 409

    def __init__(self) -> None:
        super().__init__("This connector isn't set up on this server yet.")


class ConnectorInactiveError(AppError):
    code = "connector_inactive"
    http_status = 409

    def __init__(self) -> None:
        super().__init__("Turn this connector on for this file first.")


class ConnectorView(BaseModel):
    id: ConnectorName
    title: str
    adds: str
    # Exactly what leaves the server when it runs, in plain words.
    sends: str
    service: str
    # Set up on this server. Decided by whoever runs it.
    enabled: bool
    # Switched on by the user for the file they have open. Always off without a file.
    active: bool = False


class CountryOption(BaseModel):
    code: str
    name: str


class OfferView(BaseModel):
    connector: ConnectorName
    column: str
    title: str
    distinct_values: int
    # Postal codes only: the user must say which country before anything is sent.
    countries: list[CountryOption] = Field(default_factory=list)
    enabled: bool


class EnrichmentView(BaseModel):
    step_id: str
    connector: ConnectorName
    column: str
    into: list[str]
    # False until the user has asked for the lookup on this file.
    looked_up: bool
    # Different values by outcome, in the words a user reads: "found", "not found", ...
    counts: dict[str, int] = Field(default_factory=dict)
    examples: dict[str, list[str]] = Field(default_factory=dict)
    # Values another run could still fill in.
    remaining: int = 0
    as_of: str | None = None
    # Prices from before the latest market open.
    out_of_date: bool = False
    enabled: bool


class ConnectorsOverview(BaseModel):
    connectors: list[ConnectorView]
    offers: list[OfferView] = Field(default_factory=list)
    enrichments: list[EnrichmentView] = Field(default_factory=list)
    # Connectors the user has already agreed to use on this file.
    consented: list[ConnectorName] = Field(default_factory=list)


def enabled(runtime: Runtime, connector: str) -> bool:
    names = {
        "postal_geocode": runtime.postal.name,
        "company_ticker": runtime.symbols.name,
        "stock_price": runtime.quotes.name,
        "ai_fill": runtime.model.name,
    }
    return names[connector] != "none"


def connector_views(
    runtime: Runtime, active: frozenset[str] | set[str] = frozenset()
) -> list[ConnectorView]:
    views = [
        ConnectorView(
            id="postal_geocode",
            title="Map positions from postal codes",
            adds="A map position (latitude, longitude) for each postal code.",
            sends="Each different postal code and the country you choose. Nothing else.",
            service="Zippopotam.us",
            enabled=enabled(runtime, "postal_geocode"),
        ),
        ConnectorView(
            id="company_ticker",
            title="Stock symbols from company names",
            adds="The stock symbol of each company that is listed in the United States.",
            sends=(
                "Nothing from your file. The public list of listed companies is "
                "downloaded and your names are matched against it here."
            ),
            service="U.S. Securities and Exchange Commission",
            enabled=enabled(runtime, "company_ticker"),
        ),
        ConnectorView(
            id="stock_price",
            title="Latest share prices from stock symbols",
            adds="The latest price in US dollars for each stock symbol.",
            sends="Each different stock symbol. Nothing else.",
            service="Finnhub",
            enabled=enabled(runtime, "stock_price"),
        ),
        ConnectorView(
            id="ai_fill",
            title="Fill a new column with AI",
            adds=(
                "Text a model works out from another column, such as an industry or a "
                "website. Unverified: it can be wrong, and is left blank when unsure."
            ),
            sends=(
                "Each different value in the column the new one is based on, and up to "
                "two columns beside it. Nothing else."
            ),
            service=MODEL_SERVICES.get(runtime.model.name, "A model service"),
            enabled=enabled(runtime, "ai_fill"),
        ),
    ]
    return [view.model_copy(update={"active": view.id in active}) for view in views]


def set_active(session: DatasetSession, runtime: Runtime, connector: str, active: bool) -> None:
    """Switch a connector on or off for this file. Off is the state every file starts in.

    Switching off sends nothing and removes nothing: columns already looked up
    stay, and no further lookup can run until it is switched back on.
    """
    if not active:
        session.connectors_on.discard(connector)
        return
    if not enabled(runtime, connector):
        raise ConnectorOffError
    session.connectors_on.add(connector)


MODEL_SERVICES = {"anthropic": "Anthropic (Claude)", "gemini": "Google (Gemini)"}
AI_LABEL = "Filled in by AI and not verified. Check before relying on it."
PREVIEW_VALUES = 8

_OFFER_TITLES = {
    "postal_geocode": 'Add map positions from "{column}"',
    "company_ticker": 'Add stock symbols from "{column}"',
    "stock_price": 'Add share prices from "{column}"',
}


def overview(session: DatasetSession, runtime: Runtime) -> ConnectorsOverview:
    """What could be looked up in this file, and what already has been.

    Call after the recipe has been applied: detection reads the cleaned table.
    """
    assert session.applied is not None
    steps = [step for step in session.recipe.steps if isinstance(step, EnrichColumnStep)]
    taken = {(step.connector, step.column) for step in steps}
    companies = cached_companies(runtime)
    index = build_index(companies) if companies is not None else None

    offers = [
        _offer_view(offer, runtime)
        for offer in find_offers(session.conn, session.applied.columns, index)
        if (offer.connector, offer.column) not in taken
    ]
    return ConnectorsOverview(
        connectors=connector_views(runtime, session.connectors_on),
        offers=offers,
        enrichments=[_enrichment_view(session, step, runtime) for step in steps],
        consented=sorted(session.connector_consent),
    )


def _offer_view(offer: Offer, runtime: Runtime) -> OfferView:
    return OfferView(
        connector=offer.connector,
        column=offer.column,
        title=_OFFER_TITLES[offer.connector].format(column=offer.column),
        distinct_values=offer.distinct_values,
        countries=[
            CountryOption(code=code, name=POSTAL_BY_COUNTRY[code].name) for code in offer.countries
        ],
        enabled=enabled(runtime, offer.connector),
    )


def _enrichment_view(
    session: DatasetSession, step: EnrichColumnStep, runtime: Runtime
) -> EnrichmentView:
    view = EnrichmentView(
        step_id=step.id,
        connector=step.connector,
        column=step.column,
        into=list(step.into),
        looked_up=step.snapshot is not None,
        enabled=enabled(runtime, step.connector),
    )
    if step.snapshot is None:
        return view
    rows = session.conn.execute(
        f"SELECT status, shown, value2, fetched_at FROM {ENRICHMENTS_REF} "
        "WHERE snapshot = $snapshot ORDER BY key",
        {"snapshot": step.snapshot},
    ).fetchall()
    now = runtime.now()
    for status_text, shown, value2, fetched_at in rows:
        status = Status(status_text)
        reason = REASONS[status]
        view.counts[reason] = view.counts.get(reason, 0) + 1
        if status is not Status.FOUND:
            listed = view.examples.setdefault(reason, [])
            if len(listed) < EXAMPLES_PER_REASON:
                listed.append(str(shown))
        if status in _UNFINISHED:
            view.remaining += 1
        if step.connector == "stock_price" and status is Status.FOUND:
            view.as_of = max(view.as_of or "", str(value2 or "")) or None
            if not freshness.price_is_fresh(fetched_at, now):
                view.out_of_date = True
    return view


# --- running a lookup -----------------------------------------------------------------------


class FillRequest(BaseModel):
    """A new column for a model to fill in: what it's called, what it means, what it's based on."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    based_on: str
    instruction: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    kind: FillKind
    choices: Annotated[list[str], Field(max_length=MAX_FILL_CHOICES)] = Field(default_factory=list)
    context: Annotated[list[str], Field(max_length=2)] = Field(default_factory=list)


@dataclass(frozen=True)
class PreparedRun:
    step: EnrichColumnStep
    is_new: bool
    # Different values to ask about, most common first, as the key they're stored under.
    keys: list[str]
    shown: dict[str, str]
    rows: dict[str, int]
    # AI fill only: what sits beside each value in the step's context columns.
    context: dict[str, dict[str, str]]

    def fill_spec(self) -> FillSpec:
        step = self.step
        assert step.instruction is not None
        assert step.kind is not None
        return FillSpec(
            name=step.into[0],
            instruction=step.instruction,
            kind=step.kind,
            based_on=step.column,
            choices=tuple(step.choices),
        )

    def fill_items(self) -> list[FillItem]:
        return [
            FillItem(key, self.shown.get(key, key), self.context.get(key, {})) for key in self.keys
        ]


def prepare_run(
    session: DatasetSession,
    runtime: Runtime,
    *,
    connector: ConnectorName | None,
    column: str | None,
    country: str | None,
    step_id: str | None,
    consent: bool,
    fill: FillRequest | None = None,
) -> PreparedRun:
    """Check a lookup can go ahead and read the values it will ask about."""
    review.prepare(session)
    if step_id is not None:
        step = _existing_step(session.recipe, step_id)
        earlier = Recipe(steps=session.recipe.steps[: session.recipe.steps.index(step)])
        is_new = False
    else:
        earlier = session.recipe
        taken = plan_recipe(earlier, session.base_schema).output.names()
        step = _new_step(connector, column, country, fill, taken)
        is_new = True

    if not enabled(runtime, step.connector):
        raise ConnectorOffError
    if step.connector not in session.connectors_on:
        raise ConnectorInactiveError
    if not consent and step.connector not in session.connector_consent:
        raise ConsentRequiredError

    plan = plan_recipe(earlier, session.base_schema)
    source = plan.output.get(step.column)
    if source is None or source.kind not in LOOKUP_KINDS:
        raise StepValidationError(f'"{step.column}" can\'t be looked up at this point.', step.id)
    beside = []
    for name in step.context:
        found_column = plan.output.get(name)
        if found_column is None:
            raise StepValidationError(f'There\'s no column called "{name}" to go with it.', step.id)
        beside.append(found_column)

    sql, params = chain_sql(plan)
    ident = text_of(quote_ident(step.column), source.kind)
    # What most often sits beside each value, as text, to help tell values apart.
    extras = "".join(
        f", mode({trimmed(f'CAST({text_of(quote_ident(c.name), c.kind)} AS VARCHAR)')})"
        for c in beside
    )
    found = session.conn.execute(
        f"SELECT {match_key(ident)} AS k, any_value({trimmed(ident)}), count(*){extras} "
        f"FROM ({sql}) GROUP BY k HAVING k IS NOT NULL ORDER BY count(*) DESC, k",
        params,
    ).fetchall()

    session.connector_consent.add(step.connector)
    return PreparedRun(
        step=step,
        is_new=is_new,
        keys=[str(row[0]) for row in found],
        shown={str(row[0]): str(row[1]) for row in found},
        rows={str(row[0]): int(row[2]) for row in found},
        context={
            str(row[0]): {
                column.name: str(value)
                for column, value in zip(beside, row[3:], strict=True)
                if value is not None
            }
            for row in found
        },
    )


def _new_step(
    connector: ConnectorName | None,
    column: str | None,
    country: str | None,
    fill: FillRequest | None,
    taken: list[str],
) -> EnrichColumnStep:
    if connector == "ai_fill":
        if fill is None:
            raise StepValidationError("Say what the new column is and what it's based on.")
        try:
            return EnrichColumnStep(
                connector="ai_fill",
                column=fill.based_on,
                into=_free_names([fill.name], taken),
                instruction=fill.instruction,
                kind=fill.kind,
                choices=fill.choices,
                context=[name for name in fill.context if name != fill.based_on],
            )
        except ValidationError as error:
            raise StepValidationError("That column can't be filled in this way.") from error
    if connector is None or column is None:
        raise StepValidationError("Say which column to look up, and with which connector.")
    if connector == "postal_geocode" and (country or "").upper() not in POSTAL_BY_COUNTRY:
        raise StepValidationError("Choose which country these postal codes are from.")
    return EnrichColumnStep(
        connector=connector,
        column=column,
        into=_free_names(DEFAULT_NAMES[connector], taken),
        country=country if connector == "postal_geocode" else None,
    )


def answers_for(prepared: PreparedRun, runtime: Runtime) -> dict[str, LookupResult]:
    """Ask the outside service. The slow part: call it without holding the session lock."""
    if prepared.step.connector == "ai_fill":
        return fill_values(prepared.fill_spec(), prepared.fill_items(), runtime)
    return look_up(prepared.step.connector, prepared.keys, prepared.step.country, runtime)


class FillPreviewRow(BaseModel):
    value: str
    # None when the model wasn't sure or couldn't be reached; `reason` says which.
    answer: str | None = None
    reason: str | None = None


class FillPreview(BaseModel):
    rows: list[FillPreviewRow]
    # How many different values a full fill would send.
    total_values: int


def preview_answers(prepared: PreparedRun, runtime: Runtime) -> FillPreview:
    """Fill in the first few values only, so the user can judge before filling them all.

    Adds nothing to the table. The answers are remembered, so the full fill
    doesn't pay for them again.
    """
    items = prepared.fill_items()[:PREVIEW_VALUES]
    results = fill_values(prepared.fill_spec(), items, runtime, limit=PREVIEW_VALUES)
    rows = []
    for item in items:
        result = results[item.key]
        found = result.status is Status.FOUND
        rows.append(
            FillPreviewRow(
                value=item.shown,
                answer=result.value1 if found else None,
                reason=None if found else REASONS[result.status],
            )
        )
    return FillPreview(rows=rows, total_values=len(prepared.keys))


def finish_run(
    session: DatasetSession, prepared: PreparedRun, results: dict[str, LookupResult]
) -> None:
    """Store the answers as a new snapshot and point the recipe at it."""
    snapshot = new_step_id()
    rows = [
        (
            snapshot,
            key,
            prepared.shown.get(key, key),
            # A reason, never a guess: only a found value fills a cell.
            result.value1 if result.status is Status.FOUND else None,
            result.value2 if result.status in (Status.FOUND, Status.AMBIGUOUS) else None,
            result.status.value,
            result.fetched_at,
        )
        for key, result in results.items()
    ]
    if rows:
        session.conn.executemany(
            f"INSERT INTO {ENRICHMENTS_REF} VALUES (?, ?, ?, ?, ?, ?, ?)", rows
        )
    step = prepared.step.model_copy(update={"snapshot": snapshot})
    if prepared.is_new:
        edit = recipe_ops.add_step(session.recipe, session.history, step, session.base_schema)
    else:
        # The step may have been removed while the services were being asked.
        _existing_step(session.recipe, step.id)
        edit = recipe_ops.update_step(session.recipe, session.history, step, session.base_schema)
    session.recipe, session.history = edit.recipe, edit.history

    if step.connector == "company_ticker":
        _ask_about_matches(session, step, prepared, results)


def _existing_step(recipe: Recipe, step_id: str) -> EnrichColumnStep:
    for step in recipe.steps:
        if step.id == step_id and isinstance(step, EnrichColumnStep):
            return step
    raise StepNotFoundError(step_id)


def _free_names(wanted: list[str], taken: list[str]) -> list[str]:
    used = {name.casefold() for name in taken}
    names = []
    for name in wanted:
        candidate, number = name, 2
        while candidate.casefold() in used:
            candidate, number = f"{name} {number}", number + 1
        used.add(candidate.casefold())
        names.append(candidate)
    return names


def _ask_about_matches(
    session: DatasetSession,
    step: EnrichColumnStep,
    prepared: PreparedRun,
    results: dict[str, LookupResult],
) -> None:
    """Turn each name with several matches into a question. Never pick one silently."""
    into = step.into[0]
    ctx = DetectorContext(conn=session.conn, profile=session.profile, today=date.today())
    questions: list[Issue] = []
    for key in prepared.keys:
        result = results.get(key)
        if result is None or result.status is not Status.AMBIGUOUS:
            continue
        candidates = decode_candidates(result.value2)
        shown = prepared.shown.get(key, key)
        builder = IssueBuilder(ctx, DetectorName.CONNECTOR_MATCH, [step.column, into], f"m-{key}")
        choices = [
            builder.choice(
                company.ticker,
                company.ticker,
                company.title,
                [
                    builder.step(
                        ResolveMatchStep(
                            column=step.column, value=key, into=into, chosen=company.ticker
                        )
                    )
                ],
            )
            for company in candidates[:MAX_CANDIDATES]
        ]
        choices.append(builder.choice("none", "Leave it empty", "None of these is right.", []))
        more = len(candidates) - MAX_CANDIDATES
        extra = f" The first {MAX_CANDIDATES} are offered." if more > 0 else ""
        questions.append(
            builder.build(
                title=f'"{shown}" matches more than one listed company',
                explanation=(
                    f'There are {len(candidates)} stock symbols for this name, so "{into}" '
                    f"is left empty for it until you pick one.{extra}"
                ),
                affected_rows=prepared.rows.get(key, 0),
                tier=Tier.ASK,
                ask=AskQuestion(prompt=f'Which one is "{shown}"?', choices=choices),
                examples=[shown],
            )
        )
        if len(questions) == MAX_MATCH_QUESTIONS:
            break

    ours = {issue.id for issue in questions}
    kept = [
        issue
        for issue in session.issues or []
        if issue.id not in ours
        and not (
            issue.detector is DetectorName.CONNECTOR_MATCH and issue.columns == [step.column, into]
        )
    ]
    session.issues = [*kept, *questions]


# --- what the canvas shows about looked-up cells ----------------------------------------------


@dataclass(frozen=True)
class ColumnNotes:
    # Shown beside the column name, such as when its prices were true.
    label: str | None
    # One per preview row: why the cell is empty, or None when it isn't.
    reasons: list[str | None]


def canvas_notes(session: DatasetSession, runtime: Runtime, limit: int) -> dict[str, ColumnNotes]:
    """For each looked-up column in the cleaned table: its label and its empty cells' reasons."""
    assert session.applied is not None
    statuses = {outcome.step_id: outcome.status for outcome in session.applied.outcomes}
    present = {column.name: column.kind for column in session.applied.columns}
    notes: dict[str, ColumnNotes] = {}
    for step in session.recipe.steps:
        if not isinstance(step, EnrichColumnStep) or statuses.get(step.id) != StepStatus.APPLIED:
            continue
        kind = present.get(step.column)
        if kind not in LOOKUP_KINDS:
            continue
        assert kind is not None
        view = _enrichment_view(session, step, runtime)
        key = match_key(text_of("c." + quote_ident(step.column), kind))
        rows = session.conn.execute(
            f"SELECT (SELECT any_value(e.status) FROM {ENRICHMENTS_REF} AS e "
            f"WHERE e.snapshot = $snapshot AND e.key = {key}), {key} IS NULL "
            f"FROM {work_ref(CLEANED_TABLE)} AS c ORDER BY c._row_id LIMIT {int(limit)}",
            {"snapshot": step.snapshot},
        ).fetchall()
        reasons: list[str | None] = []
        for status, source_blank in rows:
            if source_blank or status == Status.FOUND.value:
                reasons.append(None)
            else:
                reasons.append(REASONS[Status(status)] if status else REASONS[Status.PENDING])
        for position, name in enumerate(step.into):
            label = f"Prices as of {view.as_of}" if position == 0 and view.as_of else None
            if step.connector == "ai_fill":
                label = AI_LABEL
            if label and view.out_of_date:
                label += ". Out of date: refresh them under Connectors"
            if name in present:
                notes[name] = ColumnNotes(label=label, reasons=reasons)
    return notes
