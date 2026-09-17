"""What one before/after comparison produced."""

from pydantic import BaseModel, Field

from app.questions.models import AnswerDiff
from app.steps.models import Recipe


class Comparison(BaseModel):
    # The recipe these answers came from, so a later comparison can work out
    # what changed without being told.
    recipe: Recipe
    # What the cleaned rows look like; recipes that make the same rows share it.
    recipe_key: str
    # Every question asked, ranked by impact. Unlocked ones are flagged, and the
    # ones that didn't move are kept so the story can say what stayed the same.
    diffs: list[AnswerDiff] = Field(default_factory=list)
    # Queries this pass actually ran, and the questions it ran them for.
    evaluations: int = 0
    recomputed: list[str] = Field(default_factory=list)
