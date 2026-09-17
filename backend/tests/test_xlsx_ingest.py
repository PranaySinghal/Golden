import datetime as dt

import duckdb
import pytest

from app.errors import EmptyFileError, SheetNotFoundError, UnreadableFileError
from app.ingest.models import HeaderMode, IngestOptions, SourceFormat
from app.ingest.xlsx_adapter import cell_to_text
from tests.conftest import load, make_xlsx, raw_rows

TWO_SHEETS = make_xlsx(
    {
        "Summary": [["region", "total"], ["North", 10], ["South", 20]],
        "Details": [["sku", "qty"], ["A-1", 3], ["B-2", 4], ["C-3", 5]],
    }
)


def test_first_sheet_is_read_by_default(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, TWO_SHEETS, filename="book.xlsx")

    assert result.format is SourceFormat.XLSX
    assert result.sheet_name == "Summary"
    assert result.available_sheets == ["Summary", "Details"]
    assert result.encoding is None
    assert result.delimiter is None
    assert result.columns == ["region", "total"]
    assert raw_rows(conn) == [(1, "North", "10"), (2, "South", "20")]


def test_chosen_sheet_is_read(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, TWO_SHEETS, filename="book.xlsx", options=IngestOptions(sheet="Details"))

    assert result.sheet_name == "Details"
    assert result.columns == ["sku", "qty"]
    assert result.row_count == 3


def test_unknown_sheet_lists_the_available_ones(conn: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(SheetNotFoundError) as excinfo:
        load(conn, TWO_SHEETS, filename="book.xlsx", options=IngestOptions(sheet="Nope"))

    assert excinfo.value.available == ["Summary", "Details"]
    assert '"Summary"' in excinfo.value.message


def test_hidden_first_sheet_is_skipped_by_default(conn: duckdb.DuckDBPyConnection) -> None:
    data = make_xlsx(
        {"Lookup": [["k"], ["v"]], "Data": [["name"], ["Ann"]]},
        hidden={"Lookup"},
    )

    result = load(conn, data, filename="book.xlsx")

    assert result.sheet_name == "Data"
    assert result.available_sheets == ["Lookup", "Data"]


def test_cells_become_text_the_way_a_user_sees_them(conn: duckdb.DuckDBPyConnection) -> None:
    data = make_xlsx(
        {
            "Sheet": [
                ["whole", "fraction", "flag", "day", "moment", "blank", "label"],
                [
                    85000.0,
                    12.75,
                    True,
                    dt.datetime(2024, 3, 15),
                    dt.datetime(2024, 3, 15, 9, 30),
                    None,
                    "007",
                ],
            ]
        }
    )

    load(conn, data, filename="book.xlsx")

    assert raw_rows(conn) == [
        (1, "85000", "12.75", "TRUE", "2024-03-15", "2024-03-15 09:30:00", None, "007")
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (False, "FALSE"),
        (42, "42"),
        (3.0, "3"),
        (0.1, "0.1"),
        (1e20, "1e+20"),
        (float("nan"), "nan"),
        (dt.date(2024, 1, 2), "2024-01-02"),
        (dt.time(8, 5), "08:05:00"),
        ("", None),
        ("  spaced ", "  spaced "),
    ],
)
def test_cell_to_text(value: object, expected: str | None) -> None:
    assert cell_to_text(value) == expected


def test_empty_sheet_is_rejected(conn: duckdb.DuckDBPyConnection) -> None:
    data = make_xlsx({"Empty": [], "Data": [["a"], ["1"]]})

    with pytest.raises(EmptyFileError):
        load(conn, data, filename="book.xlsx")


def test_header_only_sheet(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, make_xlsx({"S": [["a", "b"]]}), filename="book.xlsx")

    assert result.columns == ["a", "b"]
    assert result.row_count == 0


def test_sheet_without_header(conn: duckdb.DuckDBPyConnection) -> None:
    data = make_xlsx(
        {"S": [["X-1", 10, dt.datetime(2024, 1, 1)], ["X-2", 20, dt.datetime(2024, 1, 2)]]}
    )

    result = load(conn, data, filename="book.xlsx")

    assert result.header_detected is False
    assert result.columns == ["column_1", "column_2", "column_3"]


def test_first_row_is_data_toggle_on_excel(conn: duckdb.DuckDBPyConnection) -> None:
    data = make_xlsx({"S": [["alpha", "beta"], ["gamma", "delta"]]})

    result = load(
        conn, data, filename="book.xlsx", options=IngestOptions(header=HeaderMode.FIRST_ROW_IS_DATA)
    )

    assert result.row_count == 2


def test_gaps_and_ragged_rows_in_a_sheet(conn: duckdb.DuckDBPyConnection) -> None:
    data = make_xlsx({"S": [["a", "b"], [1], [], [2, 3, 4]]})

    result = load(conn, data, filename="book.xlsx")

    assert result.columns == ["a", "b", "column_3"]
    assert result.empty_rows_skipped == 1
    assert raw_rows(conn) == [(1, "1", None, None), (2, "2", "3", "4")]


def test_corrupt_workbook_is_rejected(conn: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(UnreadableFileError):
        load(conn, b"PK\x03\x04not really a zip", filename="book.xlsx")


def test_workbook_renamed_to_csv_is_still_read_as_excel(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, TWO_SHEETS, filename="export.csv")

    assert result.format is SourceFormat.XLSX
    assert result.sheet_name == "Summary"
