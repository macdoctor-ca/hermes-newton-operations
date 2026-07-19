"""Bounded append-only decision and outcome journal for Newton Operations."""
from __future__ import annotations

import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

VALID_CATEGORIES = {"decision", "outcome", "lifecycle"}
VALID_SOURCES = {"manual", "hermes-hook"}
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_RECORD_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class InvalidJournalEntry(ValueError):
    """The requested journal entry violates the bounded journal contract."""


class RecordNotFound(LookupError):
    """No projected journal record exists for the supplied record id."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    value = value.astimezone(timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def _validate_text(name: str, value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidJournalEntry(f"{name} must be text")
    cleaned = value.strip()
    if not cleaned:
        raise InvalidJournalEntry(f"{name} is required")
    if len(cleaned) > maximum:
        raise InvalidJournalEntry(f"{name} exceeds {maximum} characters")
    if _CONTROL_RE.search(cleaned):
        raise InvalidJournalEntry(f"{name} contains control characters")
    return cleaned


def _validate_record_id(record_id: Any) -> str:
    value = str(record_id or "").strip().lower()
    if not _RECORD_ID_RE.fullmatch(value):
        raise InvalidJournalEntry("invalid record id")
    return value


class JournalStore:
    """SQLite event journal with a derived record projection.

    Reads open SQLite in URI ``mode=ro`` and never initialize a missing or
    uninitialized database. Writes initialize the private store, append events,
    and prune complete record histories beyond the configured bounds.
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        retention_days: int = 365,
        max_records: int = 2000,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.retention_days = max(1, int(retention_days))
        self.max_records = max(1, int(max_records))
        self.clock = clock or _utc_now

    @property
    def plugin_root(self) -> Path:
        return self.db_path.parent.parent

    def _ensure_private_paths(self) -> None:
        self.plugin_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            os.chmod(self.plugin_root, 0o700)
            os.chmod(self.db_path.parent, 0o700)
        if not self.db_path.exists():
            fd = os.open(self.db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        if os.name != "nt":
            os.chmod(self.db_path, 0o600)

    def _tighten_sidecars(self) -> None:
        if os.name == "nt":
            return
        for path in (self.db_path, Path(f"{self.db_path}-wal"), Path(f"{self.db_path}-shm")):
            if path.exists():
                os.chmod(path, 0o600)

    def _connect_write(self) -> sqlite3.Connection:
        self._ensure_private_paths()
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS journal_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT NOT NULL,
                event_type TEXT NOT NULL CHECK(event_type IN ('created','sealed')),
                category TEXT,
                title TEXT,
                summary TEXT,
                source TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_journal_record ON journal_events(record_id,event_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_journal_created ON journal_events(created_at,event_id)"
        )
        self._tighten_sidecars()
        return conn

    def _connect_read(self) -> sqlite3.Connection:
        encoded = quote(str(self.db_path.resolve()), safe="/")
        conn = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        return conn

    @staticmethod
    def _project(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        ordering: list[str] = []
        for row in rows:
            record_id = row["record_id"]
            event_type = row["event_type"]
            if event_type == "created":
                records[record_id] = {
                    "record_id": record_id,
                    "category": row["category"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "source": row["source"],
                    "status": "open",
                    "created_at": row["created_at"],
                    "updated_at": row["created_at"],
                    "sealed_at": None,
                    "event_count": 1,
                }
                ordering.append(record_id)
            elif event_type == "sealed" and record_id in records:
                record = records[record_id]
                record["status"] = "sealed"
                record["sealed_at"] = row["created_at"]
                record["updated_at"] = row["created_at"]
                record["event_count"] += 1
        return [records[rid] for rid in reversed(ordering) if rid in records]

    @staticmethod
    def _read_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT event_id,record_id,event_type,category,title,summary,source,created_at "
            "FROM journal_events ORDER BY event_id"
        ).fetchall()

    def list_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        with self._connect_read() as conn:
            records = self._project(self._read_rows(conn))
        return records[: max(0, min(int(limit), self.max_records))]

    def get_record(self, record_id: str) -> Optional[dict[str, Any]]:
        record_id = _validate_record_id(record_id)
        if not self.db_path.exists():
            return None
        with self._connect_read() as conn:
            rows = conn.execute(
                "SELECT event_id,record_id,event_type,category,title,summary,source,created_at "
                "FROM journal_events WHERE record_id=? ORDER BY event_id",
                (record_id,),
            ).fetchall()
        records = self._project(rows)
        return records[0] if records else None

    def _prune(self, conn: sqlite3.Connection, now: datetime) -> None:
        cutoff = _iso(now - timedelta(days=self.retention_days))
        conn.execute(
            """DELETE FROM journal_events WHERE record_id IN (
                SELECT record_id FROM journal_events
                GROUP BY record_id HAVING MAX(created_at) < ?
            )""",
            (cutoff,),
        )
        conn.execute(
            """DELETE FROM journal_events WHERE record_id IN (
                SELECT record_id FROM journal_events
                GROUP BY record_id
                ORDER BY MIN(event_id) DESC
                LIMIT -1 OFFSET ?
            )""",
            (self.max_records,),
        )

    def create_record(
        self,
        *,
        category: str,
        title: str,
        summary: str,
        source: str,
        sealed: bool = False,
    ) -> dict[str, Any]:
        if category not in VALID_CATEGORIES:
            raise InvalidJournalEntry("unsupported category")
        if source not in VALID_SOURCES:
            raise InvalidJournalEntry("unsupported source")
        title = _validate_text("title", title, 120)
        summary = _validate_text("summary", summary, 500)
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise InvalidJournalEntry("clock must return a timezone-aware datetime")
        created_at = _iso(now)
        record_id = uuid.uuid4().hex

        conn = self._connect_write()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO journal_events(record_id,event_type,category,title,summary,source,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (record_id, "created", category, title, summary, source, created_at),
            )
            if sealed:
                conn.execute(
                    "INSERT INTO journal_events(record_id,event_type,created_at) VALUES(?,?,?)",
                    (record_id, "sealed", created_at),
                )
            self._prune(conn, now)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            self._tighten_sidecars()

        record = self.get_record(record_id)
        if record is None:  # max_records is always >= 1, defensive only.
            raise RecordNotFound(record_id)
        return record

    def seal_record(self, record_id: str) -> dict[str, Any]:
        record_id = _validate_record_id(record_id)
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise InvalidJournalEntry("clock must return a timezone-aware datetime")
        sealed_at = _iso(now)
        record: Optional[dict[str, Any]] = None
        conn = self._connect_write()
        try:
            # Existence, idempotence, append, and pruning share one write lock.
            # This prevents a concurrent create/prune transaction from deleting
            # the record between a preflight read and the sealed-event insert.
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT event_id,record_id,event_type,category,title,summary,source,created_at "
                "FROM journal_events WHERE record_id=? ORDER BY event_id",
                (record_id,),
            ).fetchall()
            projected = self._project(rows)
            if not projected:
                conn.rollback()
                raise RecordNotFound(record_id)
            if projected[0]["status"] == "sealed":
                conn.rollback()
                return projected[0]

            conn.execute(
                "INSERT INTO journal_events(record_id,event_type,created_at) VALUES(?,?,?)",
                (record_id, "sealed", sealed_at),
            )
            self._prune(conn, now)
            rows = conn.execute(
                "SELECT event_id,record_id,event_type,category,title,summary,source,created_at "
                "FROM journal_events WHERE record_id=? ORDER BY event_id",
                (record_id,),
            ).fetchall()
            projected = self._project(rows)
            record = projected[0] if projected else None
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()
            self._tighten_sidecars()
        if record is None:
            raise RecordNotFound(record_id)
        return record
