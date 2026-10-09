"""What the canvas offers: columns a user might want to add, and why."""

from typing import Literal

from pydantic import BaseModel, Field

MIN_SUGGESTIONS = 3
MAX_SUGGESTIONS = 5


class FillPlan(BaseModel):
    based_on: str
    kind: Literal["label", "text", "website"]
    # The only answers allowed in a label column.
    choices: list[str] = Field(default_factory=list)


class ColumnSuggestion(BaseModel):
    name: str
    reason: str
    # Text to put in every row until the real values are filled in. None leaves it blank.
    placeholder: str | None = None
    source: Literal["rules", "ai"] = "rules"
    # Where the values could come from one day, in plain words. Nothing is fetched.
    live_source: str | None = None
    # Set when a model could fill the column in, row by row, from an existing
    # column. None means the user fills it in themselves.
    fill: FillPlan | None = None


class ColumnIdeas(BaseModel):
    """What a model made of the file, kept once per file and filtered per request."""

    # "off" is a configuration, not a failure: the built-in ideas are complete.
    status: Literal["off", "ready", "failed"] = "off"
    about: str | None = None
    suggestions: list[ColumnSuggestion] = Field(default_factory=list)


class Suggestions(BaseModel):
    status: Literal["off", "ready", "failed"] = "off"
    # One sentence on what the file seems to be about, when a model was asked.
    about: str | None = None
    suggestions: list[ColumnSuggestion] = Field(default_factory=list)
