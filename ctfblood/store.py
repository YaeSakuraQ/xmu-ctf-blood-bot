"""SQLite persistence for announcements and race state.

A single SQLite file is enough for one contest: writes are tiny, the bot is a
single process, and WAL mode keeps readers from blocking the sender.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .models import BloodEvent, StoredEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS announcements (
    race_id         TEXT NOT NULL,
    challenge_id    TEXT NOT NULL,
    challenge_name  TEXT NOT NULL,
    direction       TEXT NOT NULL,
    blood           INTEGER NOT NULL,
    team_id         TEXT NOT NULL,
    team_name       TEXT NOT NULL,
    solve_time      TEXT,
    score           INTEGER,
    time_exact      INTEGER NOT NULL DEFAULT 0,
    catchup         INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INTEGER NOT NULL DEFAULT 0,
    message         TEXT NOT NULL DEFAULT '',
    last_error      TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    sent_at         TEXT,
    next_attempt_at TEXT NOT NULL,
    PRIMARY KEY (race_id, challenge_id, blood)
);

CREATE INDEX IF NOT EXISTS idx_announcements_pending
    ON announcements (race_id, status, next_attempt_at, created_at);

CREATE TABLE IF NOT EXISTS race_state (
    race_id       TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL DEFAULT '',
    total_score   INTEGER NOT NULL DEFAULT 0,
    total_solved  INTEGER NOT NULL DEFAULT 0,
    drop_streak   INTEGER NOT NULL DEFAULT 0,
    last_poll_at  TEXT,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path: str) -> None:
        self.path = str(Path(path).expanduser())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ writes
    def add(
        self,
        event: BloodEvent,
        *,
        status: str = "pending",
        catchup: bool | None = None,
        message: str = "",
        now: str | None = None,
    ) -> bool:
        """Insert an announcement. Returns ``True`` when this is a new key."""

        timestamp = now or _now()
        catchup_value = int(event.catchup if catchup is None else catchup)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO announcements (
                    race_id, challenge_id, challenge_name, direction, blood,
                    team_id, team_name, solve_time, score, time_exact, catchup,
                    status, attempts, message, created_at, updated_at, next_attempt_at,
                    sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                """,
                (
                    event.race_id,
                    event.challenge_id,
                    event.challenge_name,
                    event.direction,
                    event.blood,
                    event.team_id,
                    event.team_name,
                    event.solve_time,
                    event.score,
                    int(event.time_exact),
                    catchup_value,
                    status,
                    message,
                    timestamp,
                    timestamp,
                    timestamp,
                    timestamp if status == "sent" else None,
                ),
            )
        return cursor.rowcount == 1

    def mark_sent(self, key: tuple[str, str, int], message: str, now: str | None = None) -> None:
        timestamp = now or _now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE announcements
                SET status = 'sent', message = ?, sent_at = ?, updated_at = ?,
                    attempts = attempts + 1, last_error = ''
                WHERE race_id = ? AND challenge_id = ? AND blood = ?
                """,
                (message, timestamp, timestamp, *key),
            )

    def mark_failed(
        self,
        key: tuple[str, str, int],
        error: str,
        *,
        next_attempt_at: str,
        max_attempts: int,
        now: str | None = None,
    ) -> str:
        """Increment attempts and return the new status (pending/failed)."""

        timestamp = now or _now()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT attempts FROM announcements WHERE race_id = ? AND challenge_id = ? AND blood = ?",
                key,
            ).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            status = "failed" if attempts >= max_attempts else "pending"
            self._conn.execute(
                """
                UPDATE announcements
                SET status = ?, attempts = ?, last_error = ?, updated_at = ?, next_attempt_at = ?
                WHERE race_id = ? AND challenge_id = ? AND blood = ?
                """,
                (status, attempts, error[:500], timestamp, next_attempt_at, *key),
            )
        return status

    def clear_race(self, race_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM announcements WHERE race_id = ?", (race_id,))
            self._conn.execute("DELETE FROM race_state WHERE race_id = ?", (race_id,))
            self._conn.execute("DELETE FROM meta WHERE key LIKE ?", (f"%:{race_id}",))

    # ------------------------------------------------------------------- reads
    def next_pending(self, race_id: str, now: str | None = None) -> StoredEvent | None:
        timestamp = now or _now()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM announcements
                WHERE race_id = ? AND status = 'pending' AND next_attempt_at <= ?
                ORDER BY created_at ASC, blood ASC
                LIMIT 1
                """,
                (race_id, timestamp),
            ).fetchone()
        return _to_event(row) if row else None

    def announced_keys(self, race_id: str) -> set[tuple[str, int]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT challenge_id, blood FROM announcements WHERE race_id = ?",
                (race_id,),
            ).fetchall()
        return {(row["challenge_id"], row["blood"]) for row in rows}

    def has_any(self, race_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM announcements WHERE race_id = ? LIMIT 1",
                (race_id,),
            ).fetchone()
        return row is not None

    def counts(self, race_id: str) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM announcements WHERE race_id = ? GROUP BY status",
                (race_id,),
            ).fetchall()
        result = {"pending": 0, "sent": 0, "failed": 0}
        for row in rows:
            result[str(row["status"])] = int(row["n"])
        return result

    def get_state(self, race_id: str) -> dict[str, object] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM race_state WHERE race_id = ?",
                (race_id,),
            ).fetchone()
        return dict(row) if row else None

    def set_state(
        self,
        race_id: str,
        *,
        fingerprint: str,
        total_score: int,
        total_solved: int,
        drop_streak: int,
        last_poll_at: str,
    ) -> None:
        timestamp = _now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO race_state (
                    race_id, fingerprint, total_score, total_solved,
                    drop_streak, last_poll_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(race_id) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    total_score = excluded.total_score,
                    total_solved = excluded.total_solved,
                    drop_streak = excluded.drop_streak,
                    last_poll_at = excluded.last_poll_at,
                    updated_at = excluded.updated_at
                """,
                (race_id, fingerprint, total_score, total_solved, drop_streak, last_poll_at, timestamp),
            )

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_meta(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def recent(self, race_id: str, limit: int = 10) -> list[StoredEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM announcements WHERE race_id = ? ORDER BY updated_at DESC LIMIT ?",
                (race_id, limit),
            ).fetchall()
        return [_to_event(row) for row in rows]


def _to_event(row: sqlite3.Row) -> StoredEvent:
    return StoredEvent(
        race_id=str(row["race_id"]),
        challenge_id=str(row["challenge_id"]),
        challenge_name=str(row["challenge_name"]),
        direction=str(row["direction"]),
        blood=int(row["blood"]),
        team_id=str(row["team_id"]),
        team_name=str(row["team_name"]),
        solve_time=row["solve_time"],
        score=row["score"],
        time_exact=bool(row["time_exact"]),
        catchup=bool(row["catchup"]),
        status=str(row["status"]),
        attempts=int(row["attempts"]),
    )
