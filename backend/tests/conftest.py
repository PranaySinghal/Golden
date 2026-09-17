import io
from collections.abc import Iterator, Sequence
from pathlib import Path

import duckdb
import pytest
from openpyxl import Workbook

from app.config import Settings
from app.db import RAW_TABLE, ROW_ID_COLUMN, quote_ident
from app.ingest.loader import ingest
from app.ingest.models import IngestOptions, IngestResult
from app.profile.models import ColumnProfile
from app.profile.profiler import profile_column
from app.profile.stats import ColumnStats, compute_column_stats, count_rows

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = REPO_ROOT / "data" / "samples"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    yield connection
    connection.close()


def load(
    conn: duckdb.DuckDBPyConnection,
    data: bytes | str,
    filename: str = "file.csv",
    options: IngestOptions | None = None,
    settings: Settings | None = None,
) -> IngestResult:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return ingest(conn, filename, raw, options or IngestOptions(), settings or Settings())


def raw_rows(conn: duckdb.DuckDBPyConnection) -> list[tuple[object, ...]]:
    table = quote_ident(RAW_TABLE)
    return conn.execute(f"SELECT * FROM {table} ORDER BY {quote_ident(ROW_ID_COLUMN)}").fetchall()


def make_xlsx(sheets: dict[str, list[list[object]]], hidden: set[str] | None = None) -> bytes:
    workbook = Workbook()
    default = workbook.active
    assert default is not None
    workbook.remove(default)
    for title, rows in sheets.items():
        ws = workbook.create_sheet(title)
        for row in rows:
            ws.append(row)
        if hidden and title in hidden:
            ws.sheet_state = "hidden"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def column_stats(values: Sequence[str | None], name: str = "values") -> ColumnStats:
    """Stats for a single column built straight from values, bypassing file parsing."""
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            f"CREATE TABLE {quote_ident(RAW_TABLE)} "
            f"({quote_ident(ROW_ID_COLUMN)} BIGINT, {quote_ident(name)} VARCHAR)"
        )
        if values:
            connection.executemany(
                f"INSERT INTO {quote_ident(RAW_TABLE)} VALUES (?, ?)",
                [(index + 1, value) for index, value in enumerate(values)],
            )
        return compute_column_stats(connection, name, 0, count_rows(connection))
    finally:
        connection.close()


def profile_values(values: Sequence[str | None], name: str = "values") -> ColumnProfile:
    return profile_column(column_stats(values, name))
