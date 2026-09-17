"""Load any supported file into a DuckDB table named `raw`.

The connection passed in is a writable database file in the dataset's
workspace; sessions later attach that file read-only (see app/db.py).

Every value is stored as text exactly as it appeared (blank cells become NULL),
plus a `_row_id` column holding each row's position in the file. Nothing is
parsed or cleaned here; that happens later and never touches this table.
"""

import csv
import itertools
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

import duckdb

from app.config import Settings
from app.db import RAW_TABLE, ROW_ID_COLUMN, quote_ident
from app.errors import EmptyFileError, FileTooLargeError
from app.ingest.base import FileAdapter, detect_format
from app.ingest.csv_adapter import CsvAdapter
from app.ingest.header import clean_column_names, resolve_header
from app.ingest.models import IngestOptions, IngestResult, SourceFormat
from app.ingest.xlsx_adapter import XlsxAdapter

_ADAPTERS: dict[SourceFormat, FileAdapter] = {
    SourceFormat.CSV: CsvAdapter(),
    SourceFormat.XLSX: XlsxAdapter(),
}
_HEADER_SAMPLE_ROWS = 200


class _SkipEmptyRows:
    """Drops rows with no values and counts them, so the count can be reported."""

    def __init__(self) -> None:
        self.skipped = 0

    def __call__(self, rows: Iterable[list[str | None]]) -> Iterator[list[str | None]]:
        for row in rows:
            # Trailing empty cells come from ragged rows or Excel formatting, not data.
            while row and row[-1] is None:
                row.pop()
            if row:
                yield row
            else:
                self.skipped += 1


def ingest(
    conn: duckdb.DuckDBPyConnection,
    filename: str,
    data: bytes,
    options: IngestOptions,
    settings: Settings,
) -> IngestResult:
    if len(data) > settings.max_upload_bytes:
        raise FileTooLargeError(len(data), settings.max_upload_bytes)
    if data.strip() == b"":
        raise EmptyFileError()

    source_format = detect_format(filename, data)
    source = _ADAPTERS[source_format].read(data, options)

    skip_empty = _SkipEmptyRows()
    rows = skip_empty(source.rows)
    head = list(itertools.islice(rows, _HEADER_SAMPLE_ROWS))
    if not head:
        raise EmptyFileError()

    has_header = resolve_header(options.header, head)
    original_headers = [value or "" for value in head[0]] if has_header else []
    data_rows = itertools.chain(head[1:] if has_header else head, rows)

    with tempfile.TemporaryDirectory(prefix="ingest-") as tmp:
        path = Path(tmp) / "rows.csv"
        row_count, width = _write_normalized_csv(path, data_rows)
        width = max(width, len(original_headers))
        columns = clean_column_names(list(original_headers), width)
        _load_raw_table(conn, path, columns)

    return IngestResult(
        filename=filename,
        format=source_format,
        encoding=source.encoding,
        delimiter=source.delimiter,
        sheet_name=source.sheet_name,
        available_sheets=source.available_sheets,
        header_mode=options.header,
        header_detected=has_header,
        original_headers=original_headers,
        columns=columns,
        row_count=row_count,
        empty_rows_skipped=skip_empty.skipped,
    )


def ingest_to_file(
    raw_path: Path,
    filename: str,
    data: bytes,
    options: IngestOptions,
    settings: Settings,
) -> IngestResult:
    """Ingest into a new database file, closing it so it can be attached read-only."""
    conn = duckdb.connect(str(raw_path))
    try:
        return ingest(conn, filename, data, options, settings)
    finally:
        conn.close()


def _write_normalized_csv(path: Path, rows: Iterable[list[str | None]]) -> tuple[int, int]:
    """Write rows with a leading row id, returning (row count, widest row)."""
    row_count = width = 0
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        for row in rows:
            row_count += 1
            width = max(width, len(row))
            writer.writerow([row_count, *("" if v is None else v for v in row)])
    return row_count, width


def _load_raw_table(conn: duckdb.DuckDBPyConnection, path: Path, columns: list[str]) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {quote_ident(RAW_TABLE)}")
    column_defs = ", ".join(
        [f"{quote_ident(ROW_ID_COLUMN)} BIGINT"] + [f"{quote_ident(c)} VARCHAR" for c in columns]
    )
    conn.execute(f"CREATE TABLE {quote_ident(RAW_TABLE)} ({column_defs})")

    column_types = {ROW_ID_COLUMN: "BIGINT", **dict.fromkeys(columns, "VARCHAR")}
    # Everything is spelled out so DuckDB doesn't guess types, headers, or quoting.
    conn.execute(
        f"INSERT INTO {quote_ident(RAW_TABLE)} "
        "SELECT * FROM read_csv($path, header = false, delim = ',', quote = '\"', "
        "escape = '\"', columns = $columns, null_padding = true, auto_detect = false, "
        "parallel = false)",
        {"path": str(path), "columns": column_types},
    )
