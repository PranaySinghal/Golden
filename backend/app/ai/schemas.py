"""The only shapes an AI reply is allowed to take.

Anything else is rejected whole: extra fields, missing fields, wrong types, a
list that's too long. Nothing here is trusted yet — these models say the reply
is well-formed, not that it's true. fixes.py and wording.py decide that.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MAX_FIXES = 5
MAX_STEPS_PER_FIX = 4
MAX_TITLE_CHARS = 120
MAX_EXPLANATION_CHARS = 400
MAX_LABEL_CHARS = 100

Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITLE_CHARS)
]
Explanation = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_EXPLANATION_CHARS)
]
Label = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_LABEL_CHARS)
]


class _Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposedStep(_Reply):
    type: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ProposedFix(_Reply):
    columns: Annotated[list[str], Field(min_length=1, max_length=10)]
    title: Title
    explanation: Explanation
    # A model never gets to say "safe": nothing it proposes is applied unasked.
    confidence: Literal["likely", "ask"] = "likely"
    steps: Annotated[list[ProposedStep], Field(min_length=1, max_length=MAX_STEPS_PER_FIX)]


class SuggestFixesReply(_Reply):
    fixes: Annotated[list[ProposedFix], Field(max_length=MAX_FIXES)] = Field(default_factory=list)


class RewordedIssue(_Reply):
    id: str
    title: Title
    explanation: Explanation


class RewordIssuesReply(_Reply):
    items: list[RewordedIssue] = Field(default_factory=list)


class RewordedQuestion(_Reply):
    id: str
    label: Label


class RewordQuestionsReply(_Reply):
    items: list[RewordedQuestion] = Field(default_factory=list)
