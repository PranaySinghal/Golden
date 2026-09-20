"""Blank cells in number, category, and date columns."""

from dataclasses import dataclass

from app.detectors import copy
from app.detectors.base import DetectorContext, IssueBuilder, reading_issue_id
from app.detectors.models import AskQuestion, Choice, DetectorName, Issue, Tier
from app.profile.models import ColumnFlag, SemanticRole
from app.steps.models import BlankCondition, FillMissingStep, SetAsideRowsStep

MIN_BLANK_SHARE = 0.01
KINDS = {
    SemanticRole.MEASURE: "number",
    SemanticRole.CATEGORY: "category",
    SemanticRole.DATE: "date",
}


@dataclass(frozen=True)
class Evidence:
    column: str
    role: SemanticRole
    blanks: int


def gather(ctx: DetectorContext) -> list[Evidence]:
    """Columns with gaps worth asking about.

    A column that's mostly empty isn't a column with missing values; it's a
    column that only applies to a few rows, like one block of a cross-tab.
    Offering to fill 800 blanks from the 30 values that are there would be bad
    advice, and asking it once per column buries everything else.
    """
    # The profile already counts blanks; no extra query needed.
    skip = {ColumnFlag.ALL_BLANK, ColumnFlag.MOSTLY_BLANK}
    return [
        Evidence(c.name, c.semantic_role, c.row_count - c.non_blank_count)
        for c in ctx.columns_with_role(*KINDS)
        if not skip & set(c.flags)
    ]


def decide(evidence: list[Evidence], ctx: DetectorContext) -> list[Issue]:
    issues = []
    for item in evidence:
        if item.blanks == 0 or item.blanks < MIN_BLANK_SHARE * ctx.row_count:
            continue
        kind = KINDS[item.role]
        b = IssueBuilder(ctx, DetectorName.MISSING_VALUES, [item.column], "blank")
        title, explanation, prompt = copy.missing_values(item.column, item.blanks, kind)
        choices: list[Choice] = [
            b.choice(
                "leave",
                "Leave them blank",
                "They aren't counted in totals, averages, or groups.",
                [],
                recommended=True,
            )
        ]
        requires: list[str] = []
        if kind == "number":
            choices.append(
                b.choice(
                    "median",
                    "Fill with the middle value",
                    "Use the middle of the filled values, which isn't pulled by extremes.",
                    [b.step(FillMissingStep(column=item.column, strategy="median"))],
                )
            )
            requires = [reading_issue_id(item.column)]
        elif kind == "category":
            choices.append(
                b.choice(
                    "unknown",
                    'Fill with "Unknown"',
                    'Group them together under "Unknown".',
                    [
                        b.step(
                            FillMissingStep(column=item.column, strategy="value", value="Unknown")
                        )
                    ],
                )
            )
        choices.append(
            b.choice(
                "set_aside",
                "Set these rows aside",
                "Leave these rows out of every answer.",
                [b.step(SetAsideRowsStep(condition=BlankCondition(column=item.column)))],
            )
        )
        issues.append(
            b.build(
                title=title,
                explanation=explanation,
                affected_rows=item.blanks,
                tier=Tier.ASK,
                ask=AskQuestion(prompt=prompt, choices=choices),
                requires=requires,
            )
        )
    return issues


def run(ctx: DetectorContext) -> list[Issue]:
    return decide(gather(ctx), ctx)
