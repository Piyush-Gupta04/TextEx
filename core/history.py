"""
core/history.py
===============
SQLite-backed OCR history manager for Smart Text Extractor.

Stores every successful OCR extraction with metadata (timestamp, text,
word/char counts, language, processing duration).  Enforces a configurable
entry limit by pruning the oldest records when the ceiling is hit.

Database location: database/history.db (relative to the project root).

Thread safety: SQLite connections are NOT shared across threads.
              _get_conn() opens a per-thread connection using
              threading.local() so background workers can safely
              call add() without locking.

Usage:
    mgr = HistoryManager(limit=500)
    mgr.add("Hello World", language="en", duration=1.23)
    records = mgr.get_all()
    mgr.delete(record_id)
    mgr.close()
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional

import pathlib as _pathlib

# Always resolve the database path relative to this source file, not CWD.
# Without this, the DB ends up in whichever directory the user ran the app
# from, which can differ between terminal launches and double-click launches.
_PROJECT_ROOT = _pathlib.Path(__file__).resolve().parent.parent
DB_PATH = str(_PROJECT_ROOT / "database" / "history.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT    NOT NULL,
    text      TEXT    NOT NULL,
    words     INTEGER NOT NULL DEFAULT 0,
    chars     INTEGER NOT NULL DEFAULT 0,
    language  TEXT    NOT NULL DEFAULT 'en',
    duration  REAL    NOT NULL DEFAULT 0.0
);
"""


class HistoryManager:
    """
    Manages the OCR extraction history stored in a local SQLite database.

    Each call to add() inserts a new record and prunes old ones when
    the total count exceeds `limit`.
    """

    def __init__(self, limit: int = 500) -> None:
        """
        Create (or open) the history database.

        Args:
            limit: Maximum number of history entries to retain.
        """
        self.limit = limit
        self._local = threading.local()
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        # Initialise schema on the calling thread
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    # ── Connection management ─────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection, creating one if needed."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    # ── CRUD ──────────────────────────────────────────────────────────────

    def add(
        self,
        text: str,
        language: str = "en",
        duration: float = 0.0,
    ) -> int:
        """
        Insert a new OCR result into history.

        Args:
            text:     Extracted text string.
            language: OCR language code used ("en", "hi", "ch").
            duration: OCR processing time in seconds.

        Returns:
            The rowid of the newly inserted record.
        """
        if not text.strip():
            return -1

        words = len(text.split())
        chars = len(text)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = self._get_conn()
        cur = conn.execute(
            "INSERT INTO history (timestamp, text, words, chars, language, duration) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, text, words, chars, language, round(duration, 3)),
        )
        conn.commit()
        self._enforce_limit(conn)
        return cur.lastrowid

    def get_all(self) -> list[dict]:
        """
        Return all history records, newest first.

        Returns:
            List of dicts with keys: id, timestamp, text, words, chars,
            language, duration.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, timestamp, text, words, chars, language, duration "
            "FROM history ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_id(self, record_id: int) -> Optional[dict]:
        """Fetch a single record by its primary key, or None."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, timestamp, text, words, chars, language, duration "
            "FROM history WHERE id = ?",
            (record_id,),
        ).fetchone()
        return dict(row) if row else None

    def delete(self, record_id: int) -> None:
        """Delete the record with the given id."""
        conn = self._get_conn()
        conn.execute("DELETE FROM history WHERE id = ?", (record_id,))
        conn.commit()

    def clear(self) -> None:
        """Delete all history records."""
        conn = self._get_conn()
        conn.execute("DELETE FROM history")
        conn.commit()

    def count(self) -> int:
        """Return the total number of stored records."""
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]

    # ── Internal ──────────────────────────────────────────────────────────

    def _enforce_limit(self, conn: sqlite3.Connection) -> None:
        """Prune oldest records if total exceeds self.limit."""
        conn.execute(
            "DELETE FROM history WHERE id NOT IN "
            "(SELECT id FROM history ORDER BY id DESC LIMIT ?)",
            (self.limit,),
        )
        conn.commit()

    def close(self) -> None:
        """Close the thread-local database connection."""
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None
