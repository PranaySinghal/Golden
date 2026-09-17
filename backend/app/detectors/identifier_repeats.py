"""ID or contact values that appear on more than one row."""

from dataclasses import dataclass

from app.db import RAW_REF, quote_ident
from app.detectors import copy
from app.detectors.base import DetectorContext, IssueBuilder
from app.detectors.models import AskQuestion, DetectorName, Issue, Tier
from app.profile.models import SemanticRole
from app.steps.models import DedupeStep
from app.steps.schema import trimmed

ROLES = (SemanticRole.IDENTIFIER, SemanticRole.CONTACT)
# A few repeats among mostly unique values look like mistakes...
MOSTLY_UNIQUE = 0.9
# ...while values shared by many rows look intentional.
WIDELY_SHARED = 0.5


@dataclass(frozen=True)
class Evidence:
    column: str
    role: SemanticRole
    filled: int
    distinct: int
    repeated_values: int
    rows_involved: int
    examples: list[str]


def gather(ctx: DetectorContext) -> list[Evidence]:
    names = [quote_ident(c.name) for c in ctx.profile.columns]
    found = []
    for column in ctx.columns_with_role(*ROLES):
        t = trimmed(quote_ident(column.name))
        # Fully identical rows are the duplicates detector's job, so count distinct rows.
        row = ctx.query(
            f"""
            WITH d AS (SELECT DISTINCT {", ".join(names)} FROM {RAW_REF}),
            g AS (SELECT {t} AS v, count(*) AS n FROM d WHERE {t} IS NOT NULL GROUP BY v)
            SELECT coalesce(sum(n), 0), count(*), count_if(n > 1),
              coalesce(sum(n) FILTER (WHERE n > 1), 0),
              list(v ORDER BY n DESC, v) FILTER (WHERE n > 1)
            FROM g
            """
        )[0]
        found.append(
            Evidence(
                column=column.name,
                role=column.semantic_role,
                filled=int(row[0]),
                distinct=int(row[1]),
                repeated_values=int(row[2]),
                rows_involved=int(row[3]),
                examples=list(row[4] or [])[:5],
            )
        )
    return found


def decide(evidence: list[Evidence], ctx: DetectorContext) -> list[Issue]:
    issues = []
    for item in evidence:
        if not item.repeated_values:
            continue
        contact = item.role is SemanticRole.CONTACT
        uniqueness = item.distinct / item.filled
        b = IssueBuilder(ctx, DetectorName.IDENTIFIER_REPEATS, [item.column], "repeats")
        title, explanation, prompt = copy.identifier_repeats(
            item.column, item.repeated_values, item.rows_involved, contact, item.examples
        )
        ask = AskQuestion(
            prompt=prompt,
            choices=[
                b.choice(
                    "first",
                    "Yes, keep the first row for each",
                    "Later rows with the same value are set aside.",
                    [b.step(DedupeStep(columns=[item.column], match="ignore_case_and_spaces"))],
                    recommended=uniqueness >= MOSTLY_UNIQUE,
                ),
                b.choice(
                    "last",
                    "Yes, keep the last row for each",
                    "Earlier rows with the same value are set aside.",
                    [
                        b.step(
                            DedupeStep(
                                columns=[item.column], match="ignore_case_and_spaces", keep="last"
                            )
                        )
                    ],
                ),
                b.choice(
                    "shared",
                    "No, sharing is fine",
                    "Keep every row.",
                    [],
                    recommended=uniqueness < WIDELY_SHARED,
                ),
            ],
        )
        issues.append(
            b.build(
                title=title,
                explanation=explanation,
                affected_rows=item.rows_involved,
                tier=Tier.ASK,
                ask=ask,
                examples=item.examples,
            )
        )
    return issues


def run(ctx: DetectorContext) -> list[Issue]:
    return decide(gather(ctx), ctx)
