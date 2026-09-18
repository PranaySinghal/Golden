"""What the "what changed" screen shows, built from a comparison. No numbers made here.

Every value comes from the engine's `AnswerDiff`; this decides only what the
screen needs and how it's grouped.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.compare.before import RULES
from app.compare.models import Comparison
from app.questions.models import AnswerDiff, GroupDiff, Measure, StepContribution
from app.steps.models import Recipe

CardKind = Literal["headline", "breakdown", "trend"]
BLANK_LABEL = "(blank)"


class ValueView(BaseModel):
    answerable: bool
    value: float | None = None
    # Why it can't be answered, in plain words, when it can't.
    note: str | None = None
    rows_used: int = 0
    rows_skipped: int = 0


class GroupChangeView(BaseModel):
    label: str
    # None means "no value to show", which isn't the same as zero: an average
    # over no values has no answer, while a count of nothing really is 0.
    before: float | None
    after: float | None
    status: Literal["same", "changed", "appeared", "disappeared"]


class MergedNote(BaseModel):
    """A spelling that now counts as another: "sales" folded into "Sales"."""

    label: str
    into: str


class WhyView(BaseModel):
    step_ids: list[str] = Field(default_factory=list)
    groups: list[StepContribution] = Field(default_factory=list)
    method: Literal["exact", "estimated", "none"] = "none"


class AnswerCardView(BaseModel):
    question_id: str
    label: str
    kind: CardKind
    measure: Measure
    changed: bool
    unlocked: bool
    impact: float
    before: ValueView
    after: ValueView
    change: float | None = None
    relative_change: float | None = None
    groups: list[GroupChangeView] = Field(default_factory=list)
    merged: list[MergedNote] = Field(default_factory=list)
    why: WhyView


class ComparisonResponse(BaseModel):
    # Answers that moved, most telling first.
    cards: list[AnswerCardView] = Field(default_factory=list)
    # Questions the raw file couldn't answer at all.
    unlocked: list[AnswerCardView] = Field(default_factory=list)
    # Answers that came out the same, by label, for the collapsed list.
    unchanged: list[str] = Field(default_factory=list)
    # How a spreadsheet reads the raw file, shown in the explainer.
    before_rules: list[str] = Field(default_factory=list)
    recipe_key: str
    has_steps: bool
    questions_asked: int
    recomputed: int = 0


def comparison_response(comparison: Comparison) -> ComparisonResponse:
    changed = [d for d in comparison.diffs if d.changed and not d.unlocked]
    unlocked = [d for d in comparison.diffs if d.unlocked]
    return ComparisonResponse(
        cards=[_card(d) for d in changed],
        unlocked=[_card(d) for d in unlocked],
        unchanged=[d.question.label for d in comparison.diffs if not d.changed],
        before_rules=list(RULES),
        recipe_key=comparison.recipe_key,
        has_steps=_runs_anything(comparison.recipe),
        questions_asked=len(comparison.diffs),
        recomputed=len(comparison.recomputed),
    )


def _runs_anything(recipe: Recipe) -> bool:
    return any(step.enabled for step in recipe.steps)


def _card(diff: AnswerDiff) -> AnswerCardView:
    merged = [
        MergedNote(label=group.label or BLANK_LABEL, into=group.merged_into)
        for group in diff.groups
        if group.merged_into is not None
    ]
    return AnswerCardView(
        question_id=diff.question.id,
        label=diff.question.label,
        kind=_kind(diff),
        measure=diff.question.measure,
        changed=diff.changed,
        unlocked=diff.unlocked,
        impact=diff.impact,
        before=_value(diff, "before"),
        after=_value(diff, "after"),
        change=diff.change,
        relative_change=diff.relative_change,
        groups=[_group(group) for group in diff.groups if group.merged_into is None],
        merged=merged,
        why=WhyView(
            step_ids=diff.attribution,
            groups=diff.attribution_detail,
            method=diff.attribution_method,
        ),
    )


def _kind(diff: AnswerDiff) -> CardKind:
    if diff.question.group_by is None:
        return "headline"
    return "trend" if diff.question.grain is not None else "breakdown"


def _value(diff: AnswerDiff, side: Literal["before", "after"]) -> ValueView:
    answer = diff.before if side == "before" else diff.after
    return ValueView(
        answerable=answer.answerable,
        value=answer.value,
        note=answer.note,
        rows_used=answer.rows_used,
        rows_skipped=answer.rows_skipped,
    )


def _group(group: GroupDiff) -> GroupChangeView:
    return GroupChangeView(
        label=group.label or BLANK_LABEL,
        before=group.before,
        after=group.after,
        status=group.status,
    )
