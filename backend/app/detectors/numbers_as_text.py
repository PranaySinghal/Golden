"""Number columns that need reading as numbers ("$1,299.00", "12%", "$85k", or plain)."""

from dataclasses import dataclass
from typing import Literal

from app.db import RAW_REF, quote_ident
from app.detectors import copy
from app.detectors.base import DetectorContext, IssueBuilder, reading_issue_id
from app.detectors.models import AskQuestion, DetectorName, Issue, Tier
from app.profile import patterns
from app.profile.models import SemanticRole
from app.steps.compile import number_pattern
from app.steps.models import CastNumberStep
from app.steps.schema import trimmed

# "1.200,50" or "3,5": a comma followed by one or two digits at the end is a decimal comma.
DECIMAL_COMMA = r"[-+(]?[$€£¥₹]?\s?[0-9.]*[0-9],[0-9]{1,2}\s?[$€£¥₹]?\s?%?\)?"
# "1,200.50": a comma before a later point means the point is the decimal mark.
DECIMAL_POINT = r"[-+(]?[$€£¥₹]?\s?[0-9,]*[0-9]\.[0-9]+\s?[$€£¥₹]?\s?%?\)?"
MAX_EXAMPLES = 5
# Columns the profile calls labels can still be numbers written with decimal
# commas ("3,50"), which the profile's number pattern doesn't read.
NUMBER_LIKE_SHARE = 0.8


@dataclass(frozen=True)
class Evidence:
    column: str
    is_measure: bool
    filled: int
    readable: int  # values that read as numbers with either decimal mark
    not_plain: int  # readable only with formatting removed
    with_suffix: int  # need "k" or "M"
    decimal_comma: int
    decimal_point: int
    examples: list[str]
    suffix_examples: list[str]
    comma_examples: list[str]


def gather(ctx: DetectorContext) -> list[Evidence]:
    found = []
    roles = (
        SemanticRole.MEASURE,
        SemanticRole.CATEGORY,
        SemanticRole.TEXT,
        SemanticRole.IDENTIFIER,
    )
    for column in ctx.columns_with_role(*roles):
        t = trimmed(quote_ident(column.name))
        params = {
            "plain": patterns.PLAIN_NUMBER,
            "dot": number_pattern(".", False),
            "dot_suffix": number_pattern(".", True),
            "comma": number_pattern(",", False),
            "decimal_comma": DECIMAL_COMMA,
            "decimal_point": DECIMAL_POINT,
            "placeholder": patterns.PLACEHOLDER,
        }
        row = ctx.query(
            f"""
            WITH v AS (SELECT {t} AS t FROM {RAW_REF}),
            f AS (SELECT t FROM v WHERE t IS NOT NULL AND NOT regexp_full_match(t, $placeholder))
            SELECT
              count(*),
              count_if(regexp_full_match(t, $dot) OR regexp_full_match(t, $comma)
                       OR regexp_full_match(t, $dot_suffix)),
              count_if((regexp_full_match(t, $dot) OR regexp_full_match(t, $comma))
                       AND NOT regexp_full_match(t, $plain)),
              count_if(regexp_full_match(t, $dot_suffix) AND NOT regexp_full_match(t, $dot)),
              count_if(regexp_full_match(t, $decimal_comma)),
              count_if(regexp_full_match(t, $decimal_point) AND regexp_matches(t, ',')),
              list(t ORDER BY t) FILTER (WHERE (regexp_full_match(t, $dot)
                  OR regexp_full_match(t, $dot_suffix)) AND NOT regexp_full_match(t, $plain)),
              list(t ORDER BY t) FILTER (WHERE regexp_full_match(t, $dot_suffix)
                  AND NOT regexp_full_match(t, $dot)),
              list(t ORDER BY t) FILTER (WHERE regexp_full_match(t, $decimal_comma))
            FROM f
            """,
            params,
        )[0]
        found.append(
            Evidence(
                column=column.name,
                is_measure=column.semantic_role is SemanticRole.MEASURE,
                filled=int(row[0]),
                readable=int(row[1]),
                not_plain=int(row[2]) + int(row[3]),
                with_suffix=int(row[3]),
                decimal_comma=int(row[4]),
                decimal_point=int(row[5]),
                examples=_distinct(row[6]),
                suffix_examples=_distinct(row[7]),
                comma_examples=_distinct(row[8]),
            )
        )
    return found


def _distinct(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(values or []))[:MAX_EXAMPLES]


def _cast(
    b: IssueBuilder, column: str, separator: Literal[".", ","], suffix: bool
) -> CastNumberStep:
    step = b.step(
        CastNumberStep(column=column, decimal_separator=separator, allow_k_m_suffix=suffix)
    )
    assert isinstance(step, CastNumberStep)
    return step


def decide(evidence: list[Evidence], ctx: DetectorContext) -> list[Issue]:
    issues = []
    for item in evidence:
        if item.filled == 0:
            continue
        number_like = item.decimal_comma and item.readable >= NUMBER_LIKE_SHARE * item.filled
        if not item.is_measure and not number_like:
            continue
        b = IssueBuilder(ctx, DetectorName.NUMBERS_AS_TEXT, [item.column], "read")
        assert b.id == reading_issue_id(item.column)
        suffix = item.with_suffix > 0
        if item.decimal_comma and item.decimal_point:
            title, explanation, prompt = copy.decimal_comma(item.column, item.comma_examples)
            ask = AskQuestion(
                prompt=prompt,
                choices=[
                    b.choice(
                        "thousands",
                        "Thousands",
                        'Read "1,200" as one thousand two hundred.',
                        [_cast(b, item.column, ".", suffix)],
                    ),
                    b.choice(
                        "decimals",
                        "Decimals",
                        'Read "3,5" as three and a half.',
                        [_cast(b, item.column, ",", suffix)],
                    ),
                ],
            )
            issues.append(
                b.build(
                    title=title,
                    explanation=explanation,
                    affected_rows=item.not_plain,
                    tier=Tier.ASK,
                    ask=ask,
                    examples=item.comma_examples,
                )
            )
            continue

        separator: Literal[".", ","] = "," if item.decimal_comma else "."
        title, explanation = copy.numbers_as_text(item.column, item.not_plain, item.examples)
        tier = Tier.SAFE
        if suffix:
            explanation = copy.numbers_with_suffix(item.column, item.suffix_examples)
            tier = Tier.LIKELY
        elif item.decimal_comma:
            tier = Tier.LIKELY
        issues.append(
            b.build(
                title=title,
                explanation=explanation,
                affected_rows=item.not_plain,
                tier=tier,
                steps=[_cast(b, item.column, separator, suffix)],
                examples=item.suffix_examples or item.examples,
            )
        )
    return issues


def run(ctx: DetectorContext) -> list[Issue]:
    return decide(gather(ctx), ctx)
