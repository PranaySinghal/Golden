"""Answers we've already paid for, kept on disk so a restart doesn't ask again.

One SQLite file. It holds what was looked up and what came back: a postal code
and its position, a stock symbol and its price. Never a row, a file name or a
dataset id, so nothing in it says whose file a value came from. This is the
one thing in the app that outlives the server process (see docs/decisions.md).

Whether an entry is still good is the caller's question (freshness.py); the
cache only remembers when it was fetched.
"""

import logging
import sqlite3
import threading
from pathlib import Path

from app.connectors.models import LookupResult, Status

logger = logging.getLogger("tidylab.connectors")


class LookupCache:
    def __init__(self, path: str = "") -> None:
        """`path` is a file to keep answers in; empty keeps them in memory only."""
        self._conn = self._open(path)
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS lookups (provider TEXT NOT NULL, key TEXT NOT NULL, "
                "status TEXT NOT NULL, value1 TEXT, value2 TEXT, fetched_at TEXT NOT NULL, "
                "PRIMARY KEY (provider, key))"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS documents (name TEXT PRIMARY KEY, "
                "body TEXT NOT NULL, fetched_at TEXT NOT NULL)"
            )

    @staticmethod
    def _open(path: str) -> sqlite3.Connection:
        # One connection shared by request threads, guarded by the lock.
        if path:
            target = Path(path).expanduser()
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                return sqlite3.connect(str(target), check_same_thread=False)
            except (OSError, sqlite3.Error):
                # A disk we can't write to costs repeat lookups, not the feature.
                logger.warning("connector cache file can't be opened; keeping answers in memory")
        return sqlite3.connect(":memory:", check_same_thread=False)

    def get(self, provider: str, key: str) -> LookupResult | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT status, value1, value2, fetched_at FROM lookups "
                "WHERE provider = ? AND key = ?",
                (provider, key),
            ).fetchone()
        if row is None:
            return None
        return LookupResult(Status(row[0]), row[1], row[2], row[3])

    def put(self, provider: str, key: str, result: LookupResult) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO lookups VALUES (?, ?, ?, ?, ?, ?)",
                (provider, key, result.status.value, result.value1, result.value2,
                 result.fetched_at or ""),
            )  # fmt: skip

    def get_document(self, name: str) -> tuple[str, str] | None:
        """A whole downloaded list (body, fetched_at), such as the companies list."""
        with self._lock:
            row = self._conn.execute(
                "SELECT body, fetched_at FROM documents WHERE name = ?", (name,)
            ).fetchone()
        return (row[0], row[1]) if row else None

    def put_document(self, name: str, body: str, fetched_at: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO documents VALUES (?, ?, ?)", (name, body, fetched_at)
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
