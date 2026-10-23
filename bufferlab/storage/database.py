"""SQLite connection management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bufferlab.storage.migrations import migrate
from bufferlab.utils.paths import db_path


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open (creating and migrating if needed) the BufferLab database.

    ``check_same_thread=False`` lets the TUI's worker thread save results; callers
    serialise access with the repository's lock.
    """
    target = str(path) if path is not None else str(db_path())
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn
