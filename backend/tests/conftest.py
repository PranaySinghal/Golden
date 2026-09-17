import hashlib
import io
from collections.abc import Callable, Iterator, Sequence
from datetime import date
from pathlib import Path

import duckdb
import pytest
from openpyxl import Workbook

from app.config import Settings
from app.db import (
    RAW_REF,
    ROW_ID_COLUMN,
    SOURCE_CATALOG,
    attach_raw,
    create_workspace,
    quote_ident,
    raw_db_path,
    remove_workspace,
)
from app.detectors.models import Issue
from app.detectors.registry import detect_issues
from app.ingest.loader import ingest_to_file
from app.ingest.models import IngestOptions, IngestResult
from app.profile.models import ColumnProfile
from app.profile.profiler import profile_column, profile_table
from app.profile.stats import ColumnStats, compute_column_stats, count_rows
from app.steps.apply import ApplyResult, apply_recipe
from app.steps.models import Recipe, Step
from app.steps.schema import base_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = REPO_ROOT / "data" / "samples"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
# Detection takes "today" as input so date checks don't drift as time passes.
TODAY = date(2026, 9, 16)

_workspaces: list[Path] = []


@pytest.fixture(autouse=True, scope="session")
def _remove_test_workspaces() -> Iterator[None]:
    yield
    for workspace in _workspaces:
        remove_workspace(workspace)


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
    """Ingest into a fresh raw file and attach it read-only to `conn`, like a session does."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    workspace = create_workspace()
    _workspaces.append(workspace)
    result = ingest_to_file(
        raw_db_path(workspace), filename, raw, options or IngestOptions(), settings or Settings()
    )
    attach_raw(conn, raw_db_path(workspace))
    return result


def raw_rows(conn: duckdb.DuckDBPyConnection) -> list[tuple[object, ...]]:
    order = quote_ident(ROW_ID_COLUMN)
    return conn.execute(f"SELECT * FROM {RAW_REF} ORDER BY {order}").fetchall()


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
        connection.execute(f"ATTACH ':memory:' AS {quote_ident(SOURCE_CATALOG)}")
        connection.execute(
            f"CREATE TABLE {RAW_REF} "
            f"({quote_ident(ROW_ID_COLUMN)} BIGINT, {quote_ident(name)} VARCHAR)"
        )
        if values:
            connection.executemany(
                f"INSERT INTO {RAW_REF} VALUES (?, ?)",
                [(index + 1, value) for index, value in enumerate(values)],
            )
        return compute_column_stats(connection, name, 0, count_rows(connection))
    finally:
        connection.close()


def profile_values(values: Sequence[str | None], name: str = "values") -> ColumnProfile:
    return profile_column(column_stats(values, name))


class Dataset:
    """A loaded file with its profile, for exercising recipes in tests."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self.conn = conn
        self.profile = profile_table(conn)
        self.base = base_schema(self.profile)
        self.result: ApplyResult | None = None

    def apply(self, *steps: Step, lineage: bool = True) -> ApplyResult:
        return self.apply_recipe(Recipe(steps=list(steps)), lineage=lineage)

    def apply_recipe(self, recipe: Recipe, lineage: bool = True) -> ApplyResult:
        self.result = apply_recipe(self.conn, recipe, self.base, lineage=lineage)
        return self.result

    def column(self, name: str) -> list[object]:
        return [
            row[0]
            for row in self.conn.execute(
                f"SELECT {quote_ident(name)} FROM work.cleaned ORDER BY _row_id"
            ).fetchall()
        ]

    def row_ids(self) -> list[int]:
        return [row[0] for row in self.conn.execute("SELECT _row_id FROM work.cleaned").fetchall()]

    def cleaned(self) -> list[tuple[object, ...]]:
        return self.conn.execute("SELECT * FROM work.cleaned ORDER BY _row_id").fetchall()

    def set_aside(self) -> list[tuple[object, ...]]:
        return self.conn.execute(
            "SELECT _row_id, step_id, reason FROM work.set_aside ORDER BY step_index, _row_id"
        ).fetchall()

    def changes(self) -> list[tuple[object, ...]]:
        return self.conn.execute(
            "SELECT row_id, column_name, step_id, before, after, kind FROM work.changes "
            "ORDER BY step_index, row_id, column_name"
        ).fetchall()

    def issues(self, detector: str | None = None) -> list[Issue]:
        found = detect_issues(self.conn, self.profile, TODAY)
        return [i for i in found if detector is None or i.detector.value == detector]

    def raw_fingerprint(self) -> str:
        rows = self.conn.execute(f"SELECT * FROM {RAW_REF} ORDER BY _row_id").fetchall()
        return hashlib.sha256(repr(rows).encode()).hexdigest()


@pytest.fixture
def make_dataset() -> Iterator[Callable[..., Dataset]]:
    connections: list[duckdb.DuckDBPyConnection] = []

    def build(data: bytes | str, filename: str = "file.csv") -> Dataset:
        connection = duckdb.connect(":memory:")
        connections.append(connection)
        load(connection, data, filename=filename)
        return Dataset(connection)

    yield build
    for connection in connections:
        connection.close()
