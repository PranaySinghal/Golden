"""The typed spine of cleaning: Steps, row conditions, Recipes, and the recipe file.

Models only describe what to do. How each step becomes SQL lives in compile.py.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.profile.patterns import DateFormat
from app.steps.phone import DEFAULT_REGION

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
ConnectorName = Literal["postal_geocode", "company_ticker", "stock_price", "ai_fill"]
# What an AI-filled column holds: one of a fixed list, free text, or a web address.
FillKind = Literal["label", "text", "website"]
MAX_FILL_CHOICES = 20
# How many columns each connector adds. Each adds one: a map position is one
# "latitude, longitude" cell, and a price's time is shown beside it, not in a column.
CONNECTOR_OUTPUTS: dict[str, int] = {
    "postal_geocode": 1,
    "company_ticker": 1,
    "stock_price": 1,
    "ai_fill": 1,
}


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


class DigitsFewerThanCondition(_Model):
    """Filled values with fewer digits than `count`, e.g. phone numbers that are too short."""

    kind: Literal["digits_fewer_than"] = "digits_fewer_than"
    column: ColumnName
    count: Annotated[int, Field(ge=1, le=30)]


RowCondition = Annotated[
    BlankCondition
    | EqualsCondition
    | OneOfCondition
    | RowIdsCondition
    | OutsideRangeCondition
    | NotMatchingCondition
    | DigitsFewerThanCondition,
    Field(discriminator="kind"),
]


# --- steps ---------------------------------------------------------------------------


class TrimStep(_StepBase):
    type: Literal["trim"] = "trim"
    columns: Columns
    collapse_inner_spaces: bool = False


class RemoveCharactersStep(_StepBase):
    type: Literal["remove_characters"] = "remove_characters"
    columns: Columns
    # Each character listed is removed; they aren't treated as a sequence.
    characters: Annotated[str, StringConstraints(min_length=1, max_length=10)]
    where: Literal["leading", "trailing", "anywhere"] = "leading"


class NormalizeCaseStep(_StepBase):
    type: Literal["normalize_case"] = "normalize_case"
    columns: Columns
    case: Literal["lower", "upper", "title"]


class NormalizePhoneStep(_StepBase):
    type: Literal["normalize_phone"] = "normalize_phone"
    columns: Columns
    # Used only for a number with no country code of its own to go by. An
    # ISO 3166-1 alpha-2 code, e.g. "US", "GB".
    default_region: Annotated[str, StringConstraints(min_length=2, max_length=2, to_upper=True)] = (
        DEFAULT_REGION
    )


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


class AddColumnStep(_StepBase):
    """A new column the user asked for: blank, or the same text in every row."""

    type: Literal["add_column"] = "add_column"
    name: NewColumnName
    # None leaves the column blank, ready to be filled in later.
    value: Annotated[str, StringConstraints(max_length=1000)] | None = None
    # None puts the column last.
    insert_after: ColumnName | None = None


class EnrichColumnStep(_StepBase):
    """New columns looked up from an outside service, one answer per different value.

    The step never fetches anything. A lookup run stores its answers under a
    `snapshot` id, and the step joins the table to that snapshot, so the same
    recipe always gives the same rows. Looking up again makes a new snapshot.
    """

    type: Literal["enrich_column"] = "enrich_column"
    connector: ConnectorName
    column: ColumnName
    into: Annotated[list[NewColumnName], Field(min_length=1, max_length=2)]
    # Postal codes only mean something inside a country. ISO 3166-1 alpha-2.
    country: Annotated[str, StringConstraints(min_length=2, max_length=2, to_upper=True)] | None = (
        None
    )
    # None means nothing has been looked up yet, so the new columns are empty.
    snapshot: StepId | None = None
    # --- AI fill only: what the new column means, so a model can fill it in ---
    instruction: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    kind: FillKind | None = None
    # For a label column, the only answers allowed. Keeps one spelling per label.
    choices: Annotated[
        list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]],
        Field(max_length=MAX_FILL_CHOICES),
    ] = Field(default_factory=list)
    # Up to two columns shown to the model beside the value, to tell rows apart.
    context: Annotated[list[ColumnName], Field(max_length=2)] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape_fits_connector(self) -> Self:
        wanted = CONNECTOR_OUTPUTS[self.connector]
        if len(self.into) != wanted:
            raise ValueError(f"{self.connector} adds {wanted} column(s), got {len(self.into)}")
        if (self.connector == "postal_geocode") != (self.country is not None):
            raise ValueError("a country goes with postal codes, and only with them")
        if self.connector == "ai_fill":
            if self.instruction is None or self.kind is None:
                raise ValueError("an AI-filled column needs to say what it means")
            if (self.kind == "label") != (len(self.choices) >= 2):
                raise ValueError("a label column needs a list of labels, and only a label column")
        elif self.instruction or self.kind or self.choices or self.context:
            raise ValueError("only an AI-filled column carries a meaning")
        return self


class ResolveMatchStep(_StepBase):
    """The user's pick where a lookup found several answers for one value."""

    type: Literal["resolve_match"] = "resolve_match"
    column: ColumnName
    value: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    into: ColumnName
    chosen: Annotated[str, StringConstraints(min_length=1, max_length=100)]


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


class ClearValuesStep(_StepBase):
    """Blank out values that match a condition, keeping the rest of the row."""

    type: Literal["clear_values"] = "clear_values"
    column: ColumnName
    condition: RowCondition


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
    "remove_characters": "Remove characters",
    "normalize_case": "Change letter case",
    "normalize_phone": "Tidy phone numbers",
    "map_values": "Replace values",
    "null_placeholders": "Clear placeholder text",
    "cast_number": "Read as numbers",
    "parse_date": "Read as dates",
    "split_column": "Split a column",
    "add_column": "Add a column",
    "enrich_column": "Look up new columns",
    "resolve_match": "Pick a match",
    "dedupe": "Set aside repeated rows",
    "set_aside_rows": "Set aside rows",
    "clear_values": "Clear values",
    "fill_missing": "Fill in blanks",
}

Step = Annotated[
    TrimStep
    | RemoveCharactersStep
    | NormalizeCaseStep
    | NormalizePhoneStep
    | MapValuesStep
    | NullPlaceholdersStep
    | CastNumberStep
    | ParseDateStep
    | SplitColumnStep
    | AddColumnStep
    | EnrichColumnStep
    | ResolveMatchStep
    | DedupeStep
    | SetAsideRowsStep
    | ClearValuesStep
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


def without_snapshots(recipe: Recipe) -> Recipe:
    """The recipe with no looked-up answers attached.

    A snapshot belongs to the file and the moment it was looked up for. Saved to
    a file or run on another one, a step keeps what to look up but must be told
    to go and do it again.
    """
    return Recipe(
        steps=[
            step.model_copy(update={"snapshot": None})
            if isinstance(step, EnrichColumnStep)
            else step
            for step in recipe.steps
        ]
    )
