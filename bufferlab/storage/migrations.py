"""Forward-only schema migrations keyed on ``PRAGMA user_version``."""

from __future__ import annotations

import sqlite3

MIGRATIONS: list[str] = [
    # 1: initial schema
    """
    CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        name TEXT NOT NULL,
        scenario TEXT,
        algorithm TEXT NOT NULL,
        seed INTEGER NOT NULL,
        duration_s REAL NOT NULL,
        config_json TEXT NOT NULL,
        resolved_params_json TEXT NOT NULL,
        metrics_json TEXT NOT NULL,
        terminated TEXT NOT NULL,
        events_processed INTEGER NOT NULL,
        wall_time_s REAL NOT NULL,
        software_version TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        batch_id TEXT,
        replicate INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_runs_created ON runs(created_at);
    CREATE INDEX idx_runs_batch ON runs(batch_id);
    CREATE TABLE run_series (
        run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
        data BLOB NOT NULL
    );
    CREATE TABLE batches (
        batch_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        name TEXT NOT NULL,
        spec_json TEXT NOT NULL
    );
    CREATE TABLE saved_configs (
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        config_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (name, kind)
    );
    """,
]


def migrate(conn: sqlite3.Connection) -> int:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, script in enumerate(MIGRATIONS, start=1):
        if version > current:
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
    return len(MIGRATIONS)
