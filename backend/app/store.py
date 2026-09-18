"""In-memory dataset sessions. Nothing outlives the server process (a stated non-goal).

Each dataset gets a workspace folder holding its raw table as a DuckDB file,
attached read-only to the session's own in-memory database. Datasets can't see
each other's tables, and closing a session deletes its workspace.
"""

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from app.compare.compare import AnswerCache
from app.config import Settings
from app.db import create_workspace, open_dataset_connection, raw_db_path, remove_workspace
from app.detectors.models import Issue
from app.errors import DatasetNotFoundError
from app.ingest.loader import ingest_to_file
from app.ingest.models import IngestOptions, IngestResult
from app.profile.models import DatasetProfile
from app.profile.profiler import profile_table
from app.questions.models import Question
from app.steps.apply import ApplyResult
from app.steps.models import Recipe
from app.steps.recipe_ops import RecipeHistory
from app.steps.schema import StageSchema, base_schema


@dataclass
class DatasetSession:
    id: str
    created_at: datetime
    filename: str
    # Kept so the file can be read again with different options (such as
    # "first row is data") without asking the user to upload it again.
    source_bytes: bytes
    options: IngestOptions
    workspace: Path
    conn: duckdb.DuckDBPyConnection
    ingest: IngestResult
    profile: DatasetProfile
    recipe: Recipe = field(default_factory=Recipe)
    history: RecipeHistory = field(default_factory=RecipeHistory)
    applied: ApplyResult | None = None
    # What review found, worked out once and kept: detection and impact scoring
    # cost a second or two, and neither changes until the file is read again.
    issues: list[Issue] | None = None
    questions: list[Question] | None = None
    answer_cache: AnswerCache = field(default_factory=dict)
    safe_applied: bool = False
    # Which ask-tier question got which answer, and which suggestions the user
    # turned down. The recipe says what runs; these say what the user decided.
    answers: dict[str, str] = field(default_factory=dict)
    rejected: set[str] = field(default_factory=set)
    # Which issue each step came from, for showing them together in the panel.
    step_origin: dict[str, str] = field(default_factory=dict)
    # One DuckDB connection isn't safe to use from two threads at once.
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def base_schema(self) -> StageSchema:
        return base_schema(self.profile)

    def close(self) -> None:
        with self.lock:
            self.conn.close()
        remove_workspace(self.workspace)


@dataclass(frozen=True)
class _Loaded:
    workspace: Path
    conn: duckdb.DuckDBPyConnection
    ingest: IngestResult
    profile: DatasetProfile


class DatasetStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sessions: OrderedDict[str, DatasetSession] = OrderedDict()
        self._lock = threading.Lock()

    def create(
        self, filename: str, data: bytes, options: IngestOptions | None = None
    ) -> DatasetSession:
        options = options or IngestOptions()
        # Loading happens outside the lock: it's the slow part and touches no shared state.
        loaded = self._load(filename, data, options)
        session = DatasetSession(
            id=uuid.uuid4().hex,
            created_at=datetime.now(UTC),
            filename=filename,
            source_bytes=data,
            options=options,
            workspace=loaded.workspace,
            conn=loaded.conn,
            ingest=loaded.ingest,
            profile=loaded.profile,
        )
        with self._lock:
            self._sessions[session.id] = session
            evicted = self._evict_over_limit()
        for old in evicted:
            old.close()
        return session

    def get(self, dataset_id: str) -> DatasetSession:
        with self._lock:
            session = self._sessions.get(dataset_id)
        if session is None:
            raise DatasetNotFoundError(dataset_id)
        return session

    def reingest(self, dataset_id: str, options: IngestOptions) -> DatasetSession:
        """Read the same file again with new options, keeping the dataset id.

        The columns can change (for example when the first row becomes data), so
        the recipe starts empty. If reading fails, the existing session is left
        untouched.
        """
        current = self.get(dataset_id)
        loaded = self._load(current.filename, current.source_bytes, options)
        replacement = DatasetSession(
            id=current.id,
            created_at=current.created_at,
            filename=current.filename,
            source_bytes=current.source_bytes,
            options=options,
            workspace=loaded.workspace,
            conn=loaded.conn,
            ingest=loaded.ingest,
            profile=loaded.profile,
        )
        with self._lock:
            if dataset_id not in self._sessions:
                replacement.close()
                raise DatasetNotFoundError(dataset_id)
            self._sessions[dataset_id] = replacement
        current.close()
        return replacement

    def delete(self, dataset_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(dataset_id, None)
        if session is None:
            raise DatasetNotFoundError(dataset_id)
        session.close()

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _load(self, filename: str, data: bytes, options: IngestOptions) -> _Loaded:
        workspace = create_workspace()
        conn: duckdb.DuckDBPyConnection | None = None
        try:
            result = ingest_to_file(raw_db_path(workspace), filename, data, options, self._settings)
            conn = open_dataset_connection(raw_db_path(workspace))
            profile = profile_table(conn)
        except BaseException:
            if conn is not None:
                conn.close()
            remove_workspace(workspace)
            raise
        return _Loaded(workspace=workspace, conn=conn, ingest=result, profile=profile)

    def _evict_over_limit(self) -> list[DatasetSession]:
        evicted: list[DatasetSession] = []
        while len(self._sessions) > self._settings.max_datasets:
            _, oldest = self._sessions.popitem(last=False)
            evicted.append(oldest)
        return evicted
