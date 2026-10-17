"""SQLite index of recordings, motion events, users and login sessions.

The database lives on the server's local disk (SQLite over NFS is unsafe).
It can be rebuilt from the journals stored next to recordings on the NAS
(see `cli reindex`).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    totp_secret TEXT,
    prefs TEXT NOT NULL DEFAULT '{}',
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created REAL NOT NULL,
    expires REAL NOT NULL,
    ip TEXT,
    user_agent TEXT
);
CREATE TABLE IF NOT EXISTS rec_sessions (
    id TEXT PRIMARY KEY,
    cam TEXT NOT NULL,
    started REAL NOT NULL,
    ended REAL,
    init_path TEXT NOT NULL,
    codec TEXT
);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    cam TEXT NOT NULL,
    sess TEXT NOT NULL,
    start REAL NOT NULL,
    duration REAL NOT NULL,
    path TEXT UNIQUE NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    keep INTEGER
);
CREATE INDEX IF NOT EXISTS segments_cam_start ON segments(cam, start);
CREATE INDEX IF NOT EXISTS segments_start ON segments(start);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    cam TEXT NOT NULL,
    start REAL NOT NULL,
    end REAL,
    kind TEXT NOT NULL DEFAULT 'motion'
);
CREATE INDEX IF NOT EXISTS events_cam_start ON events(cam, start);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def executemany(self, sql: str, rows) -> None:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.executemany(sql, rows)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params=()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    # --- recordings -------------------------------------------------------

    def add_session(self, sess_id: str, cam: str, started: float, init_path: str, codec: str | None):
        self.execute(
            "INSERT OR IGNORE INTO rec_sessions(id, cam, started, init_path, codec) VALUES (?,?,?,?,?)",
            (sess_id, cam, started, init_path, codec),
        )

    def end_session(self, sess_id: str, ended: float):
        self.execute("UPDATE rec_sessions SET ended=? WHERE id=? AND ended IS NULL", (ended, sess_id))

    def add_segments(self, rows: list[tuple]) -> None:
        """rows: (cam, sess, start, duration, path, size)"""
        if rows:
            self.executemany(
                "INSERT OR IGNORE INTO segments(cam, sess, start, duration, path, size) VALUES (?,?,?,?,?,?)",
                rows,
            )

    def segments_between(self, cam: str, start: float, end: float) -> list[sqlite3.Row]:
        # Segments are at most a few tens of seconds long; look back a bit so a
        # segment that started before `start` but overlaps it is included.
        return self.query(
            "SELECT id, sess, start, duration, path, size FROM segments "
            "WHERE cam=? AND start>=? AND start<? ORDER BY start",
            (cam, start - 120, end),
        )

    # --- events -----------------------------------------------------------

    def open_event(self, cam: str, start: float, kind: str = "motion") -> int:
        row = self.one("SELECT id FROM events WHERE cam=? AND kind=? AND end IS NULL", (cam, kind))
        if row:
            return row["id"]
        return self.execute("INSERT INTO events(cam, start, kind) VALUES (?,?,?)", (cam, start, kind)).lastrowid

    def close_event(self, cam: str, end: float, kind: str = "motion") -> None:
        self.execute("UPDATE events SET end=? WHERE cam=? AND kind=? AND end IS NULL", (end, cam, kind))

    def events_between(self, cam: str, start: float, end: float) -> list[sqlite3.Row]:
        return self.query(
            "SELECT start, end, kind FROM events WHERE cam=? AND start<? AND (end IS NULL OR end>?) ORDER BY start",
            (cam, end, start),
        )

    # --- users ------------------------------------------------------------

    def user_prefs(self, user_id: int) -> dict:
        row = self.one("SELECT prefs FROM users WHERE id=?", (user_id,))
        return json.loads(row["prefs"]) if row else {}

    def set_user_prefs(self, user_id: int, prefs: dict) -> None:
        self.execute("UPDATE users SET prefs=? WHERE id=?", (json.dumps(prefs), user_id))

    def close(self):
        with self._lock:
            self._conn.close()
