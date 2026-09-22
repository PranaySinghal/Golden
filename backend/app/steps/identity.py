"""What a step *does*, as distinct from which step object does it.

Step ids are stable but not universal: `IssueBuilder` derives them from the
detector, a kind and the column names, so the same file read twice gives the
same ids — but a recipe saved from last month's file and the issues detected on
this month's carry ids that only sometimes line up. Sometimes they collide while
meaning different things (an issue whose parameters changed), and sometimes they
differ while meaning the same thing (a fix a model proposed).

So "is this fix already in the recipe?" can't be answered by id alone. It's
answered here, by comparing the work itself.
"""

from collections.abc import Sequence

from app.steps.models import Recipe, Step


def work_key(step: Step) -> str:
    """What a step does, ignoring which object does it and whether it's on.

    `enabled` is excluded deliberately: a step switched off is still in the
    recipe, and its issue still reads as answered, which is how the panel has
    always behaved.
    """
    return step.model_dump_json(exclude={"id", "enabled"})


def matched_ids(recipe: Recipe, steps: Sequence[Step]) -> list[str] | None:
    """The recipe's ids for `steps`, or None if any of them isn't in there.

    Each recipe step is claimed at most once, so two proposals doing identical
    work need two steps in the recipe to match. An empty `steps` gives `[]`,
    which is not the same answer as None: a choice that means "leave it alone"
    carries no steps and is still a choice that can be taken.
    """
    available: dict[str, list[str]] = {}
    for step in recipe.steps:
        available.setdefault(work_key(step), []).append(step.id)

    found: list[str] = []
    for step in steps:
        ids = available.get(work_key(step))
        if not ids:
            return None
        found.append(ids.pop(0))
    return found
