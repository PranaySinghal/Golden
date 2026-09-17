"""Compare a question's before and after answers."""

from app.compare.evaluate import OTHER_KEY
from app.questions.models import Answer, AnswerDiff, GroupDiff, GroupValue, Measure, Question
from app.steps.schema import normalize_text

# Sums of many doubles pick up rounding noise; changes this small aren't real.
RELATIVE_TOLERANCE = 1e-9
# Groups shown per breakdown; the rest are summed into one line.
MAX_SHOWN_GROUPS = 20
OTHER_LABEL = "All other groups"


def same_number(before: float | None, after: float | None) -> bool:
    if before is None or after is None:
        return before is after
    return abs(after - before) <= RELATIVE_TOLERANCE * max(1.0, abs(before))


def relative(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before == 0:
        return None
    return (after - before) / abs(before)


def diff_answers(question: Question, before: Answer, after: Answer) -> AnswerDiff:
    if question.group_by is None:
        return _scalar_diff(question, before, after)
    groups = diff_groups(question, before.groups, after.groups)
    changed = before.answerable != after.answerable or any(g.status != "same" for g in groups)
    return AnswerDiff(
        question=question,
        before=before,
        after=after,
        changed=changed,
        groups=groups,
        unlocked=unlocked(before, after),
    )


def unlocked(before: Answer, after: Answer) -> bool:
    """The raw file couldn't answer this at all, and the cleaned one can."""
    return not before.answerable and after.answerable


def _scalar_diff(question: Question, before: Answer, after: Answer) -> AnswerDiff:
    both = before.answerable and after.answerable
    changed = before.answerable != after.answerable or (
        both and not same_number(before.value, after.value)
    )
    change = None
    if both and before.value is not None and after.value is not None:
        change = after.value - before.value
    return AnswerDiff(
        question=question,
        before=before,
        after=after,
        changed=changed,
        change=change,
        relative_change=relative(before.value, after.value) if both else None,
        unlocked=unlocked(before, after),
    )


def diff_groups(
    question: Question, before: list[GroupValue], after: list[GroupValue]
) -> list[GroupDiff]:
    counts = question.measure is not Measure.AVG
    before_by_key = {g.key: g for g in before}
    after_by_key = {g.key: g for g in after}
    # A group that vanished but reads the same as a surviving one once spacing is
    # ignored was folded into it ("sales " into "Sales"), not lost.
    after_by_loose = {
        normalize_text(g.key): g for g in after if g.key is not None and g.key != OTHER_KEY
    }

    diffs: list[GroupDiff] = []
    for key in list(dict.fromkeys([*before_by_key, *after_by_key])):
        b, a = before_by_key.get(key), after_by_key.get(key)
        missing = 0.0 if counts else None
        before_value = b.value if b else missing
        after_value = a.value if a else missing
        if b and not a:
            status = "disappeared"
        elif a and not b:
            status = "appeared"
        else:
            status = "same" if same_number(before_value, after_value) else "changed"
        merged = None
        if status == "disappeared" and key is not None and key != OTHER_KEY:
            target = after_by_loose.get(normalize_text(key))
            merged = target.label if target else None
        change = None
        if before_value is not None and after_value is not None:
            change = after_value - before_value
        shown = a if a is not None else b
        diffs.append(
            GroupDiff(
                key=key,
                label=shown.label if shown is not None else None,
                before=before_value,
                after=after_value,
                status=status,
                merged_into=merged,
                change=change,
                relative_change=relative(before_value, after_value),
            )
        )

    if question.grain is not None:
        return sorted(diffs, key=lambda d: (d.key == OTHER_KEY, str(d.key)))
    ordered = sorted(
        diffs,
        key=lambda d: (
            d.status == "disappeared",
            -(d.after or 0.0)
            if counts
            else -(max(_rows(after_by_key, d.key), _rows(before_by_key, d.key))),
            str(d.label),
        ),
    )
    return _cap(ordered, counts)


def _rows(groups: dict[str | None, GroupValue], key: str | None) -> int:
    group = groups.get(key)
    return group.rows if group else 0


def _cap(diffs: list[GroupDiff], counts: bool) -> list[GroupDiff]:
    if len(diffs) <= MAX_SHOWN_GROUPS:
        return diffs
    shown, rest = diffs[: MAX_SHOWN_GROUPS - 1], diffs[MAX_SHOWN_GROUPS - 1 :]
    before: float | None
    after: float | None
    if counts:
        before = sum(d.before or 0.0 for d in rest)
        after = sum(d.after or 0.0 for d in rest)
    else:
        # Averages of different groups can't be combined without their row counts.
        before = after = None
    other = GroupDiff(
        key=OTHER_KEY,
        label=OTHER_LABEL,
        before=before,
        after=after,
        status="same" if same_number(before, after) else "changed",
        change=None if before is None or after is None else after - before,
        relative_change=relative(before, after),
    )
    return [*shown, other]
