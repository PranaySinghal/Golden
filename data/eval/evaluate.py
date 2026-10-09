"""Score the app against the test files in make_files.py.

    cd backend && uv run python ../data/eval/evaluate.py --offline   # no keys, nothing sent
    cd backend && (set -a; source ../.env; set +a; uv run python ../data/eval/evaluate.py)

Offline checks what the rules and the column detection do on their own. With
the services in .env switched on it also runs real lookups and asks the model,
and scores what comes back against each file's answer key. That part sends the
test files' values out and costs a few cents.

Every step goes through the same code a browser request does: the dataset
store, `review`, and the connectors service.
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))
sys.path.insert(0, str(HERE))

from make_files import COMPANIES, FillCheck, Key, build  # noqa: E402

from app import review  # noqa: E402
from app.api.views import recipe_response  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.connectors import freshness, service  # noqa: E402
from app.connectors.ai_fill import FillItem, FillSpec, fill_values  # noqa: E402
from app.connectors.build import build_runtime  # noqa: E402
from app.connectors.cache import LookupCache  # noqa: E402
from app.connectors.models import Company, Status  # noqa: E402
from app.connectors.runner import COMPANY_LIST, Runtime  # noqa: E402
from app.db import quote_ident, work_ref  # noqa: E402
from app.detectors.models import Tier  # noqa: E402
from app.errors import AppError  # noqa: E402
from app.ingest.models import IngestOptions  # noqa: E402
from app.steps.apply import CLEANED_TABLE  # noqa: E402
from app.steps.schema import ValueKind  # noqa: E402
from app.store import DatasetSession, DatasetStore  # noqa: E402

# How far a looked-up position may be from the one we know, in degrees (about 25 km).
POSITION_TOLERANCE = 0.25


class StandInSymbols:
    """The companies list, when the real one isn't switched on. Offline and exact."""

    name = "stand_in"

    def companies(self) -> list[Company]:
        listed = [Company(ticker, name) for ticker, name, *_ in COMPANIES]
        # Two share classes under one name, so the "several matches" path is exercised.
        return [*listed, Company("GOOGL", "Alphabet Inc."), Company("GOOG", "Alphabet Inc.")]


@dataclass
class Score:
    filename: str
    rows: int = 0
    columns: int = 0
    seconds: dict[str, float] = field(default_factory=dict)
    header_ok: bool = True
    problems_found: list[str] = field(default_factory=list)
    problems_missed: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    offers: list[tuple[str, str]] = field(default_factory=list)
    offers_missed: list[tuple[str, str]] = field(default_factory=list)
    offers_on_traps: list[tuple[str, str]] = field(default_factory=list)
    offers_unexpected: list[tuple[str, str]] = field(default_factory=list)
    totals: dict[str, str] = field(default_factory=dict)
    rows_after: str = ""
    lookups: dict[str, str] = field(default_factory=dict)
    ai: dict[str, str] = field(default_factory=dict)
    fills: dict[str, dict[str, object]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def timed(score: Score, name: str, started: float) -> float:
    score.seconds[name] = round(time.perf_counter() - started, 2)
    return time.perf_counter()


def accept_everything(session: DatasetSession) -> None:
    """Take every rule-based suggestion; for a question, the recommended answer or "leave it"."""
    for issue in list(review.prepare(session)):
        if issue.source == "ai":
            continue
        try:
            if issue.tier is Tier.LIKELY:
                review.accept(session, issue.id)
            elif issue.tier is Tier.ASK and issue.ask is not None:
                # The recommended answer, else the one that changes nothing. A
                # question with neither is left unanswered, as a careful user would.
                choices = issue.ask.choices
                chosen = next((c for c in choices if c.recommended), None) or next(
                    (c for c in choices if not c.steps), None
                )
                if chosen is not None:
                    review.accept(session, issue.id, chosen.id)
        except AppError:
            # A fix that no longer fits once others ran. Not what is being scored here.
            continue


def score_offline(
    data: bytes, key: Key, store: DatasetStore, runtime: Runtime
) -> tuple[Score, DatasetSession]:
    """What the rules and the column detection make of one file, against its answer key."""
    score = Score(key.filename)
    started = time.perf_counter()
    session = store.create(key.filename, data, IngestOptions())
    started = timed(score, "read", started)
    score.rows, score.columns = session.profile.row_count, session.profile.column_count
    score.header_ok = session.ingest.header_detected == key.header
    names = [column.name for column in session.profile.columns]
    if key.columns is not None and names != key.columns:
        score.errors.append(f"column names not found; got {names}")

    issues = review.prepare(session)
    started = timed(score, "find problems", started)
    score.issues = [f"{issue.tier.value}: {issue.title}" for issue in review.ranked(session)]
    for problem in key.problems:
        hit = any(
            issue.detector.value in problem.detectors
            and (not problem.column or problem.column in issue.columns)
            for issue in issues
        )
        (score.problems_found if hit else score.problems_missed).append(problem.what)

    accept_everything(session)
    applied = recipe_response(session)
    review.compare_now(session)
    timed(score, "clean and compare", started)

    kinds = {column.name: column.kind for column in applied.columns}
    for column, wanted in key.totals.items():
        if kinds.get(column) is not ValueKind.NUMBER:
            score.totals[column] = (
                f"MISSED: still {kinds.get(column, 'missing')}, wanted {wanted:,.2f}"
            )
            continue
        got = session.conn.execute(
            f"SELECT sum({quote_ident(column)}) FROM {work_ref(CLEANED_TABLE)}"
        ).fetchone()
        total = float(got[0]) if got and got[0] is not None else 0.0
        ok = abs(total - wanted) < 0.01 * max(1.0, abs(wanted)) / 100
        score.totals[column] = f"{'ok' if ok else 'WRONG'}: {total:,.2f} (wanted {wanted:,.2f})"
    if key.rows_after_cleaning is not None:
        ok = applied.row_count == key.rows_after_cleaning
        score.rows_after = (
            f"{'ok' if ok else 'WRONG'}: {applied.row_count:,} (wanted {key.rows_after_cleaning:,})"
        )

    found = service.overview(session, runtime)
    score.offers = [(offer.connector, offer.column) for offer in found.offers]
    wanted_offers = {(c, column) for c, columns in key.offers.items() for column in columns}
    score.offers_missed = sorted(wanted_offers - set(score.offers))
    score.offers_on_traps = [offer for offer in score.offers if offer[1] in key.traps]
    score.offers_unexpected = [
        offer for offer in score.offers if offer not in wanted_offers and offer[1] not in key.traps
    ]
    return score, session


def run_lookup(session: DatasetSession, runtime: Runtime, **request: object) -> None:
    service.set_active(session, runtime, str(request["connector"]), True)
    prepared = service.prepare_run(
        session,
        runtime,
        connector=request["connector"],  # type: ignore[arg-type]
        column=request.get("column"),  # type: ignore[arg-type]
        country=request.get("country"),  # type: ignore[arg-type]
        step_id=None,
        consent=True,
    )
    results = service.answers_for(prepared, runtime)
    service.finish_run(session, prepared, results)
    recipe_response(session)


def counts(session: DatasetSession, runtime: Runtime, connector: str, column: str) -> str:
    for item in service.overview(session, runtime).enrichments:
        if item.connector == connector and item.column == column:
            return ", ".join(f"{count} {reason}" for reason, count in item.counts.items())
    return "nothing"


def score_lookups(score: Score, key: Key, session: DatasetSession, runtime: Runtime) -> None:
    for connector, column in list(score.offers):
        if not service.enabled(runtime, connector):
            score.lookups[f"{connector} on {column}"] = "service not set up"
            continue
        if column in key.traps:
            continue
        try:
            started = time.perf_counter()
            country = key.postal_country if connector == "postal_geocode" else None
            run_lookup(session, runtime, connector=connector, column=column, country=country)
            line = counts(session, runtime, connector, column)
            line += f" in {time.perf_counter() - started:.1f}s"
            if connector == "postal_geocode" and column in key.positions:
                line += "; " + check_positions(session, column, key.positions[column])
            if connector == "company_ticker":
                line += "; " + check_tickers(session, column)
            score.lookups[f"{connector} on {column}"] = line
        except AppError as error:
            score.lookups[f"{connector} on {column}"] = f"REFUSED: {error.message}"


def check_positions(
    session: DatasetSession, column: str, known: dict[str, tuple[float, float]]
) -> str:
    rows = session.conn.execute(
        f'SELECT DISTINCT upper(trim(CAST({quote_ident(column)} AS VARCHAR))), "Geolocation" '
        f"FROM {work_ref(CLEANED_TABLE)}"
    ).fetchall()
    got = {str(code): position for code, position in rows}
    right, wrong, missing = 0, [], []
    for code, (latitude, longitude) in known.items():
        position = got.get(code.upper())
        if not position:
            missing.append(code)
            continue
        found_lat, found_lon = (float(part) for part in str(position).split(","))
        near = (
            abs(found_lat - latitude) < POSITION_TOLERANCE
            and abs(found_lon - longitude) < POSITION_TOLERANCE
        )
        if near:
            right += 1
        else:
            wrong.append(f"{code}->{position}")
    text = f"positions right {right}/{len(known)}"
    if wrong:
        text += f", WRONG {wrong}"
    if missing:
        text += f", no answer for {missing}"
    return text


def check_tickers(session: DatasetSession, column: str) -> str:
    rows = session.conn.execute(
        f'SELECT {quote_ident(column)}, "Ticker", "Ticker 2" FROM {work_ref(CLEANED_TABLE)}'
    ).fetchall()
    right = sum(1 for _, real, found in rows if found == real)
    blank = sum(1 for _, _, found in rows if found is None)
    wrong = [(name, real, found) for name, real, found in rows if found not in (None, real)]
    text = f"tickers right {right}/{len(rows)}, blank {blank}"
    return text + (f", WRONG {wrong[:5]}" if wrong else "")


class _Heard(logging.Handler):
    """Keeps what the AI layer logs about fixes it turned away, and why."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if message.startswith(("ai fix rejected", "ai enhancement")):
            self.lines.append(message)


def score_ai(
    score: Score, key: Key, session: DatasetSession, settings: Settings, runtime: Runtime
) -> None:
    started = time.perf_counter()
    heard = _Heard()
    logger = logging.getLogger("tidylab.ai")
    logger.addHandler(heard)
    logger.setLevel(logging.INFO)
    try:
        enhancement = review.ai_enhancement(session, settings)
    finally:
        logger.removeHandler(heard)
    score.ai["fixes proposed"] = "; ".join(heard.lines) or "nothing logged"
    score.ai["status"] = f"{enhancement.status} in {time.perf_counter() - started:.1f}s"
    score.ai["fixes added"] = (
        "; ".join(f"{issue.title} ({issue.affected_rows} rows)" for issue in enhancement.added)
        or "none"
    )
    score.ai["wording improved"] = (
        f"{len(enhancement.issue_copy)} cards, {len(enhancement.question_labels)} questions"
    )
    score.ai["story"] = "written" if enhancement.story else "none"

    started = time.perf_counter()
    ideas = review.column_suggestions(session, settings)
    score.ai["column ideas"] = (
        f"{ideas.status} in {time.perf_counter() - started:.1f}s: "
        + "; ".join(
            f"{idea.name}"
            + (f" [fill: {idea.fill.kind} from {idea.fill.based_on}]" if idea.fill else "")
            + ("" if idea.source == "ai" else " (built-in)")
            for idea in ideas.suggestions
        )
    )
    score.ai["about"] = ideas.about or "none"

    present = {column.name for column in recipe_response(session).columns}
    for check in key.fills:
        if check.based_on not in present:
            score.fills[check.name] = {"skipped": f'no column called "{check.based_on}"'}
            continue
        score.fills[check.name] = score_fill(check, session, runtime)


def score_fill(check: FillCheck, session: DatasetSession, runtime: Runtime) -> dict[str, object]:
    """Ask the model to fill one column and compare every answer with the truth."""
    values = session.conn.execute(
        f"SELECT DISTINCT trim(CAST({quote_ident(check.based_on)} AS VARCHAR)) "
        f"FROM {work_ref(CLEANED_TABLE)} WHERE {quote_ident(check.based_on)} IS NOT NULL"
    ).fetchall()
    items = [FillItem(key=str(value).lower(), shown=str(value)) for (value,) in values]
    spec = FillSpec(check.name, check.instruction, check.kind, check.based_on, check.choices)
    started = time.perf_counter()
    results = fill_values(spec, items, runtime)
    truth = {value.strip().lower(): answers for value, answers in check.truth.items()}
    right = wrong = unsure = failed = unknown = 0
    mistakes = []
    for item in items:
        result = results[item.key]
        wanted = truth.get(item.key)
        if result.status is Status.NOT_SURE:
            unsure += 1
        elif result.status is not Status.FOUND:
            failed += 1
        elif wanted is None:
            unknown += 1
        elif _same(check, str(result.value1), wanted):
            right += 1
        else:
            wrong += 1
            mistakes.append(f"{item.shown} -> {result.value1} (wanted {sorted(wanted)[0]})")
    answered = right + wrong
    return {
        "values": len(items),
        "right": right,
        "wrong": wrong,
        "not sure": unsure,
        "failed": failed,
        "no truth": unknown,
        "accuracy of answers": f"{100 * right / answered:.0f}%" if answered else "n/a",
        "seconds": round(time.perf_counter() - started, 1),
        "mistakes": mistakes[:8],
    }


def _same(check: FillCheck, answer: str, wanted: set[str]) -> bool:
    got = answer.strip().lower()
    if check.kind == "website":
        got = got.removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")
    return got in wanted


def show(score: Score) -> None:
    print(f"\n=== {score.filename}  ({score.rows:,} rows x {score.columns} columns) ===")
    print("  time:", ", ".join(f"{name} {seconds}s" for name, seconds in score.seconds.items()))
    if not score.header_ok:
        print("  HEADER: guessed wrong about whether the first row is column names")
    found, missed = len(score.problems_found), len(score.problems_missed)
    if found + missed:
        print(f"  problems found: {found}/{found + missed}")
        for what in score.problems_missed:
            print(f"    MISSED: {what}")
    print(f"  cards shown: {len(score.issues)}")
    for issue in score.issues:
        print(f"    - {issue}")
    for column, line in score.totals.items():
        print(f"  total of {column}: {line}")
    if score.rows_after:
        print(f"  rows after cleaning: {score.rows_after}")
    print(f"  connector offers: {score.offers or 'none'}")
    for label, offers in (
        ("MISSED", score.offers_missed),
        ("ON A TRAP COLUMN", score.offers_on_traps),
        ("not expected", score.offers_unexpected),
    ):
        if offers:
            print(f"    {label}: {offers}")
    for name, line in score.lookups.items():
        print(f"  lookup {name}: {line}")
    for name, line in score.ai.items():
        print(f"  ai {name}: {line}")
    for name, result in score.fills.items():
        print(f"  ai fill {name}: {json.dumps(result, ensure_ascii=False)}")
    for error in score.errors:
        print(f"  ERROR: {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="send nothing anywhere")
    parser.add_argument("--only", help="part of a filename, to score one file")
    parser.add_argument("--cache", default="", help="a file to keep answers in between runs")
    args = parser.parse_args()

    settings = Settings() if args.offline else get_settings()
    runtime = build_runtime(settings, cache=LookupCache(args.cache))
    if runtime.symbols.name == "none":
        # The real list needs a contact string we don't have. Matching is scored
        # against the same companies the test file was built from.
        runtime.symbols = StandInSymbols()
    listed = (
        [{"ticker": c.ticker, "title": c.title} for c in runtime.symbols.companies()]
        if (runtime.symbols.name == "stand_in")
        else []
    )
    if listed:
        runtime.cache.put_document(COMPANY_LIST, json.dumps(listed), freshness.stamp(runtime.now()))
    store = DatasetStore(settings)
    print(
        "services:",
        {
            name: service.enabled(runtime, name)
            for name in ("postal_geocode", "company_ticker", "stock_price", "ai_fill")
        },
    )

    scores = []
    for data, key in build():
        if args.only and args.only not in key.filename:
            continue
        try:
            score, session = score_offline(data, key, store, runtime)
            if not args.offline:
                score_lookups(score, key, session, runtime)
                if settings.llm_enabled:
                    score_ai(score, key, session, settings, runtime)
        except Exception as error:
            score = Score(key.filename, errors=[f"{type(error).__name__}: {error}"])
        show(score)
        scores.append(score)
    store.close_all()

    found = sum(len(s.problems_found) for s in scores)
    total = found + sum(len(s.problems_missed) for s in scores)
    print("\n=== overall ===")
    print(f"  injected problems found: {found}/{total}")
    print(f"  offers on trap columns: {sum(len(s.offers_on_traps) for s in scores)}")
    print(f"  expected offers missed: {sum(len(s.offers_missed) for s in scores)}")
    print(f"  files that crashed: {sum(1 for s in scores if s.errors)}")


if __name__ == "__main__":
    main()
