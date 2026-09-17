import duckdb
import pytest

from app.config import Settings
from app.db import RAW_REF, RAW_TABLE, ROW_ID_COLUMN, SOURCE_CATALOG, raw_columns
from app.errors import EmptyFileError, FileTooLargeError, UnreadableFileError
from app.ingest.csv_adapter import sniff_delimiter
from app.ingest.models import HeaderMode, IngestOptions
from app.profile.profiler import profile_table
from tests.conftest import load, raw_rows


def column_types(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_catalog = $c AND table_name = $t",
        {"c": SOURCE_CATALOG, "t": RAW_TABLE},
    ).fetchall()
    return {str(name): str(kind) for name, kind in rows}


def test_basic_file_loads_every_value_as_text(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, "id,amount,when\nA1,10.5,2024-01-02\nA2,7,2024-01-03\n")

    assert result.columns == ["id", "amount", "when"]
    assert result.row_count == 2
    assert result.header_detected is True
    assert result.encoding == "utf-8"
    assert result.delimiter == ","
    types = column_types(conn)
    assert types.pop(ROW_ID_COLUMN) == "BIGINT"
    assert set(types.values()) == {"VARCHAR"}
    assert raw_rows(conn) == [(1, "A1", "10.5", "2024-01-02"), (2, "A2", "7", "2024-01-03")]


def test_values_are_preserved_exactly(conn: duckdb.DuckDBPyConnection) -> None:
    load(conn, 'code,note,num\n007, padded ,1e5\n"N/A","NULL",-0\n')

    assert raw_rows(conn) == [(1, "007", " padded ", "1e5"), (2, "N/A", "NULL", "-0")]


def test_blank_cells_become_null(conn: duckdb.DuckDBPyConnection) -> None:
    load(conn, 'a,b,c\n1,,""\n')

    assert raw_rows(conn) == [(1, "1", None, None)]


def test_quoted_fields_with_delimiters_quotes_and_newlines(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    load(conn, 'name,comment\nx,"hello, world"\ny,"say ""hi""\nsecond line"\n')

    assert raw_rows(conn) == [(1, "x", "hello, world"), (2, "y", 'say "hi"\nsecond line')]


def test_windows_line_endings(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, "a,b\r\n1,2\r\n3,4\r\n")

    assert result.row_count == 2
    assert raw_rows(conn) == [(1, "1", "2"), (2, "3", "4")]


def test_empty_file_is_rejected(conn: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(EmptyFileError):
        load(conn, b"")


def test_whitespace_only_file_is_rejected(conn: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(EmptyFileError):
        load(conn, "  \n\n \r\n")


def test_file_of_only_delimiters_is_rejected(conn: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(EmptyFileError):
        load(conn, ",,\n,,\n")


def test_header_only_file_gives_columns_and_no_rows(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, "name,amount,joined\n")

    assert result.columns == ["name", "amount", "joined"]
    assert result.row_count == 0
    assert raw_rows(conn) == []

    profile = profile_table(conn)
    assert profile.row_count == 0
    assert [c.fill_rate for c in profile.columns] == [0.0, 0.0, 0.0]


def test_file_without_header_gets_generated_names(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, "EMP1,25,2024-01-02\nEMP2,31,2024-02-03\nEMP3,40,2024-03-04\n")

    assert result.header_detected is False
    assert result.original_headers == []
    assert result.columns == ["column_1", "column_2", "column_3"]
    assert result.row_count == 3
    assert raw_rows(conn)[0] == (1, "EMP1", "25", "2024-01-02")


def test_first_row_is_data_toggle_overrides_detection(conn: duckdb.DuckDBPyConnection) -> None:
    text = "north,east\nsouth,west\n"
    detected = load(conn, text)
    assert detected.header_detected is True
    assert detected.row_count == 1

    forced = load(conn, text, options=IngestOptions(header=HeaderMode.FIRST_ROW_IS_DATA))
    assert forced.header_detected is False
    assert forced.header_mode is HeaderMode.FIRST_ROW_IS_DATA
    assert forced.row_count == 2
    assert raw_rows(conn) == [(1, "north", "east"), (2, "south", "west")]


def test_first_row_is_header_toggle_overrides_detection(conn: duckdb.DuckDBPyConnection) -> None:
    text = "1,2\n3,4\n"
    assert load(conn, text).header_detected is False

    forced = load(conn, text, options=IngestOptions(header=HeaderMode.FIRST_ROW_IS_HEADER))
    assert forced.header_detected is True
    assert forced.columns == ["1", "2"]
    assert raw_rows(conn) == [(1, "3", "4")]


def test_cp1252_file_is_decoded(conn: duckdb.DuckDBPyConnection) -> None:
    data = "city,price\nCafé Zürich,€5\n".encode("cp1252")

    result = load(conn, data)

    assert result.encoding == "cp1252"
    assert raw_rows(conn) == [(1, "Café Zürich", "€5")]


def test_latin1_bytes_undefined_in_cp1252_still_load(conn: duckdb.DuckDBPyConnection) -> None:
    # 0x81 has no cp1252 character, so only latin-1 can read it.
    data = b"name\nab\x81c\n"

    result = load(conn, data)

    assert result.encoding == "latin-1"
    assert raw_rows(conn) == [(1, "ab\x81c")]


def test_utf8_bom_is_not_left_on_first_header(conn: duckdb.DuckDBPyConnection) -> None:
    data = "﻿id,name\n1,Zoë\n".encode()

    result = load(conn, data)

    assert result.encoding == "utf-8-sig"
    assert result.columns == ["id", "name"]
    assert raw_rows(conn) == [(1, "1", "Zoë")]


def test_utf16_with_bom_is_decoded(conn: duckdb.DuckDBPyConnection) -> None:
    data = "id,name\n1,Łukasz\n".encode("utf-16")

    result = load(conn, data)

    assert result.encoding == "utf-16"
    assert raw_rows(conn) == [(1, "1", "Łukasz")]


def test_binary_garbage_is_rejected(conn: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(UnreadableFileError):
        load(conn, b"id,name\n\x00\x01\x02\x00\n")


def test_single_column_file(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, "email\na@example.com\nb@example.com\n")

    assert result.columns == ["email"]
    assert result.delimiter == ","
    assert raw_rows(conn) == [(1, "a@example.com"), (2, "b@example.com")]


def test_single_column_values_with_commas_inside_quotes(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, 'full name\n"Smith, Jo"\n"Lee, Al"\n')

    assert result.columns == ["full name"]
    assert raw_rows(conn) == [(1, "Smith, Jo"), (2, "Lee, Al")]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a;b;c\n1;2,5;3\n4;5,5;6\n", ";"),
        ("a\tb\n1\t2\n", "\t"),
        ("a|b\n1|2\n", "|"),
        ("a,b\n1,2\n", ","),
        ("only\none\n", ","),
    ],
)
def test_delimiter_sniffing(text: str, expected: str) -> None:
    assert sniff_delimiter(text) == expected


def test_semicolon_file_with_decimal_commas(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, "product;price\nTea;2,50\nCoffee;3,10\n")

    assert result.delimiter == ";"
    assert raw_rows(conn) == [(1, "Tea", "2,50"), (2, "Coffee", "3,10")]


def test_ragged_rows_are_padded_not_dropped(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, "a,b\n1\n2,3,extra\n")

    assert result.columns == ["a", "b", "column_3"]
    assert raw_rows(conn) == [(1, "1", None, None), (2, "2", "3", "extra")]


def test_blank_lines_are_skipped_and_counted(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, "\n\na,b\n1,2\n\n,,\n3,4\n\n")

    assert result.row_count == 2
    assert result.empty_rows_skipped == 5
    assert raw_rows(conn) == [(1, "1", "2"), (2, "3", "4")]


def test_blank_and_duplicate_headers_are_made_unique(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, "Name,,name,NAME, _row_id \nA,B,C,D,E\n")

    assert result.original_headers == ["Name", "", "name", "NAME", " _row_id "]
    assert result.columns == ["Name", "column_2", "name_2", "NAME_3", "_row_id_2"]
    assert raw_columns(conn) == [ROW_ID_COLUMN, *result.columns]


def test_hostile_column_names_are_safe(conn: duckdb.DuckDBPyConnection) -> None:
    result = load(conn, 'a"; DROP TABLE raw; --,select\n1,2\n')

    assert result.columns == ['a"; DROP TABLE raw; --', "select"]
    assert raw_rows(conn) == [(1, "1", "2")]


def test_unclosed_quote_does_not_crash(conn: duckdb.DuckDBPyConnection) -> None:
    # Python's csv reads to the end of the file for an unclosed quote rather
    # than raising, so the stray quote's text lands in one cell.
    result = load(conn, 'a,b\n1,"unterminated\n2,3\n')

    assert result.row_count == 1


def test_size_limit_rejects_large_files(conn: duckdb.DuckDBPyConnection) -> None:
    small_limit = Settings(max_upload_bytes=100)
    data = ("a,b\n" + "1,2\n" * 50).encode()

    with pytest.raises(FileTooLargeError) as excinfo:
        load(conn, data, settings=small_limit)

    assert excinfo.value.limit_bytes == 100
    assert excinfo.value.size_bytes == len(data)
    assert "limit" in excinfo.value.message


def test_file_exactly_at_size_limit_is_accepted(conn: duckdb.DuckDBPyConnection) -> None:
    data = b"a,b\n1,2\n"

    result = load(conn, data, settings=Settings(max_upload_bytes=len(data)))

    assert result.row_count == 1


def test_loading_again_replaces_the_raw_table(conn: duckdb.DuckDBPyConnection) -> None:
    load(conn, "a,b\n1,2\n")
    load(conn, "x\n9\n8\n")

    assert raw_columns(conn) == [ROW_ID_COLUMN, "x"]
    assert raw_rows(conn) == [(1, "9"), (2, "8")]


def test_large_file_loads_all_rows(conn: duckdb.DuckDBPyConnection) -> None:
    body = "".join(f"R{i},{i * 1.5},cat{i % 7}\n" for i in range(50_000))

    result = load(conn, "id,value,group\n" + body)

    assert result.row_count == 50_000
    last = conn.execute(f"SELECT * FROM {RAW_REF} ORDER BY {ROW_ID_COLUMN} DESC LIMIT 1")
    assert last.fetchone() == (50_000, "R49999", "74998.5", "cat5")
