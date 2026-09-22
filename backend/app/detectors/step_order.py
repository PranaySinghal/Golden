"""Turn accepted issues into a recipe with steps in a dependable order.

Steps from different issues must run in a sensible sequence no matter which
issues were accepted: clean characters, then decide what placeholders mean,
then merge spellings, split columns, read numbers and dates, and only then
clear, dedupe, set aside, or fill values.
"""

from collections.abc import Mapping

from app.detectors.models import Issue, Tier
from app.steps.models import Recipe, Step

RANK: dict[str, int] = {
    "remove_characters": 0,
    "trim": 0,
    "null_placeholders": 1,
    "map_values": 2,
    "normalize_case": 2,
    "normalize_phone": 2,
    "split_column": 3,
    "cast_number": 4,
    "parse_date": 4,
    "clear_values": 5,
    "dedupe": 6,
    "set_aside_rows": 7,
    "fill_missing": 8,
}


def chosen_steps(issue: Issue, answers: Mapping[str, str]) -> list[Step]:
    """Steps for an issue: its own for safe/likely, the answered or recommended choice for ask."""
    if issue.tier is not Tier.ASK:
        return list(issue.steps)
    assert issue.ask is not None
    wanted = answers.get(issue.id)
    for choice in issue.ask.choices:
        if choice.id == wanted or (wanted is None and choice.recommended):
            return list(choice.steps)
    return []


def recipe_for(
    issues: list[Issue], accepted: set[str] | None = None, answers: Mapping[str, str] | None = None
) -> Recipe:
    """Build a recipe from accepted issues (all by default) and ask-tier answers.

    An accepted issue pulls in the issues it requires, like reading a column as
    numbers before filling its blanks with the middle value.
    """
    by_id = {issue.id: issue for issue in issues}
    wanted = set(by_id) if accepted is None else set(accepted)
    pending = list(wanted)
    while pending:
        for required in by_id[pending.pop()].requires:
            if required in by_id and required not in wanted:
                wanted.add(required)
                pending.append(required)

    ordered: list[tuple[int, int, int, Step]] = []
    for issue_index, issue in enumerate(issues):
        if issue.id not in wanted:
            continue
        for step_index, step in enumerate(chosen_steps(issue, answers or {})):
            ordered.append((RANK[step.type], issue_index, step_index, step))
    ordered.sort(key=lambda item: item[:3])

    steps: list[Step] = []
    seen: set[str] = set()
    for *_, step in ordered:
        # Two issues can propose the same change; keep it once.
        content = step.model_dump_json(exclude={"id"})
        if content not in seen and step.id not in {s.id for s in steps}:
            seen.add(content)
            steps.append(step)
    return Recipe(steps=steps)
