"""Persistence for runs, batches and saved configurations."""

from __future__ import annotations

import json
import sqlite3
import threading
import zlib
from pathlib import Path
from typing import Any

from bufferlab.experiments.batch import BatchSpec
from bufferlab.experiments.models import ExperimentConfig, RunRecord, utc_now
from bufferlab.storage.database import connect


class NotFoundError(LookupError):
    pass


class AmbiguousIdError(LookupError):
    pass


class Repository:
    """All database access.  Thread-safe (single connection guarded by a lock).

    Per-run time series are bounded (<= ``series_bins`` points per channel) and are
    stored zlib-compressed in a separate table.  Raw packet traces are never stored.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.conn = connect(path)
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # -- runs ----------------------------------------------------------------
    def save_run(self, rec: RunRecord, with_series: bool = True) -> None:
        c = rec.config
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rec.run_id,
                    rec.created_at,
                    c.name,
                    c.scenario,
                    c.algorithm,
                    c.seed,
                    c.duration_s,
                    json.dumps(c.to_dict()),
                    json.dumps(rec.resolved_params),
                    json.dumps(rec.metrics),
                    rec.terminated,
                    rec.events_processed,
                    rec.wall_time_s,
                    rec.software_version,
                    rec.schema_version,
                    rec.batch_id,
                    rec.replicate,
                ),
            )
            if with_series and rec.series:
                self.conn.execute(
                    "INSERT OR REPLACE INTO run_series VALUES (?,?)",
                    (rec.run_id, zlib.compress(json.dumps(rec.series).encode())),
                )

    def _row_to_run(self, row: sqlite3.Row, with_series: bool = True) -> RunRecord:
        series: dict[str, Any] = {}
        if with_series:
            s = self.conn.execute(
                "SELECT data FROM run_series WHERE run_id=?", (row["run_id"],)
            ).fetchone()
            if s:
                series = json.loads(zlib.decompress(s["data"]))
        return RunRecord(
            run_id=row["run_id"],
            created_at=row["created_at"],
            config=ExperimentConfig.from_dict(json.loads(row["config_json"])),
            resolved_params=json.loads(row["resolved_params_json"]),
            metrics=json.loads(row["metrics_json"]),
            series=series,
            terminated=row["terminated"],
            events_processed=row["events_processed"],
            wall_time_s=row["wall_time_s"],
            software_version=row["software_version"],
            schema_version=row["schema_version"],
            batch_id=row["batch_id"],
            replicate=row["replicate"],
        )

    def resolve_id(self, ref: str) -> str:
        """Accept a full run id or an unambiguous prefix."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT run_id FROM runs WHERE run_id LIKE ? ESCAPE '\\'",
                (ref.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",),
            ).fetchall()
        exact = [r["run_id"] for r in rows if r["run_id"] == ref]
        if exact:
            return exact[0]
        if not rows:
            raise NotFoundError(f"no run matches {ref!r}")
        if len(rows) > 1:
            raise AmbiguousIdError(f"{ref!r} is ambiguous ({len(rows)} matches)")
        return rows[0]["run_id"]

    def get_run(self, ref: str, with_series: bool = True) -> RunRecord:
        run_id = self.resolve_id(ref)
        with self._lock:
            row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            return self._row_to_run(row, with_series)

    def list_runs(
        self,
        search: str | None = None,
        algorithm: str | None = None,
        scenario: str | None = None,
        batch_id: str | None = None,
        limit: int | None = None,
    ) -> list[RunRecord]:
        """Newest first.  ``search`` matches id, name, scenario or algorithm (substring)."""
        sql = "SELECT * FROM runs WHERE 1=1"
        args: list[Any] = []
        if search:
            sql += " AND (run_id LIKE ? OR name LIKE ? OR scenario LIKE ? OR algorithm LIKE ?)"
            args += [f"%{search}%"] * 4
        if algorithm:
            sql += " AND algorithm = ?"
            args.append(algorithm)
        if scenario:
            sql += " AND scenario = ?"
            args.append(scenario)
        if batch_id:
            sql += " AND batch_id = ?"
            args.append(batch_id)
        sql += " ORDER BY created_at DESC, rowid DESC"
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
            return [self._row_to_run(r, with_series=False) for r in rows]

    def delete_run(self, ref: str) -> str:
        run_id = self.resolve_id(ref)
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
        return run_id

    def count_runs(self) -> int:
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    # -- batches ---------------------------------------------------------------
    def save_batch(self, batch_id: str, spec: BatchSpec) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO batches VALUES (?,?,?,?)",
                (batch_id, utc_now(), spec.name, json.dumps(spec.to_dict())),
            )

    def get_batch(self, batch_id: str) -> tuple[BatchSpec, list[RunRecord]]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM batches WHERE batch_id LIKE ?", (batch_id + "%",)
            ).fetchone()
            if not row:
                raise NotFoundError(f"no batch matches {batch_id!r}")
            rows = self.conn.execute(
                "SELECT * FROM runs WHERE batch_id=? ORDER BY created_at, rowid", (row["batch_id"],)
            ).fetchall()
            return BatchSpec.from_dict(json.loads(row["spec_json"])), [
                self._row_to_run(r, with_series=False) for r in rows
            ]

    def list_batches(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT b.batch_id, b.created_at, b.name, COUNT(r.run_id) AS n_runs "
                "FROM batches b LEFT JOIN runs r ON r.batch_id=b.batch_id "
                "GROUP BY b.batch_id ORDER BY b.created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # -- saved configs -----------------------------------------------------------
    def save_config(self, name: str, kind: str, payload: dict[str, Any]) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO saved_configs VALUES (?,?,?,?)",
                (name, kind, json.dumps(payload), utc_now()),
            )

    def list_configs(self, kind: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT name, config_json FROM saved_configs WHERE kind=? ORDER BY name", (kind,)
            ).fetchall()
            return {r["name"]: json.loads(r["config_json"]) for r in rows}

    def delete_config(self, name: str, kind: str) -> None:
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM saved_configs WHERE name=? AND kind=?", (name, kind))
