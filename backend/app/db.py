"""Helpers for putting identifiers into DuckDB SQL safely.

Column names come from user files, so they can contain quotes, spaces, or SQL
keywords. They can't be bound as parameters, so every identifier is checked
against the table's real columns and then quoted.
"""

import duckdb

RAW_TABLE = "raw"
ROW_ID_COLUMN = "_row_id"


def quote_ident(name: str) -> str:
    if "\x00" in name:
        raise ValueError("Identifier contains a null character")
    return '"' + name.replace('"', '""') + '"'


def table_columns(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = $table ORDER BY ordinal_position",
        {"table": table},
    ).fetchall()
    return [str(row[0]) for row in rows]


def checked_column(conn: duckdb.DuckDBPyConnection, table: str, name: str) -> str:
    """Return the quoted identifier, or raise if the column isn't in the table."""
    if name not in table_columns(conn, table):
        raise ValueError(f"Unknown column {name!r} in table {table!r}")
    return quote_ident(name)
