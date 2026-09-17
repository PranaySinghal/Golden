"""Text standing in for a missing value ("N/A", "-", "unknown")."""

from dataclasses import dataclass

from app.db import RAW_REF, quote_ident
from app.detectors import copy
from app.detectors.base import DetectorContext, IssueBuilder
from app.detectors.models import AskQuestion, DetectorName, Issue, Tier
from app.profile import patterns
from app.profile.models import SemanticRole
from app.steps.models import MapValuesStep, NullPlaceholdersStep, ValueMapping
from app.steps.schema import normalize_text, trimmed

ROLES = (SemanticRole.MEASURE, SemanticRole.DATE, SemanticRole.CATEGORY)
# A short all-capitals word like "NA" is a real code (North America) when most
# other values in the column are short all-capitals codes too.
CODE_SHAPE = r"[A-Z]{2,4}"
CODE_COLUMN_SHARE = 0.5


@dataclass(frozen=True)
class Evidence:
    column: str
    role: SemanticRole
    tokens: list[tuple[str, int]]  # placeholder text as written, with counts
    code_like_share: float  # share of other distinct values shaped like short codes


def gather(ctx: DetectorContext) -> list[Evidence]:
    found = []
    for column in ctx.columns_with_role(*ROLES):
        ident = quote_ident(column.name)
        t = trimmed(ident)
        tokens = ctx.query(
            f"SELECT {t} AS token, count(*) FROM {RAW_REF} "
            f"WHERE regexp_full_match({t}, $pattern) GROUP BY token ORDER BY count(*) DESC, token",
            {"pattern": patterns.PLACEHOLDER},
        )
        if not tokens:
            continue
        shares = ctx.query(
            f"SELECT count(DISTINCT {t}) FILTER (WHERE regexp_full_match({t}, $code)), "
            f"count(DISTINCT {t}) FROM {RAW_REF} "
            f"WHERE {t} IS NOT NULL AND NOT regexp_full_match({t}, $pattern)",
            {"code": CODE_SHAPE, "pattern": patterns.PLACEHOLDER},
        )[0]
        code_like = shares[0] / shares[1] if shares[1] else 0.0
        found.append(
            Evidence(
                column.name, column.semantic_role, [(str(a), int(b)) for a, b in tokens], code_like
            )
        )
    return found


def decide(evidence: list[Evidence], ctx: DetectorContext) -> list[Issue]:
    issues = []
    for item in evidence:
        tokens = [
            (token, n)
            for token, n in item.tokens
            if not (
                item.role is SemanticRole.CATEGORY
                and patterns.full_match(CODE_SHAPE, token)
                and item.code_like_share >= CODE_COLUMN_SHARE
            )
        ]
        if not tokens:
            continue
        # "N/A" and "n/a" are one placeholder; show the most common spelling.
        merged: dict[str, tuple[str, int]] = {}
        for token, n in tokens:
            key = normalize_text(token)
            spelling, total = merged.get(key, (token, 0))
            merged[key] = (spelling, total + n)
        words = [spelling for spelling, _ in merged.values()]
        affected = sum(n for _, n in tokens)
        b = IssueBuilder(ctx, DetectorName.PLACEHOLDERS, [item.column], "placeholders")
        clear = b.step(NullPlaceholdersStep(columns=[item.column], placeholders=words))

        if item.role is SemanticRole.MEASURE:
            title, explanation, prompt = copy.placeholders_in_numbers(item.column, affected, words)
            zero = b.step(
                MapValuesStep(
                    column=item.column,
                    match="ignore_case_and_spaces",
                    mappings=[ValueMapping(from_value=word, to_value="0") for word in words],
                )
            )
            ask = AskQuestion(
                prompt=prompt,
                choices=[
                    b.choice(
                        "missing",
                        "Missing",
                        "Leave them out of totals and averages.",
                        [clear],
                        recommended=True,
                    ),
                    b.choice("zero", "Zero", "Count them as 0, which lowers averages.", [zero]),
                ],
            )
            issues.append(
                b.build(
                    title=title,
                    explanation=explanation,
                    affected_rows=affected,
                    tier=Tier.ASK,
                    ask=ask,
                    examples=words,
                )
            )
        else:
            title, explanation = copy.placeholders_in_labels(item.column, affected, words)
            issues.append(
                b.build(
                    title=title,
                    explanation=explanation,
                    affected_rows=affected,
                    tier=Tier.LIKELY,
                    steps=[clear],
                    examples=words,
                )
            )
    return issues


def run(ctx: DetectorContext) -> list[Issue]:
    return decide(gather(ctx), ctx)
