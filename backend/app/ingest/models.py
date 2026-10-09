from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field


class SourceFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"


class HeaderMode(StrEnum):
    """Whether the first row holds column names.

    AUTO guesses from the values; the other two let the user override the guess
    (the "first row is data" toggle).
    """

    AUTO = "auto"
    FIRST_ROW_IS_HEADER = "header"
    FIRST_ROW_IS_DATA = "data"


class IngestOptions(BaseModel):
    sheet: str | None = Field(
        default=None, description="Excel sheet to read. None means the first visible sheet."
    )
    header: HeaderMode = HeaderMode.AUTO


class IngestResult(BaseModel):
    filename: str
    format: SourceFormat
    encoding: str | None = Field(description="Text encoding used to read a CSV file.")
    delimiter: str | None = Field(description="Separator between values in a CSV file.")
    sheet_name: str | None = Field(description="Excel sheet that was read.")
    available_sheets: list[str] = Field(description="All sheets in an Excel file.")
    header_mode: HeaderMode = Field(description="The header option that was requested.")
    header_detected: bool = Field(description="Whether the first row was used as column names.")
    original_headers: list[str] = Field(
        description="Column names exactly as found in the file; empty when there was no header."
    )
    columns: list[str] = Field(description="Unique column names used in the table, in file order.")
    row_count: int
    empty_rows_skipped: int = Field(description="Rows with no values at all that were not loaded.")
    title_rows_skipped: list[str] = Field(
        default_factory=list,
        description="Title or note lines found above the column names, kept here, not loaded.",
    )


@dataclass
class SourceTable:
    """What an adapter hands the loader: rows of text plus facts about the source."""

    rows: Iterator[list[str | None]]
    encoding: str | None = None
    delimiter: str | None = None
    sheet_name: str | None = None
    available_sheets: list[str] = field(default_factory=list)
