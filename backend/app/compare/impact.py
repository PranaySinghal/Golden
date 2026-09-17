"""How much an answer moved, weighted by how prominent the question is.

magnitude, from 0 to 1:
- a single value: |after - before| / |before|, capped at 1; 1 if only one side
  can be answered.
- counts per group: how far the share of rows per group moved,
  0.5 * sum(|after share - before share|) over every group on either side.
- averages per group: each group's relative change weighted by its rows; a group
  that appears or disappears counts as a full change. Capped at 1.

impact = question prominence * magnitude.
"""

from app.compare.diff import same_number
from app.questions.models import AnswerDiff, GroupValue, Measure

EPSILON = 1e-12


def magnitude(diff: AnswerDiff) -> float:
    before, after = diff.before, diff.after
    if not before.answerable and not after.answerable:
        return 0.0
    if before.answerable != after.answerable:
        return 1.0
    if diff.question.group_by is None:
        if same_number(before.value, after.value):
            return 0.0
        if before.value is None or after.value is None:
            return 1.0
        return min(1.0, abs(after.value - before.value) / max(abs(before.value), EPSILON))
    if diff.question.measure is Measure.AVG:
        return _average_shift(before.groups, after.groups)
    return _share_shift(before.groups, after.groups)


def _share_shift(before: list[GroupValue], after: list[GroupValue]) -> float:
    before_total = sum(g.value or 0.0 for g in before)
    after_total = sum(g.value or 0.0 for g in after)
    if before_total <= 0 or after_total <= 0:
        return 0.0 if before_total == after_total else 1.0
    before_share = {g.key: (g.value or 0.0) / before_total for g in before}
    after_share = {g.key: (g.value or 0.0) / after_total for g in after}
    keys = set(before_share) | set(after_share)
    moved = 0.5 * sum(abs(after_share.get(k, 0.0) - before_share.get(k, 0.0)) for k in keys)
    return 0.0 if moved < 1e-9 else min(1.0, moved)


def _average_shift(before: list[GroupValue], after: list[GroupValue]) -> float:
    before_by_key = {g.key: g for g in before}
    after_by_key = {g.key: g for g in after}
    weighted = weight = 0.0
    for key in set(before_by_key) | set(after_by_key):
        b, a = before_by_key.get(key), after_by_key.get(key)
        rows = max(b.rows if b else 0, a.rows if a else 0)
        if b is None or a is None or b.value is None or a.value is None:
            change = 0.0 if (b and a and b.value is None and a.value is None) else 1.0
        elif same_number(b.value, a.value):
            change = 0.0
        else:
            change = min(1.0, abs(a.value - b.value) / max(abs(b.value), EPSILON))
        weighted += change * rows
        weight += rows
    return min(1.0, weighted / weight) if weight else 0.0


def score(diff: AnswerDiff) -> AnswerDiff:
    size = round(magnitude(diff), 6)
    return diff.model_copy(
        update={"magnitude": size, "impact": round(diff.question.prominence * size, 6)}
    )


def rank(diffs: list[AnswerDiff]) -> list[AnswerDiff]:
    order = {d.question.id: index for index, d in enumerate(diffs)}
    return sorted(diffs, key=lambda d: (-d.impact, -d.question.prominence, order[d.question.id]))
