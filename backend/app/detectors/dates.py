"""Date columns: which formats read them, and whether month or day comes first."""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

from app.db import RAW_REF, ROW_ID_COLUMN, quote_ident
from app.detectors import copy
from app.detectors.base import DetectorContext, IssueBuilder, date_issue_id
from app.detectors.models import AskQuestion, DetectorName, Issue, Tier
from app.profile.models import PatternKind, PhysicalType, SemanticRole
from app.profile.patterns import DATE_FORMATS
from app.steps.models import ParseDateStep
from app.steps.schema import trimmed

# Formats are picked until they read this share of filled values.
COVERAGE_TARGET = 0.95
MAX_FORMATS = 5
# Columns longer than this have their date formats chosen on a sample this size.
COVER_SAMPLE_ROWS = 5000
# Above this share of unreadable values, a date fix needs review.
UNREADABLE_FOR_REVIEW = 0.05
# With conflicting evidence, one side must outnumber the other this much to be recommended.
CLEAR_MAJORITY = 10
DATE_STYLE_PATTERNS = (PatternKind.DATE_YEAR_FIRST, PatternKind.DATE_NUMERIC, PatternKind.DATE_TEXT)

MONTH_FIRST = {f for f in DATE_FORMATS if f.startswith(("%m", "%b", "%B"))}
DAY_FIRST = {f for f in DATE_FORMATS if f.startswith("%d")}

_PARTS = r"^([0-9]{1,2})[-/.]([0-9]{1,2})[-/.][0-9]{2,4}"


@dataclass(frozen=True)
class Evidence:
    column: str
    filled: int
    styles: int
    datetime_output: bool
    month_evidence: int  # second part over 12, so it must be the day
    day_evidence: int  # first part over 12
    numeric_ambiguous: int  # day/month values where both parts are 12 or less
    month_example: str | None
    day_example: str | None
    ambiguous_example: str | None
    # (formats, values they read) chosen when assuming month first, or day first
    month_cover: tuple[list[str], int]
    day_cover: tuple[list[str], int]


def gather(ctx: DetectorContext) -> list[Evidence]:
    found = []
    for column in ctx.columns_with_role(SemanticRole.DATE):
        t = trimmed(quote_ident(column.name))
        row = ctx.query(
            f"""
            WITH v AS (SELECT {t} AS t FROM {RAW_REF}),
            p AS (SELECT t,
                    TRY_CAST(regexp_extract(t, $parts, 1) AS INTEGER) AS a,
                    TRY_CAST(regexp_extract(t, $parts, 2) AS INTEGER) AS b
                  FROM v WHERE t IS NOT NULL)
            -- count_if answers NULL when nothing it looks at is true or false,
            -- which is what happens when no value has two numbers to compare.
            SELECT count(*),
              coalesce(count_if(b > 12 AND a <= 12), 0),
              coalesce(count_if(a > 12 AND b <= 12), 0),
              coalesce(count_if(a BETWEEN 1 AND 12 AND b BETWEEN 1 AND 12), 0),
              min(t) FILTER (WHERE b > 12 AND a <= 12),
              min(t) FILTER (WHERE a > 12 AND b <= 12),
              min(t) FILTER (WHERE a BETWEEN 1 AND 12 AND b BETWEEN 1 AND 12 AND a <> b)
            FROM p
            """,
            {"parts": _PARTS},
        )[0]
        styles = sum(
            1
            for pattern in column.patterns
            if pattern.kind in DATE_STYLE_PATTERNS and pattern.match_count > 0
        )
        found.append(
            Evidence(
                column=column.name,
                filled=int(row[0]),
                styles=max(styles, 1),
                datetime_output=column.physical_type is PhysicalType.DATETIME,
                month_evidence=int(row[1]),
                day_evidence=int(row[2]),
                numeric_ambiguous=int(row[3]),
                month_example=row[4],
                day_example=row[5],
                ambiguous_example=row[6],
                month_cover=_cover(ctx, t, [f for f in DATE_FORMATS if f not in DAY_FIRST]),
                day_cover=_cover(ctx, t, [f for f in DATE_FORMATS if f not in MONTH_FIRST]),
            )
        )
    return found


def _cover(ctx: DetectorContext, t: str, candidates: list[str]) -> tuple[list[str], int]:
    """Greedily pick formats that together read the most values.

    Trying every format against every value is the slow part, so on a long
    column the formats are chosen on an even sample of it, and how many values
    they read is then counted once over the whole column.
    """
    total = ctx.query(f"SELECT count(*) FROM {RAW_REF} WHERE {t} IS NOT NULL")[0][0]
    every = max(1, total // COVER_SAMPLE_ROWS)
    source = (
        RAW_REF
        if every == 1
        # Every n-th row, so each way of writing a date is seen wherever it sits in the file.
        else f"(SELECT * FROM {RAW_REF} WHERE {quote_ident(ROW_ID_COLUMN)} % {every} = 0)"
    )
    sampled = (
        total
        if every == 1
        else ctx.query(f"SELECT count(*) FROM {source} WHERE {t} IS NOT NULL")[0][0]
    )

    chosen: list[str] = []
    read = 0
    while len(chosen) < MAX_FORMATS and read < COVERAGE_TARGET * sampled:
        remaining = [f for f in candidates if f not in chosen]
        if not remaining:
            break
        unread = (
            " AND ".join(f"try_strptime({t}, $c{i}) IS NULL" for i in range(len(chosen))) or "TRUE"
        )
        params: dict[str, object] = {f"c{i}": fmt for i, fmt in enumerate(chosen)}
        params.update({f"f{i}": fmt for i, fmt in enumerate(remaining)})
        gains = ctx.query(
            "SELECT "
            + ", ".join(
                f"count_if(try_strptime({t}, $f{i}) IS NOT NULL AND {unread})"
                for i in range(len(remaining))
            )
            + f" FROM {source} WHERE {t} IS NOT NULL",
            params,
        )[0]
        best = max(range(len(remaining)), key=lambda i: (gains[i], -i))
        if gains[best] == 0:
            break
        chosen.append(remaining[best])
        read += int(gains[best])
    if every == 1 or not chosen:
        return chosen, read
    readable = " OR ".join(f"try_strptime({t}, $c{i}) IS NOT NULL" for i in range(len(chosen)))
    counted = ctx.query(
        f"SELECT count_if({readable}) FROM {RAW_REF} WHERE {t} IS NOT NULL",
        {f"c{i}": fmt for i, fmt in enumerate(chosen)},
    )[0][0]
    return chosen, int(counted)


def _parse(b: IssueBuilder, item: Evidence, formats: list[str]) -> ParseDateStep:
    output = "datetime" if item.datetime_output else "date"
    step = b.step(
        ParseDateStep.model_validate({"column": item.column, "formats": formats, "output": output})
    )
    assert isinstance(step, ParseDateStep)
    return step


def _example_reading(example: str, month_first: bool) -> str:
    """How "03/04/2024" reads under one order, e.g. "4 March 2024"."""
    a, b, year = (int(part) for part in example.replace("-", "/").replace(".", "/").split("/"))
    month, day = (a, b) if month_first else (b, a)
    year = year + 2000 if year < 100 else year
    date = dt.date(year, month, day)
    return f"{date.day} {date.strftime('%B')} {date.year}"


def decide(evidence: list[Evidence], ctx: DetectorContext) -> list[Issue]:
    issues = []
    for item in evidence:
        if item.filled == 0:
            continue
        b = IssueBuilder(ctx, DetectorName.DATES, [item.column], "read")
        assert b.id == date_issue_id(item.column)

        def parse(formats: list[str], b: IssueBuilder = b, item: Evidence = item) -> ParseDateStep:
            return _parse(b, item, formats)

        has_numeric = item.month_evidence + item.day_evidence + item.numeric_ambiguous > 0
        month_only = item.month_evidence > 0 and item.day_evidence == 0
        day_only = item.day_evidence > 0 and item.month_evidence == 0

        if has_numeric and not month_only and not day_only:
            asked = _ask_order(item, b, parse)
            if asked is not None:
                issues.append(asked)
            continue

        formats, read = item.day_cover if day_only else item.month_cover
        if not formats:
            continue
        unreadable = item.filled - read
        if month_only or day_only:
            order = "month" if month_only else "day"
            evidence_count = item.month_evidence if month_only else item.day_evidence
            example = item.month_example if month_only else item.day_example
            title, explanation = copy.dates_one_order(
                item.column, order, evidence_count, example, item.styles
            )
        else:
            title, explanation = copy.dates_plain(item.column, item.styles)
        tier = Tier.SAFE
        if unreadable:
            explanation += copy.dates_unreadable(unreadable)
        if unreadable > UNREADABLE_FOR_REVIEW * item.filled or item.styles > 1:
            tier = Tier.LIKELY
        issues.append(
            b.build(
                title=title,
                explanation=explanation,
                affected_rows=item.filled,
                tier=tier,
                steps=[parse(formats)],
                examples=[e for e in (item.month_example, item.day_example) if e],
            )
        )
    return issues


def _ask_order(
    item: Evidence, b: IssueBuilder, parse: Callable[[list[str]], ParseDateStep]
) -> Issue | None:
    if not item.month_cover[0] or not item.day_cover[0]:
        return None
    if item.month_evidence and item.day_evidence:
        assert item.month_example is not None
        assert item.day_example is not None
        title, explanation, prompt = copy.dates_conflicting(
            item.column,
            item.month_evidence,
            item.day_evidence,
            item.month_example,
            item.day_example,
        )
        recommend_month = item.month_evidence >= CLEAR_MAJORITY * item.day_evidence
        recommend_day = item.day_evidence >= CLEAR_MAJORITY * item.month_evidence
        example = item.month_example
    else:
        example = item.ambiguous_example or item.month_example or item.day_example or ""
        title, explanation, prompt = copy.dates_ambiguous(item.column, example)
        recommend_month = recommend_day = False

    if item.ambiguous_example:
        sample = item.ambiguous_example
        month_label = f'Month first ("{sample}" is {_example_reading(sample, True)})'
        day_label = f'Day first ("{sample}" is {_example_reading(sample, False)})'
    else:
        month_label, day_label = "Month first", "Day first"

    ask = AskQuestion(
        prompt=prompt,
        choices=[
            b.choice(
                "month",
                month_label,
                "Dates that only work day first are left blank.",
                [parse(item.month_cover[0])],
                recommended=recommend_month,
            ),
            b.choice(
                "day",
                day_label,
                "Dates that only work month first are left blank.",
                [parse(item.day_cover[0])],
                recommended=recommend_day,
            ),
        ],
    )
    return b.build(
        title=title,
        explanation=explanation,
        affected_rows=item.filled,
        tier=Tier.ASK,
        ask=ask,
        examples=[e for e in (item.ambiguous_example, item.month_example, item.day_example) if e],
    )


def run(ctx: DetectorContext) -> list[Issue]:
    return decide(gather(ctx), ctx)
