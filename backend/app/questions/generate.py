"""Choose business questions for any table from its profile.

Questions come in a fixed priority so the most prominent ones survive the cap:
the row count, distinct IDs, the average and total of each number column, a few
breakdowns and trends, then more breakdowns if there's room.
"""

import datetime as dt

import duckdb

from app.db import RAW_REF, quote_ident
from app.profile.models import ColumnProfile, DatasetProfile, PatternKind, SemanticRole
from app.profile.patterns import DATE_FORMATS
from app.questions import copy
from app.questions.models import DateGrain, Measure, Question
from app.steps.schema import match_key

MAX_QUESTIONS = 16

HEADLINE = 1.0
MEASURE = 0.8
BREAKDOWN = 0.6
TREND = 0.5
OTHER = 0.4

# Breakdowns only make sense for a handful of groups, counted once spelling
# differences are ignored (a messy column with 26 spellings of 3 values counts).
MIN_GROUPS, MAX_GROUPS = 2, 25
FIRST_BREAKDOWNS = 3
FIRST_AVERAGE_BREAKDOWNS = 2
MONTHLY_UP_TO_MONTHS = 24


def generate_questions(
    conn: duckdb.DuckDBPyConnection, profile: DatasetProfile, limit: int = MAX_QUESTIONS
) -> list[Question]:
    columns = [c for c in profile.columns if c.non_blank_count > 0]

    def by_role(role: SemanticRole) -> list[ColumnProfile]:
        # Fuller columns first, then file order.
        chosen = [c for c in columns if c.semantic_role is role]
        return sorted(chosen, key=lambda c: (-c.fill_rate, c.position))

    measures = by_role(SemanticRole.MEASURE)
    top_measure = measures[0].name if measures else None
    categories = [c for c in by_role(SemanticRole.CATEGORY) if _groups_fit(conn, c)]
    dates = by_role(SemanticRole.DATE)

    core: list[Question] = [Question(measure=Measure.COUNT, label=copy.rows(), prominence=HEADLINE)]
    core += [
        Question(
            measure=Measure.COUNT_DISTINCT,
            column=c.name,
            label=copy.distinct(c.name),
            prominence=HEADLINE,
        )
        for c in by_role(SemanticRole.IDENTIFIER)
    ]
    for c in measures:
        core.append(
            Question(
                measure=Measure.AVG, column=c.name, label=copy.average(c.name), prominence=MEASURE
            )
        )
        if not _is_percent(c):
            core.append(
                Question(
                    measure=Measure.SUM, column=c.name, label=copy.total(c.name), prominence=MEASURE
                )
            )

    extra: list[Question] = []
    for index, c in enumerate(categories):
        target = core if index < FIRST_BREAKDOWNS else extra
        target.append(
            Question(
                measure=Measure.COUNT,
                group_by=c.name,
                label=copy.rows_by(c.name),
                prominence=BREAKDOWN,
            )
        )
    if top_measure:
        for index, c in enumerate(categories):
            target = core if index < FIRST_AVERAGE_BREAKDOWNS else extra
            target.append(
                Question(
                    measure=Measure.AVG,
                    column=top_measure,
                    group_by=c.name,
                    label=copy.average_by(top_measure, c.name),
                    prominence=BREAKDOWN,
                )
            )

    for c in dates:
        grain = _grain(conn, c)
        core.append(
            Question(
                measure=Measure.COUNT,
                group_by=c.name,
                grain=grain,
                label=copy.rows_over_time(c.name, grain),
                prominence=TREND,
            )
        )
        if top_measure:
            core.append(
                Question(
                    measure=Measure.AVG,
                    column=top_measure,
                    group_by=c.name,
                    grain=grain,
                    label=copy.average_over_time(top_measure, c.name, grain),
                    prominence=TREND,
                )
            )

    core += [
        Question(
            measure=Measure.COUNT_DISTINCT,
            column=c.name,
            label=copy.distinct(c.name),
            prominence=OTHER,
        )
        for c in by_role(SemanticRole.CONTACT)
    ]
    unique = list({q.id: q for q in [*core, *extra]}.values())
    return unique[:limit]


def _is_percent(column: ColumnProfile) -> bool:
    return any(p.kind is PatternKind.PERCENT and p.match_rate >= 0.5 for p in column.patterns)


def _groups_fit(conn: duckdb.DuckDBPyConnection, column: ColumnProfile) -> bool:
    if column.distinct_count < MIN_GROUPS:
        return False
    key = match_key(quote_ident(column.name))
    row = conn.execute(f"SELECT count(DISTINCT {key}) FROM {RAW_REF}").fetchone()
    groups = int(row[0]) if row else 0
    return MIN_GROUPS <= groups <= MAX_GROUPS


def _grain(conn: duckdb.DuckDBPyConnection, column: ColumnProfile) -> DateGrain:
    earliest, latest = column.min_value, column.max_value
    if earliest is None or latest is None:
        formats = ", ".join(f"'{fmt}'" for fmt in DATE_FORMATS)
        ident = quote_ident(column.name)
        row = conn.execute(
            f"SELECT CAST(min(d) AS VARCHAR), CAST(max(d) AS VARCHAR) FROM "
            f"(SELECT try_strptime(trim({ident}), [{formats}]) AS d FROM {RAW_REF})"
        ).fetchone()
        earliest, latest = (row[0], row[1]) if row else (None, None)
    if earliest is None or latest is None:
        return DateGrain.YEAR
    start = dt.date.fromisoformat(str(earliest)[:10])
    end = dt.date.fromisoformat(str(latest)[:10])
    months = (end.year - start.year) * 12 + end.month - start.month
    return DateGrain.MONTH if months <= MONTHLY_UP_TO_MONTHS else DateGrain.YEAR
