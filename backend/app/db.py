"""Persistencia en SQLite. Todo lo almacenado se puede recalcular desde las APIs,
así que un disco efímero (planes gratuitos) solo significa esperar a la próxima ingesta."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .models import SEVERITY_RANK, Alert, Current, Hourly, Quake

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    location_id  TEXT PRIMARY KEY,
    fetched_at   TEXT NOT NULL,
    current_json TEXT NOT NULL,
    hourly_json  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    key           TEXT PRIMARY KEY,
    severity_rank INTEGER NOT NULL,
    payload       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quakes (
    id      TEXT PRIMARY KEY,
    time_ms INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class Snapshot:
    fetched_at: str
    current: Current
    hourly: Hourly


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    # --- snapshots -------------------------------------------------------
    def save_snapshots(self, items: dict[str, tuple[Current, Hourly]], fetched_at: str) -> None:
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO snapshots (location_id, fetched_at, current_json, hourly_json) "
                "VALUES (?, ?, ?, ?)",
                [
                    (loc_id, fetched_at, current.model_dump_json(), hourly.model_dump_json())
                    for loc_id, (current, hourly) in items.items()
                ],
            )

    def get_snapshots(self) -> dict[str, Snapshot]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM snapshots").fetchall()
        return {r["location_id"]: self._snapshot(r) for r in rows}

    def get_snapshot(self, location_id: str) -> Snapshot | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM snapshots WHERE location_id = ?", (location_id,)).fetchone()
        return self._snapshot(row) if row else None

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> Snapshot:
        return Snapshot(
            fetched_at=row["fetched_at"],
            current=Current.model_validate_json(row["current_json"]),
            hourly=Hourly.model_validate_json(row["hourly_json"]),
        )

    # --- alertas ---------------------------------------------------------
    def replace_alerts(self, alerts: list[Alert]) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM alerts")
            conn.executemany(
                "INSERT OR REPLACE INTO alerts (key, severity_rank, payload) VALUES (?, ?, ?)",
                [(a.key, SEVERITY_RANK[a.severity], a.model_dump_json()) for a in alerts],
            )

    def get_alerts(self) -> list[Alert]:
        with self._conn() as conn:
            rows = conn.execute("SELECT payload FROM alerts ORDER BY severity_rank DESC, key").fetchall()
        return [Alert.model_validate_json(r["payload"]) for r in rows]

    # --- sismos ----------------------------------------------------------
    def replace_quakes(self, quakes: list[Quake]) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM quakes")
            conn.executemany(
                "INSERT OR REPLACE INTO quakes (id, time_ms, payload) VALUES (?, ?, ?)",
                [(q.id, q.time_ms, q.model_dump_json()) for q in quakes],
            )

    def get_quakes(self) -> list[Quake]:
        with self._conn() as conn:
            rows = conn.execute("SELECT payload FROM quakes ORDER BY time_ms DESC").fetchall()
        return [Quake.model_validate_json(r["payload"]) for r in rows]

    # --- meta ------------------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    def get_meta(self, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
