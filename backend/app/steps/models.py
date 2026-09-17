"""The typed spine of cleaning: Steps, row conditions, Recipes, and the recipe file.

Models only describe what to do. How each step becomes SQL lives in compile.py.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.profile.patterns import DateFormat

MAX_STEPS = 200
MAX_MAPPINGS = 1000
MAX_LISTED_VALUES = 100
MAX_ROW_IDS = 10_000

StepId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{12}$")]
ColumnName = Annotated[str, StringConstraints(min_length=1, max_length=255)]
NewColumnName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
Columns = Annotated[list[ColumnName], Field(min_length=1, max_length=500)]
KeepRowIds = Annotated[list[int], Field(max_length=MAX_ROW_IDS)]
TextMatch = Literal["exact", "ignore_case_and_spaces"]


def new_step_id() -> str:
    return uuid.uuid4().hex[:12]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _StepBase(_Model):
    id: StepId = Field(default_factory=new_step_id)
    enabled: bool = True


# --- row conditions (for set_aside_rows) ----------------------------------------


class BlankCondition(_Model):
    kind: Literal["blank"] = "blank"
    column: ColumnName


class EqualsCondition(_Model):
    kind: Literal["equals"] = "equals"
    column: ColumnName
    value: str | float
    match: TextMatch = "exact"


class OneOfCondition(_Model):
    kind: Literal["one_of"] = "one_of"
    column: ColumnName
    values: Annotated[list[str | float], Field(min_length=1, max_length=MAX_LISTED_VALUES)]
    match: TextMatch = "exact"


class RowIdsCondition(_Model):
    kind: Literal["row_ids"] = "row_ids"
    row_ids: Annotated[list[int], Field(min_length=1, max_length=MAX_ROW_IDS)]


class OutsideRangeCondition(_Model):
    kind: Literal["outside_range"] = "outside_range"
    column: ColumnName
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _has_a_bound(self) -> Self:
        if self.min is None and self.max is None:
            raise ValueError("outside_range needs a min, a max, or both")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("outside_range min can't be larger than max")
        return self


class NotMatchingCondition(_Model):
    kind: Literal["not_matching"] = "not_matching"
    column: ColumnName
    pattern: Literal["email", "phone", "number", "date"]


RowCondition = Annotated[
    BlankCondition
    | EqualsCondition
    | OneOfCondition
    | RowIdsCondition
    | OutsideRangeCondition
    | NotMatchingCondition,
    Field(discriminator="kind"),
]


# --- steps ---------------------------------------------------------------------------


class TrimStep(_StepBase):
    type: Literal["trim"] = "trim"
    columns: Columns
    collapse_inner_spaces: bool = False


class NormalizeCaseStep(_StepBase):
    type: Literal["normalize_case"] = "normalize_case"
    columns: Columns
    case: Literal["lower", "upper", "title"]


class ValueMapping(_Model):
    from_value: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    # None means "make this blank".
    to_value: Annotated[str, StringConstraints(max_length=1000)] | None


class MapValuesStep(_StepBase):
    type: Literal["map_values"] = "map_values"
    column: ColumnName
    mappings: Annotated[list[ValueMapping], Field(min_length=1, max_length=MAX_MAPPINGS)]
    match: TextMatch = "exact"


class NullPlaceholdersStep(_StepBase):
    type: Literal["null_placeholders"] = "null_placeholders"
    columns: Columns
    placeholders: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=100)]],
        Field(min_length=1, max_length=MAX_LISTED_VALUES),
    ]


class CastNumberStep(_StepBase):
    type: Literal["cast_number"] = "cast_number"
    column: ColumnName
    decimal_separator: Literal[".", ","] = "."
    # "fraction" turns 15% into 0.15; "keep" turns it into 15.
    percent: Literal["keep", "fraction"] = "keep"
    allow_k_m_suffix: bool = False


class ParseDateStep(_StepBase):
    type: Literal["parse_date"] = "parse_date"
    column: ColumnName
    formats: Annotated[list[DateFormat], Field(min_length=1, max_length=5)]
    output: Literal["date", "datetime"] = "date"


class SplitColumnStep(_StepBase):
    type: Literal["split_column"] = "split_column"
    column: ColumnName
    delimiter: Annotated[str, StringConstraints(min_length=1, max_length=5)]
    into: Annotated[list[NewColumnName], Field(min_length=2, max_length=10)]
    trim_parts: bool = True
    keep_original: bool = True


class DedupeStep(_StepBase):
    type: Literal["dedupe"] = "dedupe"
    # None compares every column.
    columns: Columns | None = None
    match: TextMatch = "exact"
    keep: Literal["first", "last"] = "first"
    keep_row_ids: KeepRowIds = Field(default_factory=list)


class SetAsideRowsStep(_StepBase):
    type: Literal["set_aside_rows"] = "set_aside_rows"
    condition: RowCondition
    keep_row_ids: KeepRowIds = Field(default_factory=list)


class FillMissingStep(_StepBase):
    type: Literal["fill_missing"] = "fill_missing"
    column: ColumnName
    strategy: Literal["value", "mean", "median", "most_common", "previous"]
    value: str | float | None = None

    @model_validator(mode="after")
    def _value_matches_strategy(self) -> Self:
        if self.strategy == "value" and self.value is None:
            raise ValueError('fill_missing with strategy "value" needs a value')
        if self.strategy != "value" and self.value is not None:
            raise ValueError(f'fill_missing with strategy "{self.strategy}" takes no value')
        return self


# How each step type is named to users, e.g. in replay messages.
STEP_LABELS: dict[str, str] = {
    "trim": "Trim spaces",
    "normalize_case": "Change letter case",
    "map_values": "Replace values",
    "null_placeholders": "Clear placeholder text",
    "cast_number": "Read as numbers",
    "parse_date": "Read as dates",
    "split_column": "Split a column",
    "dedupe": "Set aside repeated rows",
    "set_aside_rows": "Set aside rows",
    "fill_missing": "Fill in blanks",
}

Step = Annotated[
    TrimStep
    | NormalizeCaseStep
    | MapValuesStep
    | NullPlaceholdersStep
    | CastNumberStep
    | ParseDateStep
    | SplitColumnStep
    | DedupeStep
    | SetAsideRowsStep
    | FillMissingStep,
    Field(discriminator="type"),
]


class Recipe(_Model):
    version: Literal[1] = 1
    steps: Annotated[list[Step], Field(max_length=MAX_STEPS)] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_step_ids(self) -> Self:
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")
        return self


class RecipeSource(_Model):
    filename: str
    columns: list[str]


class RecipeFile(_Model):
    """What "download recipe" produces, and what replaying a recipe reads."""

    format: Literal["tidylab.recipe"] = "tidylab.recipe"
    version: Literal[1] = 1
    created_at: datetime
    source: RecipeSource
    requires_columns: list[str]
    recipe: Recipe
