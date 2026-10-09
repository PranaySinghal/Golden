"""Download formats: the cleaned table as CSV, and the recipe as JSON."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from app.db import ROW_ID_COLUMN, quote_ident, quote_literal, work_ref
from app.profile.patterns import PLAIN_NUMBER, full_match
from app.steps.apply import CLEANED_TABLE, ApplyResult
from app.steps.models import Recipe, RecipeFile, RecipeSource, without_snapshots
from app.steps.replay import required_columns
from app.steps.schema import StageSchema, ValueKind, text_of

# Spreadsheet apps run a cell starting with one of these as a formula, which a
# hostile file can abuse. A leading apostrophe makes the app show it as text.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
_UTF8_BOM = "﻿".encode()


def guard_formula(text: str) -> str:
    if text.startswith(_FORMULA_STARTS) and not full_match(PLAIN_NUMBER, text):
        return "'" + text
    return text


def cleaned_csv_bytes(
    conn: duckdb.DuckDBPyConnection, result: ApplyResult, scratch_dir: Path
) -> bytes:
    """The cleaned rows in file order, without the internal row id.

    Starts with a UTF-8 byte order mark so Excel shows accented text correctly.
    """
    columns = []
    for column in result.columns:
        value = text_of(quote_ident(column.name), column.kind)
        if column.kind is ValueKind.TEXT:
            # COPY can't take bound parameters; the pattern is a fixed constant.
            value = (
                f"CASE WHEN regexp_matches({value}, '^[=+\\-@\\t\\r]') "
                f"AND NOT regexp_full_match({value}, {quote_literal(PLAIN_NUMBER)}) "
                f"THEN '''' || {value} ELSE {value} END"
            )
        columns.append(f"{value} AS {quote_ident(guard_formula(column.name))}")

    path = scratch_dir / f"export-{uuid.uuid4().hex}.csv"
    select = ", ".join(columns) if columns else "NULL AS empty"
    try:
        conn.execute(
            f"COPY (SELECT {select} FROM {work_ref(CLEANED_TABLE)} "
            f"ORDER BY {quote_ident(ROW_ID_COLUMN)}) "
            f"TO {quote_literal(str(path))} (FORMAT csv, HEADER true)"
        )
        return _UTF8_BOM + path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def build_recipe_file(
    recipe: Recipe, base: StageSchema, source_filename: str, now: datetime | None = None
) -> RecipeFile:
    return RecipeFile(
        created_at=now or datetime.now(UTC),
        source=RecipeSource(filename=source_filename, columns=base.names()),
        requires_columns=required_columns(recipe, base),
        recipe=without_snapshots(recipe),
    )


def recipe_file_bytes(recipe_file: RecipeFile) -> bytes:
    return recipe_file.model_dump_json(indent=2).encode()
