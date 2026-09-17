"""DuckDB layout for a dataset, and helpers for putting identifiers into SQL safely.

Each dataset lives in its own workspace folder. Ingest writes the raw table to
`raw.duckdb` there; the session then attaches that file READ_ONLY as the
`source` catalog, so DuckDB itself refuses any write to the raw data. Everything
derived from it (cleaned rows, set-aside rows, the change log) goes in the
in-memory `work` schema.

Column names come from user files, so they can contain quotes, spaces, or SQL
keywords. They can't be bound as parameters, so every identifier is checked
against a known schema and then quoted.
"""

import shutil
import tempfile
from pathlib import Path

import duckdb

RAW_TABLE = "raw"
ROW_ID_COLUMN = "_row_id"
SOURCE_CATALOG = "source"
WORK_SCHEMA = "work"
RAW_DB_FILENAME = "raw.duckdb"


def quote_ident(name: str) -> str:
    if "\x00" in name:
        raise ValueError("Identifier contains a null character")
    return '"' + name.replace('"', '""') + '"'


def quote_literal(text: str) -> str:
    """For the few statements that can't take bound parameters (ATTACH, COPY TO).

    Only ever used with paths the server generates, never with user input.
    """
    if "\x00" in text:
        raise ValueError("Literal contains a null character")
    return "'" + text.replace("'", "''") + "'"


RAW_REF = f"{quote_ident(SOURCE_CATALOG)}.{quote_ident(RAW_TABLE)}"


def work_ref(table: str) -> str:
    return f"{quote_ident(WORK_SCHEMA)}.{quote_ident(table)}"


def create_workspace() -> Path:
    return Path(tempfile.mkdtemp(prefix="tidylab-"))


def remove_workspace(workspace: Path) -> None:
    shutil.rmtree(workspace, ignore_errors=True)


def raw_db_path(workspace: Path) -> Path:
    return workspace / RAW_DB_FILENAME


def attach_raw(conn: duckdb.DuckDBPyConnection, raw_path: Path) -> None:
    """Attach a raw database file read-only as `source`, replacing any earlier one."""
    conn.execute(f"DETACH DATABASE IF EXISTS {quote_ident(SOURCE_CATALOG)}")
    conn.execute(
        f"ATTACH {quote_literal(str(raw_path))} AS {quote_ident(SOURCE_CATALOG)} (READ_ONLY)"
    )
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {quote_ident(WORK_SCHEMA)}")


def open_dataset_connection(raw_path: Path) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    try:
        attach_raw(conn, raw_path)
    except BaseException:
        conn.close()
        raise
    return conn


def raw_columns(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Columns of the attached raw table, in file order, including the row id."""
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_catalog = $catalog AND table_name = $table ORDER BY ordinal_position",
        {"catalog": SOURCE_CATALOG, "table": RAW_TABLE},
    ).fetchall()
    return [str(row[0]) for row in rows]
