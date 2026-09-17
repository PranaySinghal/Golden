"""Email addresses and phone numbers that don't look right."""

from dataclasses import dataclass

from app.db import RAW_REF, quote_ident
from app.detectors import copy
from app.detectors.base import DetectorContext, IssueBuilder
from app.detectors.models import AskQuestion, DetectorName, Issue, Tier
from app.profile import patterns
from app.profile.models import PatternKind, SemanticRole
from app.steps.models import (
    ClearValuesStep,
    DigitsFewerThanCondition,
    NotMatchingCondition,
    RemoveCharactersStep,
    RowCondition,
    SetAsideRowsStep,
)
from app.steps.schema import trimmed

FORMAT_SHARE = 0.8
# A stray "-" is only a pattern worth fixing when it's common in the column.
STRAY_MINUS_SHARE = 0.5
# "Short" only means something when most numbers share one length.
USUAL_LENGTH_SHARE = 0.8


@dataclass(frozen=True)
class Evidence:
    column: str
    kind: str  # "email" or "phone"
    filled: int
    invalid_emails: int
    invalid_examples: list[str]
    stray_minus: int
    minus_examples: list[str]
    usual_length: int | None
    usual_length_count: int
    short: int
    short_examples: list[str]


def _kind(column_patterns: list[tuple[PatternKind, float]]) -> str | None:
    rates = dict(column_patterns)
    if rates.get(PatternKind.EMAIL, 0.0) >= FORMAT_SHARE:
        return "email"
    if rates.get(PatternKind.PHONE, 0.0) >= FORMAT_SHARE:
        return "phone"
    return None


def gather(ctx: DetectorContext) -> list[Evidence]:
    found = []
    for column in ctx.columns_with_role(SemanticRole.CONTACT):
        kind = _kind([(p.kind, p.match_rate) for p in column.patterns])
        if kind is None:
            continue
        t = trimmed(quote_ident(column.name))
        digits = f"length(regexp_replace({t}, '[^0-9]', '', 'g'))"
        row = ctx.query(
            f"""
            WITH f AS (SELECT {t} AS t, {digits} AS d FROM {RAW_REF} WHERE {t} IS NOT NULL)
            SELECT count(*),
              count_if(NOT regexp_full_match(t, $email)),
              list(t ORDER BY t) FILTER (WHERE NOT regexp_full_match(t, $email)),
              count_if(regexp_full_match(t, '-[0-9].*')),
              list(t ORDER BY t) FILTER (WHERE regexp_full_match(t, '-[0-9].*'))
            FROM f
            """,
            {"email": patterns.EMAIL},
        )[0]
        lengths = ctx.query(
            f"SELECT {digits} AS d, count(*) FROM {RAW_REF} WHERE {t} IS NOT NULL "
            "GROUP BY d ORDER BY count(*) DESC, d DESC LIMIT 1"
        )
        usual, usual_count = (int(lengths[0][0]), int(lengths[0][1])) if lengths else (None, 0)
        short = ctx.query(
            f"SELECT count(*), list(t ORDER BY d, t) FROM "
            f"(SELECT {t} AS t, {digits} AS d FROM {RAW_REF} WHERE {t} IS NOT NULL) "
            "WHERE d < $usual",
            {"usual": usual or 0},
        )[0]
        found.append(
            Evidence(
                column=column.name,
                kind=kind,
                filled=int(row[0]),
                invalid_emails=int(row[1]) if kind == "email" else 0,
                invalid_examples=list(row[2] or [])[:5],
                stray_minus=int(row[3]) if kind == "phone" else 0,
                minus_examples=list(row[4] or [])[:5],
                usual_length=usual,
                usual_length_count=usual_count,
                short=int(short[0]) if kind == "phone" else 0,
                short_examples=list(short[1] or [])[:5],
            )
        )
    return found


def _fix_choices(b: IssueBuilder, column: str, condition: RowCondition, prompt: str) -> AskQuestion:
    return AskQuestion(
        prompt=prompt,
        choices=[
            b.choice(
                "clear",
                "Clear them",
                "Leave these blank; the rest of each row still counts.",
                [b.step(ClearValuesStep(column=column, condition=condition))],
                recommended=True,
            ),
            b.choice(
                "set_aside",
                "Set these rows aside",
                "Leave the whole row out of every answer.",
                [b.step(SetAsideRowsStep(condition=condition))],
            ),
            b.choice("keep", "Keep them", "Leave the values as they are.", []),
        ],
    )


def decide(evidence: list[Evidence], ctx: DetectorContext) -> list[Issue]:
    issues = []
    for item in evidence:
        if item.kind == "email" and item.invalid_emails:
            b = IssueBuilder(ctx, DetectorName.CONTACT_FORMATS, [item.column], "email")
            title, explanation, prompt = copy.invalid_emails(
                item.column, item.invalid_emails, item.invalid_examples
            )
            condition = NotMatchingCondition(column=item.column, pattern="email")
            issues.append(
                b.build(
                    title=title,
                    explanation=explanation,
                    affected_rows=item.invalid_emails,
                    tier=Tier.ASK,
                    ask=_fix_choices(b, item.column, condition, prompt),
                    examples=item.invalid_examples,
                )
            )

        if item.kind != "phone" or not item.filled:
            continue
        if item.stray_minus >= STRAY_MINUS_SHARE * item.filled:
            b = IssueBuilder(ctx, DetectorName.CONTACT_FORMATS, [item.column], "minus")
            title, explanation = copy.stray_minus(
                item.column, item.stray_minus, item.minus_examples
            )
            issues.append(
                b.build(
                    title=title,
                    explanation=explanation,
                    affected_rows=item.stray_minus,
                    tier=Tier.LIKELY,
                    steps=[
                        b.step(
                            RemoveCharactersStep(
                                columns=[item.column], characters="-", where="leading"
                            )
                        )
                    ],
                    examples=item.minus_examples,
                )
            )
        if (
            item.usual_length is not None
            and item.short
            and item.usual_length_count >= USUAL_LENGTH_SHARE * item.filled
        ):
            b = IssueBuilder(ctx, DetectorName.CONTACT_FORMATS, [item.column], "short")
            title, explanation, prompt = copy.short_phones(
                item.column, item.short, item.usual_length, item.short_examples
            )
            too_short = DigitsFewerThanCondition(column=item.column, count=item.usual_length)
            issues.append(
                b.build(
                    title=title,
                    explanation=explanation,
                    affected_rows=item.short,
                    tier=Tier.ASK,
                    ask=_fix_choices(b, item.column, too_short, prompt),
                    examples=item.short_examples,
                )
            )
    return issues


def run(ctx: DetectorContext) -> list[Issue]:
    return decide(gather(ctx), ctx)
