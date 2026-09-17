from enum import StrEnum

from pydantic import BaseModel, Field


class SemanticRole(StrEnum):
    IDENTIFIER = "identifier"
    CATEGORY = "category"
    MEASURE = "measure"
    DATE = "date"
    CONTACT = "contact"
    TEXT = "text"


class PhysicalType(StrEnum):
    """The dominant shape of the values. Storage is always text."""

    EMPTY = "empty"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    DATETIME = "datetime"
    TEXT = "text"


class PatternKind(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    URL = "url"
    DATE_YEAR_FIRST = "date_year_first"
    DATE_NUMERIC = "date_numeric"
    DATE_TEXT = "date_text"
    DATETIME = "datetime"
    INTEGER = "integer"
    DECIMAL = "decimal"
    CURRENCY = "currency"
    PERCENT = "percent"
    THOUSANDS_SEPARATOR = "thousands_separator"
    BOOLEAN = "boolean"
    LEADING_ZEROS = "leading_zeros"
    PLACEHOLDER = "placeholder"
    CODE_SHAPE = "code_shape"
    DELIMITED = "delimited"


class ColumnFlag(StrEnum):
    LOW_UNIQUENESS = "low_uniqueness"
    ALL_BLANK = "all_blank"
    MOSTLY_BLANK = "mostly_blank"
    CONSTANT = "constant"
    NAME_HINT_USED = "name_hint_used"


class DetectedPattern(BaseModel):
    kind: PatternKind
    match_count: int
    match_rate: float = Field(description="Share of filled values that match, from 0 to 1.")
    detail: str | None = Field(
        default=None,
        description='Extra context, e.g. the placeholder text "N/A", a code shape '
        '"AAA9999", or the separator "-".',
    )


class ColumnProfile(BaseModel):
    name: str
    position: int = Field(description="Zero-based position among the file's columns.")
    physical_type: PhysicalType
    semantic_role: SemanticRole
    role_confidence: float = Field(description="How sure the role guess is, from 0 to 1.")
    role_note: str = Field(
        description="Plain-language reason for the role, suitable for a hover note."
    )
    flags: list[ColumnFlag]
    row_count: int
    non_blank_count: int
    fill_rate: float
    distinct_count: int
    uniqueness: float = Field(description="Distinct values divided by filled values.")
    patterns: list[DetectedPattern]
    min_value: str | None = Field(description="Smallest number or earliest date, when typed.")
    max_value: str | None = Field(description="Largest number or latest date, when typed.")
    sample_values: list[str] = Field(description="Up to 5 of the most frequent values.")


class DatasetProfile(BaseModel):
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
