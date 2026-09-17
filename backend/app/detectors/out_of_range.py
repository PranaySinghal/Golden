"""Number values that sit far outside the rest: stray negatives, extremes, percentages over 100."""

from dataclasses import dataclass

from app.db import RAW_REF, quote_ident
from app.detectors import copy
from app.detectors.base import DetectorContext, IssueBuilder, reading_issue_id
from app.detectors.models import AskQuestion, DetectorName, Issue, Tier
from app.profile.models import PatternKind, SemanticRole
from app.steps.compile import compile_step
from app.steps.models import (
    CastNumberStep,
    ClearValuesStep,
    OutsideRangeCondition,
    SetAsideRowsStep,
)
from app.steps.schema import StageSchema

MIN_VALUES = 20
# Negatives are only suspicious when almost everything else is zero or more.
MAX_NEGATIVE_SHARE = 0.01
# Tukey's far-out fences: beyond 3 interquartile ranges from the middle half.
FENCE_IQRS = 3.0
MAX_FAR_SHARE = 0.01
PERCENT_SHARE = 0.8


@dataclass(frozen=True)
class Evidence:
    column: str
    values: int
    negatives: int
    negative_examples: list[str]
    low_fence: float | None
    high_fence: float | None
    far: int
    far_examples: list[str]
    is_percent: bool
    over_100: int
    over_100_examples: list[str]


def gather(ctx: DetectorContext) -> list[Evidence]:
    names = [c.name for c in ctx.profile.columns]
    found = []
    for column in ctx.columns_with_role(SemanticRole.MEASURE):
        # Read numbers exactly the way the cast_number fix will.
        cast = compile_step(
            CastNumberStep(column=column.name, allow_k_m_suffix=True),
            StageSchema.all_text(names),
            index=0,
            source=RAW_REF,
        )
        ident = quote_ident(column.name)
        q1, q3 = ctx.query(
            f"WITH c AS ({cast.kept.sql}) SELECT quantile_cont({ident}, 0.25), "
            f"quantile_cont({ident}, 0.75) FROM c",
            cast.kept.params,
        )[0]
        low = high = None
        if q1 is not None and q3 is not None and q3 > q1:
            low, high = q1 - FENCE_IQRS * (q3 - q1), q3 + FENCE_IQRS * (q3 - q1)
        far_check = "(n < $low OR n > $high)" if low is not None else "FALSE"
        params = dict(cast.kept.params)
        if low is not None:
            params.update({"low": low, "high": high})
        row = ctx.query(
            f"""
            WITH c AS ({cast.kept.sql}),
            j AS (SELECT c.{ident} AS n, r.{ident} AS text FROM c
                  JOIN {RAW_REF} AS r ON c._row_id = r._row_id WHERE c.{ident} IS NOT NULL)
            SELECT count(*), count_if(n < 0), list(text ORDER BY n) FILTER (WHERE n < 0),
              count_if({far_check}),
              list(text ORDER BY abs(n) DESC) FILTER (WHERE {far_check}),
              count_if(n > 100), list(text ORDER BY n DESC) FILTER (WHERE n > 100)
            FROM j
            """,
            params,
        )[0]
        is_percent = any(
            p.kind is PatternKind.PERCENT and p.match_rate >= PERCENT_SHARE for p in column.patterns
        )
        found.append(
            Evidence(
                column=column.name,
                values=int(row[0]),
                negatives=int(row[1]),
                negative_examples=list(row[2] or [])[:5],
                low_fence=low,
                high_fence=high,
                far=int(row[3]),
                far_examples=list(row[4] or [])[:5],
                is_percent=is_percent,
                over_100=int(row[5]),
                over_100_examples=list(row[6] or [])[:5],
            )
        )
    return found


def _ask(
    b: IssueBuilder,
    column: str,
    condition: OutsideRangeCondition,
    prompt: str,
    what: str,
) -> AskQuestion:
    return AskQuestion(
        prompt=prompt,
        choices=[
            b.choice(
                "keep",
                "Keep them",
                "Unusual isn't always wrong; leave these values as they are.",
                [],
                recommended=True,
            ),
            b.choice(
                "set_aside",
                "Set these rows aside",
                f"Rows with {what} are left out of every answer.",
                [b.step(SetAsideRowsStep(condition=condition))],
            ),
            b.choice(
                "clear",
                "Clear just these values",
                "The rest of each row still counts.",
                [b.step(ClearValuesStep(column=column, condition=condition))],
            ),
        ],
    )


def decide(evidence: list[Evidence], ctx: DetectorContext) -> list[Issue]:
    issues = []
    for item in evidence:
        if item.values < MIN_VALUES:
            continue
        requires = [reading_issue_id(item.column)]

        if 0 < item.negatives <= MAX_NEGATIVE_SHARE * item.values:
            b = IssueBuilder(ctx, DetectorName.OUT_OF_RANGE, [item.column], "negative")
            title, explanation, prompt = copy.out_of_range_negative(
                item.column, item.negatives, item.negative_examples
            )
            condition = OutsideRangeCondition(column=item.column, min=0)
            issues.append(
                b.build(
                    title=title,
                    explanation=explanation,
                    affected_rows=item.negatives,
                    tier=Tier.ASK,
                    ask=_ask(b, item.column, condition, prompt, "a negative value"),
                    examples=item.negative_examples,
                    requires=requires,
                )
            )

        if (
            item.low_fence is not None
            and item.high_fence is not None
            and 0 < item.far <= MAX_FAR_SHARE * item.values
        ):
            b = IssueBuilder(ctx, DetectorName.OUT_OF_RANGE, [item.column], "far")
            title, explanation, prompt = copy.out_of_range_far(
                item.column, item.far, item.far_examples
            )
            condition = OutsideRangeCondition(
                column=item.column, min=round(item.low_fence, 6), max=round(item.high_fence, 6)
            )
            issues.append(
                b.build(
                    title=title,
                    explanation=explanation,
                    affected_rows=item.far,
                    tier=Tier.ASK,
                    ask=_ask(b, item.column, condition, prompt, "an unusual value"),
                    examples=item.far_examples,
                    requires=requires,
                )
            )

        if item.is_percent and item.over_100:
            b = IssueBuilder(ctx, DetectorName.OUT_OF_RANGE, [item.column], "percent")
            title, explanation, prompt = copy.out_of_range_percent(
                item.column, item.over_100, item.over_100_examples
            )
            condition = OutsideRangeCondition(column=item.column, max=100)
            issues.append(
                b.build(
                    title=title,
                    explanation=explanation,
                    affected_rows=item.over_100,
                    tier=Tier.ASK,
                    ask=_ask(b, item.column, condition, prompt, "a value over 100%"),
                    examples=item.over_100_examples,
                    requires=requires,
                )
            )
    return issues


def run(ctx: DetectorContext) -> list[Issue]:
    return decide(gather(ctx), ctx)
