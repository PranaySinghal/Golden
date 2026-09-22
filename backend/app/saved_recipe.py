"""Re-using steps saved from one file on another one.

Downloading "the steps" gives a file describing a cleaning: which steps ran, in
what order, and which columns they need. This puts that file back to work on a
new upload, so next month's version of the same report can be cleaned the way
last month's was, without answering everything again.

A recipe either fits or it doesn't. If any step can't run, nothing is applied
and every reason is reported: a half-cleaned file that nobody chose is worse
than an uncleaned one, and `replay_recipe` guarantees that a refusal leaves the
file exactly as uploaded.
"""

from dataclasses import dataclass, field

from app.steps import recipe_ops
from app.steps.apply import StepStatus
from app.steps.errors import RecipeFileError
from app.steps.replay import check_compatibility, load_recipe_file, replay_recipe
from app.store import DatasetSession


@dataclass(frozen=True)
class RecipeOutcome:
    """What came of re-using a saved recipe, as something to show the reader."""

    applied: bool
    steps_applied: int = 0
    # The file these steps were saved from, so the reader knows what was re-used.
    source_filename: str | None = None
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def apply_saved_recipe(session: DatasetSession, data: bytes) -> RecipeOutcome:
    """Read saved steps, check they fit this file, and run them — or say why not.

    The caller holds `session.lock`.

    A recipe that can't be read or doesn't fit is a *result* of this operation,
    not a failure of it: the file is fine, and the reader needs the reasons more
    than the caller needs an exception. So `RecipeFileError` is caught and
    reported. Nothing else is.
    """
    try:
        recipe_file = load_recipe_file(data)
    except RecipeFileError as error:
        return RecipeOutcome(applied=False, problems=[error.message])

    source = recipe_file.source.filename
    fit = check_compatibility(recipe_file, session.profile)
    if not fit.compatible:
        return RecipeOutcome(
            applied=False, source_filename=source, problems=fit.problems, warnings=fit.warnings
        )

    # Compatible, so this won't raise; it re-checks, which keeps the
    # all-or-nothing guarantee in one place rather than two.
    result = replay_recipe(session.conn, recipe_file, session.profile)

    edit = recipe_ops.replace(session.recipe, session.history, recipe_file.recipe)
    session.recipe, session.history = edit.recipe, edit.history
    session.applied = result
    # These recorded decisions about the recipe that has just been replaced.
    # `review.prepare` fills them back in for whatever the new steps match.
    session.answers.clear()
    session.rejected.clear()
    session.step_origin.clear()

    applied = sum(1 for outcome in result.outcomes if outcome.status is StepStatus.APPLIED)
    return RecipeOutcome(
        applied=True,
        steps_applied=applied,
        source_filename=source,
        warnings=fit.warnings,
    )
