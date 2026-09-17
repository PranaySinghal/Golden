"""Rows that repeat an earlier row, exactly or apart from capitals and spaces."""

from dataclasses import dataclass

from app.db import RAW_REF, quote_ident
from app.detectors import copy
from app.detectors.base import DetectorContext, IssueBuilder
from app.detectors.models import DetectorName, Issue, Tier
from app.profile.models import SemanticRole
from app.steps.models import DedupeStep
from app.steps.schema import match_key


@dataclass(frozen=True)
class Evidence:
    exact_extra: int  # rows beyond the first of each exact repeat
    loose_extra: int  # same, ignoring capitals and spaces (includes exact)
    has_identifier: bool


def _extra_rows(ctx: DetectorContext, keys: list[str]) -> int:
    row = ctx.query(
        f"SELECT coalesce(sum(n - 1), 0) FROM "
        f"(SELECT count(*) AS n FROM {RAW_REF} GROUP BY {', '.join(keys)} HAVING n > 1)"
    )
    return int(row[0][0])


def gather(ctx: DetectorContext) -> Evidence:
    names = [c.name for c in ctx.profile.columns]
    if not names or ctx.row_count < 2:
        return Evidence(0, 0, False)
    exact = _extra_rows(ctx, [quote_ident(n) for n in names])
    loose = _extra_rows(ctx, [match_key(quote_ident(n)) for n in names])
    has_identifier = any(c.semantic_role is SemanticRole.IDENTIFIER for c in ctx.profile.columns)
    return Evidence(exact, loose, has_identifier)


def decide(evidence: Evidence, ctx: DetectorContext) -> list[Issue]:
    issues = []
    if evidence.exact_extra:
        b = IssueBuilder(ctx, DetectorName.DUPLICATES, [], "exact")
        title, explanation = copy.exact_repeats(evidence.exact_extra, evidence.has_identifier)
        issues.append(
            b.build(
                title=title,
                explanation=explanation,
                affected_rows=evidence.exact_extra,
                # Identical rows including their ID are certainly repeats; without an
                # ID column they could be genuine (two identical purchases).
                tier=Tier.SAFE if evidence.has_identifier else Tier.LIKELY,
                steps=[b.step(DedupeStep())],
            )
        )
    near = evidence.loose_extra - evidence.exact_extra
    if near > 0:
        b = IssueBuilder(ctx, DetectorName.DUPLICATES, [], "near")
        title, explanation = copy.near_repeats(near)
        issues.append(
            b.build(
                title=title,
                explanation=explanation,
                affected_rows=near,
                tier=Tier.LIKELY,
                steps=[b.step(DedupeStep(match="ignore_case_and_spaces"))],
            )
        )
    return issues


def run(ctx: DetectorContext) -> list[Issue]:
    return decide(gather(ctx), ctx)
