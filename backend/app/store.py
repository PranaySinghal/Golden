"""In-memory dataset sessions. Nothing outlives the server process (a stated non-goal).

Each dataset gets its own in-memory DuckDB database, so datasets can't see each
other's tables and removing one frees its memory by closing the connection.
"""

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime

import duckdb

from app.config import Settings
from app.errors import DatasetNotFoundError
from app.ingest.loader import ingest
from app.ingest.models import IngestOptions, IngestResult
from app.profile.models import DatasetProfile
from app.profile.profiler import profile_table


@dataclass
class DatasetSession:
    id: str
    created_at: datetime
    filename: str
    # Kept so the file can be read again with different options (such as
    # "first row is data") without asking the user to upload it again.
    source_bytes: bytes
    options: IngestOptions
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
        conn, result, profile = self._load(filename, data, options)
        session = DatasetSession(
            id=uuid.uuid4().hex,
            created_at=datetime.now(UTC),
            filename=filename,
            source_bytes=data,
            options=options,
            conn=conn,
            ingest=result,
            profile=profile,
        )
        with self._lock:
            self._sessions[session.id] = session
            evicted = self._evict_over_limit()
        for old in evicted:
            old.conn.close()
        return session

    def get(self, dataset_id: str) -> DatasetSession:
        with self._lock:
            session = self._sessions.get(dataset_id)
        if session is None:
            raise DatasetNotFoundError(dataset_id)
        return session

    def reingest(self, dataset_id: str, options: IngestOptions) -> DatasetSession:
        """Read the same file again with new options, keeping the dataset id.

        If reading fails, the existing session is left untouched.
        """
        current = self.get(dataset_id)
        conn, result, profile = self._load(current.filename, current.source_bytes, options)
        replacement = DatasetSession(
            id=current.id,
            created_at=current.created_at,
            filename=current.filename,
            source_bytes=current.source_bytes,
            options=options,
            conn=conn,
            ingest=result,
            profile=profile,
        )
        with self._lock:
            if dataset_id not in self._sessions:
                conn.close()
                raise DatasetNotFoundError(dataset_id)
            self._sessions[dataset_id] = replacement
        current.conn.close()
        return replacement

    def delete(self, dataset_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(dataset_id, None)
        if session is None:
            raise DatasetNotFoundError(dataset_id)
        session.conn.close()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _load(
        self, filename: str, data: bytes, options: IngestOptions
    ) -> tuple[duckdb.DuckDBPyConnection, IngestResult, DatasetProfile]:
        conn = duckdb.connect(":memory:")
        try:
            result = ingest(conn, filename, data, options, self._settings)
            profile = profile_table(conn)
        except BaseException:
            conn.close()
            raise
        return conn, result, profile

    def _evict_over_limit(self) -> list[DatasetSession]:
        evicted: list[DatasetSession] = []
        while len(self._sessions) > self._settings.max_datasets:
            _, oldest = self._sessions.popitem(last=False)
            evicted.append(oldest)
        return evicted
