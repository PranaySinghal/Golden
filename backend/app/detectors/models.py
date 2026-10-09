"""Issues: problems found in a table, each with a confidence tier and proposed fixes."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.steps.models import Step


class Tier(StrEnum):
    # Can't change meaning; applied automatically and shown as already fixed.
    SAFE = "safe"
    # Almost certainly right; shown for review with the fix filled in.
    LIKELY = "likely"
    # Ambiguous; the user picks from plain-language choices.
    ASK = "ask"


class DetectorName(StrEnum):
    PLACEHOLDERS = "placeholders"
    NUMBERS_AS_TEXT = "numbers_as_text"
    DATES = "dates"
    CATEGORY_VARIANTS = "category_variants"
    EXTRA_SPACES = "extra_spaces"
    COMBINED_COLUMNS = "combined_columns"
    DUPLICATES = "duplicates"
    IDENTIFIER_REPEATS = "identifier_repeats"
    OUT_OF_RANGE = "out_of_range"
    CONTACT_FORMATS = "contact_formats"
    MISSING_VALUES = "missing_values"
    # Not a detector: a fix a model proposed, which passed every check.
    AI_SUGGESTION = "ai_suggestion"
    # Not a detector: a lookup that found several answers and needs the user to pick.
    CONNECTOR_MATCH = "connector_match"


class Choice(BaseModel):
    """One answer to an ask-tier question."""

    id: str
    label: str
    description: str
    steps: list[Step] = Field(default_factory=list)
    recommended: bool = False


class AskQuestion(BaseModel):
    prompt: str
    choices: Annotated[list[Choice], Field(min_length=2, max_length=4)]

    @model_validator(mode="after")
    def _at_most_one_recommended(self) -> Self:
        if sum(choice.recommended for choice in self.choices) > 1:
            raise ValueError("an ask question can recommend at most one choice")
        return self


class Issue(BaseModel):
    id: str
    detector: DetectorName
    # Where it came from. "ai" issues are shown for review and never applied
    # automatically, whatever tier they carry.
    source: Literal["rules", "ai"] = "rules"
    columns: list[str]
    title: str
    explanation: str
    affected_rows: int
    tier: Tier
    # Temporary until M4: the share of rows affected, from 0 to 1.
    impact: float
    steps: list[Step] = Field(default_factory=list)
    ask: AskQuestion | None = None
    examples: Annotated[list[str], Field(max_length=5)] = Field(default_factory=list)
    # Issues whose steps must run before this one's (e.g. reading a column as numbers).
    requires: list[str] = Field(default_factory=list)
    # Ids of the questions whose answers this fix changes, once scored.
    moves_answers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _steps_match_tier(self) -> Self:
        if self.tier is Tier.ASK:
            if self.ask is None or self.steps:
                raise ValueError("ask-tier issues carry a question and no direct steps")
        elif self.ask is not None or not self.steps:
            raise ValueError("safe and likely issues carry steps and no question")
        return self
