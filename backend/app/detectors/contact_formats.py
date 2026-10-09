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
    NormalizePhoneStep,
    NotMatchingCondition,
    RemoveCharactersStep,
    RowCondition,
    SetAsideRowsStep,
)
from app.steps.phone import DEFAULT_REGION, format_phone_or_original
from app.steps.schema import trimmed

FORMAT_SHARE = 0.8
MIXED_FORMAT_SHARE = 0.5
# A stray "-" is only a pattern worth fixing when it's common in the column.
STRAY_MINUS_SHARE = 0.5
# "Short" only means something when most numbers share one length.
USUAL_LENGTH_SHARE = 0.8
# A cap on how many distinct numbers get run through the phone library per
# column, purely to bound detection cost on a pathological file; the fix
# itself (a SQL function call) has no such limit once accepted.
MAX_PHONE_VALUES = 20_000
# Shown in the issue as a preview of what would change.
MAX_REFORMAT_EXAMPLES = 3


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
    # Numbers with fewer digits than this count as short.
    short_below: int
    # True when "short" is measured against the column's own usual length.
    against_usual: bool
    short_examples: list[str]
    reformat_count: int
    reformat_examples: list[tuple[str, str]]


def _kind(column_patterns: list[tuple[PatternKind, float]]) -> str | None:
    rates = dict(column_patterns)
    if rates.get(PatternKind.EMAIL, 0.0) >= FORMAT_SHARE:
        return "email"
    # The profile only calls a column contact info when it is emails or phone
    # numbers, so a column that isn't emails and is half formatted numbers is a
    # phone column written several ways (some with spacing, some bare digits).
    if rates.get(PatternKind.PHONE, 0.0) >= MIXED_FORMAT_SHARE:
        return "phone"
    return None


def _reformat_evidence(ctx: DetectorContext, t: str) -> tuple[int, list[tuple[str, str]]]:
    """How many rows would read differently once each number is written consistently.

    Values with a stray leading "-" are left to that check instead (it has its
    own, narrower fix); counting them here too would raise two issues, with
    two different proposed steps, for the same rows.
    """
    distinct = ctx.query(
        f"SELECT {t} AS t, count(*) FROM {RAW_REF} WHERE {t} IS NOT NULL "
        f"AND NOT regexp_full_match({t}, '-[0-9].*') "
        f"GROUP BY 1 ORDER BY 1 LIMIT {MAX_PHONE_VALUES}"
    )
    affected = 0
    examples: list[tuple[str, str]] = []
    for value, n in distinct:
        formatted = format_phone_or_original(value, DEFAULT_REGION)
        if formatted != value:
            affected += int(n)
            if len(examples) < MAX_REFORMAT_EXAMPLES:
                examples.append((str(value), str(formatted)))
    return affected, examples


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
        # Against the column's own usual length when it has one. Numbers from
        # several countries have none, and then only what is too short to be a
        # phone number anywhere counts.
        against_usual = usual is not None and usual_count >= USUAL_LENGTH_SHARE * int(row[0])
        short_below = usual if against_usual and usual else patterns.PHONE_MIN_DIGITS
        short = ctx.query(
            f"SELECT count(*), list(t ORDER BY d, t) FROM "
            f"(SELECT {t} AS t, {digits} AS d FROM {RAW_REF} WHERE {t} IS NOT NULL) "
            "WHERE d < $least",
            {"least": short_below},
        )[0]
        reformat_count, reformat_examples = (
            _reformat_evidence(ctx, t) if kind == "phone" else (0, [])
        )
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
                short_below=short_below,
                against_usual=against_usual,
                short_examples=list(short[1] or [])[:5],
                reformat_count=reformat_count,
                reformat_examples=reformat_examples,
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
        if item.short:
            b = IssueBuilder(ctx, DetectorName.CONTACT_FORMATS, [item.column], "short")
            describe = copy.short_phones if item.against_usual else copy.too_short_for_a_phone
            title, explanation, prompt = describe(
                item.column, item.short, item.short_below, item.short_examples
            )
            too_short = DigitsFewerThanCondition(column=item.column, count=item.short_below)
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
        if item.reformat_count:
            b = IssueBuilder(ctx, DetectorName.CONTACT_FORMATS, [item.column], "format")
            title, explanation = copy.inconsistent_phone_format(
                item.column, item.reformat_count, item.reformat_examples
            )
            issues.append(
                b.build(
                    title=title,
                    explanation=explanation,
                    affected_rows=item.reformat_count,
                    tier=Tier.LIKELY,
                    steps=[b.step(NormalizePhoneStep(columns=[item.column]))],
                    examples=[before for before, _after in item.reformat_examples],
                )
            )
    return issues


def run(ctx: DetectorContext) -> list[Issue]:
    return decide(gather(ctx), ctx)
