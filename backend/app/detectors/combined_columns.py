"""One column holding two things joined by a separator ("DevOps-California")."""

from dataclasses import dataclass

from app.db import RAW_REF, quote_ident
from app.detectors import copy
from app.detectors.base import DetectorContext, IssueBuilder
from app.detectors.models import DetectorName, Issue, Tier
from app.profile import patterns
from app.profile.models import PatternKind, SemanticRole
from app.steps.models import SplitColumnStep
from app.steps.schema import trimmed

ROLES = (SemanticRole.CATEGORY, SemanticRole.TEXT)
MIN_SHARE = 0.9
MIN_PART_DISTINCT = 2
# Parts combine when their distinct counts multiply out to cover the column's.
MIN_COMBINATION_COVERAGE = 0.5
MAX_NUMERIC_PART_SHARE = 0.5


@dataclass(frozen=True)
class Evidence:
    column: str
    delimiter: str
    filled: int
    two_part: int
    distinct: int
    left_distinct: int
    right_distinct: int
    both_numeric: int
    example: str


def gather(ctx: DetectorContext) -> list[Evidence]:
    found = []
    for column in ctx.columns_with_role(*ROLES):
        delimited = [p for p in column.patterns if p.kind is PatternKind.DELIMITED and p.detail]
        for pattern in delimited:
            assert pattern.detail is not None
            ident = quote_ident(column.name)
            t = trimmed(ident)
            two = "regexp_full_match(t, $two)"
            left, right = "trim(split_part(t, $d, 1))", "trim(split_part(t, $d, 2))"
            row = ctx.query(
                f"""
                WITH f AS (SELECT {t} AS t FROM {RAW_REF} WHERE {t} IS NOT NULL)
                SELECT count(*), count_if({two}), count(DISTINCT t),
                  count(DISTINCT {left}) FILTER (WHERE {two}),
                  count(DISTINCT {right}) FILTER (WHERE {two}),
                  count_if({two} AND regexp_full_match({left}, $number)
                    AND regexp_full_match({right}, $number)),
                  min(t) FILTER (WHERE {two})
                FROM f
                """,
                {
                    "two": patterns.DELIMITERS[pattern.detail],
                    "d": pattern.detail,
                    "number": patterns.LENIENT_NUMBER,
                },
            )[0]
            found.append(
                Evidence(
                    column=column.name,
                    delimiter=pattern.detail,
                    filled=int(row[0]),
                    two_part=int(row[1]),
                    distinct=int(row[2]),
                    left_distinct=int(row[3]),
                    right_distinct=int(row[4]),
                    both_numeric=int(row[5]),
                    example=str(row[6]),
                )
            )
    return found


def part_names(column: str, delimiter: str, taken: set[str]) -> list[str]:
    """Name the new columns from the header when it splits the same way."""
    for separator in (delimiter, "_", " "):
        parts = [p.strip() for p in column.split(separator)]
        if len(parts) == 2 and all(parts) and not {p.casefold() for p in parts} & taken:
            return parts
    return [f"{column} part 1", f"{column} part 2"]


def is_combined(item: Evidence) -> bool:
    return (
        item.filled > 0
        and item.two_part >= MIN_SHARE * item.filled
        and item.left_distinct >= MIN_PART_DISTINCT
        and item.right_distinct >= MIN_PART_DISTINCT
        and item.left_distinct < item.distinct
        and item.right_distinct < item.distinct
        and item.left_distinct * item.right_distinct >= MIN_COMBINATION_COVERAGE * item.distinct
        and item.both_numeric <= MAX_NUMERIC_PART_SHARE * item.two_part
    )


def decide(evidence: list[Evidence], ctx: DetectorContext) -> list[Issue]:
    issues = []
    taken = {c.name.casefold() for c in ctx.profile.columns}
    done: set[str] = set()
    for item in evidence:
        if item.column in done or not is_combined(item):
            continue
        done.add(item.column)
        names = part_names(item.column, item.delimiter, taken)
        if {n.casefold() for n in names} & taken:
            continue
        taken.update(n.casefold() for n in names)
        b = IssueBuilder(ctx, DetectorName.COMBINED_COLUMNS, [item.column], "split")
        # The original goes only when every value splits cleanly; one that
        # doesn't would otherwise lose the only place its whole text is shown.
        replaces = item.two_part == item.filled
        step = b.step(
            SplitColumnStep(
                column=item.column,
                delimiter=item.delimiter,
                into=names,
                keep_original=not replaces,
            )
        )
        title, explanation = copy.combined_column(
            item.column, item.delimiter, item.example, names, replaces
        )
        issues.append(
            b.build(
                title=title,
                explanation=explanation,
                affected_rows=item.two_part,
                tier=Tier.LIKELY,
                steps=[step],
                examples=[item.example],
            )
        )
    return issues


def run(ctx: DetectorContext) -> list[Issue]:
    return decide(gather(ctx), ctx)
