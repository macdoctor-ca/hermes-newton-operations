"""Bounded append-only decision and outcome journal for Newton Operations."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

VALID_CATEGORIES = {"decision", "outcome", "lifecycle"}
VALID_SOURCES = {"manual", "hermes-hook"}
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_RECORD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
_SCHEMA_VERSION = 2
_DEFAULT_MAX_DB_BYTES = 16 * 1024 * 1024
_MIGRATION_THREAD_LOCK = threading.Lock()

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]


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


def _validate_tags(values: Any) -> list[str]:
    if values in (None, ""):
        return []
    if not isinstance(values, (list, tuple)):
        raise InvalidJournalEntry("tags must be a list")
    if len(values) > 6:
        raise InvalidJournalEntry("tags exceeds 6 items")
    tags: list[str] = []
    for raw in values:
        tag = str(raw or "").strip().lower()
        if not _TAG_RE.fullmatch(tag):
            raise InvalidJournalEntry("tag must use lowercase letters, numbers, and hyphens")
        if tag not in tags:
            tags.append(tag)
    return tags


def _validate_related(values: Any) -> list[str]:
    if values in (None, ""):
        return []
    if not isinstance(values, (list, tuple)):
        raise InvalidJournalEntry("related references must be a list")
    if len(values) > 6:
        raise InvalidJournalEntry("related references exceeds 6 items")
    related: list[str] = []
    for raw in values:
        label = _validate_text("related reference", raw, 80)
        if label not in related:
            related.append(label)
    return related


def _safe_text(value: Any, maximum: int, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = _CONTROL_RE.sub(" ", value).strip()[:maximum]
    return cleaned or fallback


def _safe_timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _iso(parsed)


def _decode_list(raw: Any, *, maximum: int, item_maximum: int) -> list[str]:
    if not isinstance(raw, str) or not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:maximum]:
        if isinstance(item, str):
            cleaned = _CONTROL_RE.sub(" ", item).strip()[:item_maximum]
            if cleaned and cleaned not in result:
                result.append(cleaned)
    return result


def _hash_value(value: Any) -> Any:
    return value if isinstance(value, (str, int)) or value is None else None


def _event_hash(
    row: Any, previous_hash: str | None, *, event_schema: int | None = None
) -> str:
    stored_schema = row["event_schema"] if event_schema is None else event_schema
    material = {
        "event_id": _hash_value(row["event_id"]),
        "record_id": _hash_value(row["record_id"]),
        "event_type": _hash_value(row["event_type"]),
        "category": _hash_value(row["category"]),
        "title": _hash_value(row["title"]),
        "summary": _hash_value(row["summary"]),
        "source": _hash_value(row["source"]),
        "created_at": _hash_value(row["created_at"]),
        "tags_json": _hash_value(row["tags_json"]),
        "related_json": _hash_value(row["related_json"]),
        "supersedes": _hash_value(row["supersedes"]),
        "previous_hash": previous_hash,
        "event_schema": _hash_value(stored_schema),
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class JournalStore:
    """SQLite event journal with a derived, bounded record projection.

    Reads open SQLite in URI ``mode=ro`` and never initialize or migrate a
    missing database. The first write performs an additive, transactional v2
    migration and creates one owner-only SQLite backup. Event hashes form an
    independent chain per retained record.
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        retention_days: int = 365,
        max_records: int = 2000,
        max_db_bytes: int = _DEFAULT_MAX_DB_BYTES,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.retention_days = max(1, int(retention_days))
        self.max_records = max(1, int(max_records))
        self.max_db_bytes = max(1024 * 1024, int(max_db_bytes))
        self.clock = clock or _utc_now

    @property
    def plugin_root(self) -> Path:
        return self.db_path.parent.parent

    @property
    def migration_backup_path(self) -> Path:
        return self.db_path.with_name(f"{self.db_path.stem}.pre-v1.1{self.db_path.suffix}")

    @property
    def migration_lock_path(self) -> Path:
        return self.db_path.with_name(f".{self.db_path.name}.migration.lock")

    def _check_db_bounds(self) -> None:
        for path in (self.db_path, Path(f"{self.db_path}-wal")):
            if path.exists() and path.stat().st_size > self.max_db_bytes:
                raise InvalidJournalEntry("journal database exceeds bounded size")

    @contextmanager
    def _migration_guard(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            os.chmod(self.db_path.parent, 0o700)
        with _MIGRATION_THREAD_LOCK:
            descriptor = os.open(
                self.migration_lock_path, os.O_CREAT | os.O_RDWR, 0o600
            )
            with os.fdopen(descriptor, "a+b") as lock_file:
                if os.name != "nt":
                    os.chmod(self.migration_lock_path, 0o600)
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

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
        for path in (
            self.db_path,
            Path(f"{self.db_path}-wal"),
            Path(f"{self.db_path}-shm"),
            self.migration_backup_path,
        ):
            if path.exists():
                os.chmod(path, 0o600)

    @staticmethod
    def _columns(conn: sqlite3.Connection) -> set[str]:
        return {row[1] for row in conn.execute("PRAGMA table_info(journal_events)")}

    @staticmethod
    def _table_exists(conn: sqlite3.Connection) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='journal_events'"
            ).fetchone()
            is not None
        )

    def _needs_migration(self) -> bool:
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return False
        self._check_db_bounds()
        with self._connect_read() as conn:
            if not self._table_exists(conn):
                return True
            columns = self._columns(conn)
        required = {
            "tags_json",
            "related_json",
            "supersedes",
            "prev_event_hash",
            "event_hash",
            "event_schema",
        }
        return not required.issubset(columns)

    def _backup_for_migration(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.migration_backup_path.with_name(
            f".{self.migration_backup_path.name}.tmp-{uuid.uuid4().hex}"
        )
        source_count: int | None = None
        try:
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            with self._connect_read() as source:
                check = source.execute("PRAGMA quick_check").fetchone()
                if not check or check[0] != "ok":
                    raise InvalidJournalEntry("legacy journal integrity check failed")
                if self._table_exists(source):
                    self._validate_existing_events(source, self.max_records * 2)
                    source_count = int(
                        source.execute("SELECT COUNT(*) FROM journal_events").fetchone()[0]
                    )
                with sqlite3.connect(temporary) as target:
                    source.backup(target)
            with sqlite3.connect(temporary) as backup:
                check = backup.execute("PRAGMA quick_check").fetchone()
                if not check or check[0] != "ok":
                    raise InvalidJournalEntry("journal migration backup verification failed")
                if source_count is not None:
                    backup_count = int(
                        backup.execute("SELECT COUNT(*) FROM journal_events").fetchone()[0]
                    )
                    if backup_count != source_count:
                        raise InvalidJournalEntry("journal migration backup verification failed")
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, self.migration_backup_path)
            if os.name != "nt":
                directory_fd = os.open(self.db_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _validate_existing_events(
        conn: sqlite3.Connection, maximum_events: int
    ) -> None:
        bounded = conn.execute(
            "SELECT event_id FROM journal_events ORDER BY event_id LIMIT ?",
            (maximum_events + 1,),
        ).fetchall()
        if len(bounded) > maximum_events:
            raise InvalidJournalEntry("journal bounds verification failed")
        invalid_type = conn.execute(
            "SELECT 1 FROM journal_events WHERE event_type NOT IN ('created','sealed') LIMIT 1"
        ).fetchone()
        duplicate_create = conn.execute(
            "SELECT 1 FROM journal_events WHERE event_type='created' "
            "GROUP BY record_id HAVING COUNT(*)<>1 LIMIT 1"
        ).fetchone()
        duplicate_seal = conn.execute(
            "SELECT 1 FROM journal_events WHERE event_type='sealed' "
            "GROUP BY record_id HAVING COUNT(*)>1 LIMIT 1"
        ).fetchone()
        orphan_seal = conn.execute(
            "SELECT 1 FROM journal_events s WHERE s.event_type='sealed' AND NOT EXISTS "
            "(SELECT 1 FROM journal_events c WHERE c.record_id=s.record_id "
            "AND c.event_type='created') LIMIT 1"
        ).fetchone()
        if invalid_type or duplicate_create or duplicate_seal or orphan_seal:
            raise InvalidJournalEntry("journal schema validation failed")

    @staticmethod
    def _full_select() -> str:
        return (
            "SELECT event_id,record_id,event_type,category,title,summary,source,created_at,"
            "tags_json,related_json,supersedes,prev_event_hash,event_hash,event_schema "
            "FROM journal_events"
        )

    def _backfill_hashes(self, conn: sqlite3.Connection) -> None:
        previous: dict[str, str | None] = {}
        rows = conn.execute(self._full_select() + " ORDER BY event_id")
        for row in rows:
            record_id = str(row["record_id"] or "")
            prior = previous.get(record_id)
            digest = _event_hash(row, prior, event_schema=_SCHEMA_VERSION)
            conn.execute(
                "UPDATE journal_events SET prev_event_hash=?,event_hash=?,event_schema=? "
                "WHERE event_id=?",
                (prior, digest, _SCHEMA_VERSION, row["event_id"]),
            )
            previous[record_id] = digest

    def _connect_write_guarded(self) -> sqlite3.Connection:
        migration_needed = self._needs_migration()
        if migration_needed:
            self._backup_for_migration()
        self._ensure_private_paths()
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        try:
            conn.execute("BEGIN IMMEDIATE")
            existed = self._table_exists(conn)
            if existed:
                self._validate_existing_events(conn, self.max_records * 2)
            conn.execute(
                """CREATE TABLE IF NOT EXISTS journal_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN ('created','sealed')),
                    category TEXT,
                    title TEXT,
                    summary TEXT,
                    source TEXT,
                    created_at TEXT NOT NULL,
                    tags_json TEXT,
                    related_json TEXT,
                    supersedes TEXT,
                    prev_event_hash TEXT,
                    event_hash TEXT,
                    event_schema INTEGER
                )"""
            )
            columns = self._columns(conn)
            if "tags_json" not in columns:
                conn.execute("ALTER TABLE journal_events ADD COLUMN tags_json TEXT")
            if "related_json" not in columns:
                conn.execute("ALTER TABLE journal_events ADD COLUMN related_json TEXT")
            if "supersedes" not in columns:
                conn.execute("ALTER TABLE journal_events ADD COLUMN supersedes TEXT")
            if "prev_event_hash" not in columns:
                conn.execute("ALTER TABLE journal_events ADD COLUMN prev_event_hash TEXT")
            if "event_hash" not in columns:
                conn.execute("ALTER TABLE journal_events ADD COLUMN event_hash TEXT")
            if "event_schema" not in columns:
                conn.execute("ALTER TABLE journal_events ADD COLUMN event_schema INTEGER")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_journal_record "
                "ON journal_events(record_id,event_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_journal_created "
                "ON journal_events(created_at,event_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_journal_supersedes "
                "ON journal_events(supersedes)"
            )
            if migration_needed:
                self._backfill_hashes(conn)
            elif existed:
                current_rows = conn.execute(
                    self._full_select() + " ORDER BY event_id LIMIT ?",
                    (self.max_records * 2 + 1,),
                ).fetchall()
                if len(current_rows) > self.max_records * 2:
                    raise InvalidJournalEntry("journal bounds verification failed")
                states = self._integrity_by_record(current_rows)
                if any(state != "verified" for state in states.values()):
                    raise InvalidJournalEntry("journal integrity verification failed")
            conn.execute("PRAGMA user_version=2")
            check = conn.execute("PRAGMA quick_check").fetchone()
            if not check or check[0] != "ok":
                raise InvalidJournalEntry("journal integrity check failed")
            conn.commit()
        except Exception:
            conn.rollback()
            conn.close()
            raise
        self._tighten_sidecars()
        return conn

    def _connect_write(self) -> sqlite3.Connection:
        with self._migration_guard():
            return self._connect_write_guarded()

    def _connect_read(self) -> sqlite3.Connection:
        self._check_db_bounds()
        encoded = quote(str(self.db_path.resolve()), safe="/")
        conn = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        return conn

    @classmethod
    def _select_sql(cls, conn: sqlite3.Connection) -> str:
        columns = cls._columns(conn)
        metadata = {"tags_json", "related_json", "supersedes"}.issubset(columns)
        hashes = {"prev_event_hash", "event_hash", "event_schema"}.issubset(columns)
        base = "SELECT event_id,record_id,event_type,category,title,summary,source,created_at,"
        if metadata and hashes:
            return cls._full_select()
        if metadata:
            return (
                base
                + "tags_json,related_json,supersedes,NULL AS prev_event_hash,"
                "NULL AS event_hash,0 AS event_schema FROM journal_events"
            )
        return (
            base
            + "NULL AS tags_json,NULL AS related_json,NULL AS supersedes,"
            "NULL AS prev_event_hash,NULL AS event_hash,0 AS event_schema "
            "FROM journal_events"
        )

    def _read_rows(self, conn: sqlite3.Connection) -> list[sqlite3.Row]:
        rows = conn.execute(
            self._select_sql(conn) + " ORDER BY event_id DESC LIMIT ?",
            (self.max_records * 2 + 1,),
        ).fetchall()
        rows.reverse()
        return rows

    @classmethod
    def _read_record_rows(
        cls, conn: sqlite3.Connection, record_id: str
    ) -> list[sqlite3.Row]:
        return conn.execute(
            cls._select_sql(conn) + " WHERE record_id=? ORDER BY event_id",
            (record_id,),
        ).fetchall()

    @staticmethod
    def _integrity_by_record(rows: list[sqlite3.Row]) -> dict[str, str]:
        previous: dict[str, str | None] = {}
        status: dict[str, str] = {}
        for row in rows:
            record_id = _safe_text(row["record_id"], 32)
            if not _RECORD_ID_RE.fullmatch(record_id):
                continue
            raw_hash = row["event_hash"]
            raw_previous = row["prev_event_hash"]
            schema = row["event_schema"]
            if schema == 0 and raw_hash is None and raw_previous is None:
                if status.get(record_id) not in (None, "legacy"):
                    status[record_id] = "failed"
                else:
                    status[record_id] = "legacy"
                previous[record_id] = None
                continue
            if (
                schema != _SCHEMA_VERSION
                or not isinstance(raw_hash, str)
                or not _HASH_RE.fullmatch(raw_hash)
                or (
                    raw_previous not in (None, "")
                    and (
                        not isinstance(raw_previous, str)
                        or not _HASH_RE.fullmatch(raw_previous)
                    )
                )
                or status.get(record_id) == "legacy"
            ):
                status[record_id] = "failed"
                previous[record_id] = raw_hash if isinstance(raw_hash, str) else None
                continue
            stored_hash = raw_hash
            stored_previous = raw_previous or None
            expected_previous = previous.get(record_id)
            expected_hash = _event_hash(row, expected_previous)
            if stored_previous != expected_previous or stored_hash != expected_hash:
                status[record_id] = "failed"
            elif status.get(record_id) != "failed":
                status[record_id] = "verified"
            previous[record_id] = stored_hash
        return status

    @classmethod
    def _project(cls, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        integrity = cls._integrity_by_record(rows)
        records: dict[str, dict[str, Any]] = {}
        ordering: list[str] = []
        for row in rows:
            record_id = _safe_text(row["record_id"], 32)
            event_type = _safe_text(row["event_type"], 16)
            if not _RECORD_ID_RE.fullmatch(record_id):
                continue
            if event_type == "created":
                if record_id in records:
                    integrity[record_id] = "failed"
                    continue
                category = _safe_text(row["category"], 16, "decision")
                source = _safe_text(row["source"], 24, "manual")
                records[record_id] = {
                    "record_id": record_id,
                    "category": category if category in VALID_CATEGORIES else "decision",
                    "title": _safe_text(row["title"], 120, "Journal record"),
                    "summary": _safe_text(row["summary"], 500),
                    "source": source if source in VALID_SOURCES else "manual",
                    "tags": _decode_list(row["tags_json"], maximum=6, item_maximum=24),
                    "related": _decode_list(row["related_json"], maximum=6, item_maximum=80),
                    "supersedes": (
                        _safe_text(row["supersedes"], 32)
                        if _RECORD_ID_RE.fullmatch(_safe_text(row["supersedes"], 32))
                        else None
                    ),
                    "superseded_by": None,
                    "status": "open",
                    "created_at": _safe_timestamp(row["created_at"]),
                    "updated_at": _safe_timestamp(row["created_at"]),
                    "sealed_at": None,
                    "integrity_status": integrity.get(record_id, "legacy"),
                    "event_count": 1,
                }
                ordering.append(record_id)
            elif event_type == "sealed" and record_id in records:
                record = records[record_id]
                record["status"] = "sealed"
                record["sealed_at"] = _safe_timestamp(row["created_at"])
                record["updated_at"] = _safe_timestamp(row["created_at"])
                record["event_count"] += 1

        for record in records.values():
            target = record.get("supersedes")
            if target in records:
                records[target]["superseded_by"] = record["record_id"]
        return [records[rid] for rid in reversed(ordering) if rid in records]

    def list_records(
        self,
        *,
        limit: int = 100,
        query: str | None = None,
        category: str | None = None,
        record_status: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        with self._connect_read() as conn:
            records = self._project(self._read_rows(conn))
        query_value = str(query or "").strip().lower()[:80]
        category_value = str(category or "").strip().lower()
        status_value = str(record_status or "").strip().lower()
        tag_value = str(tag or "").strip().lower()
        filtered: list[dict[str, Any]] = []
        for record in records:
            if category_value and record.get("category") != category_value:
                continue
            if status_value and record.get("status") != status_value:
                continue
            if tag_value and tag_value not in record.get("tags", []):
                continue
            if query_value:
                haystack = " ".join(
                    [
                        str(record.get("title") or ""),
                        str(record.get("summary") or ""),
                        " ".join(record.get("tags") or []),
                        " ".join(record.get("related") or []),
                    ]
                ).lower()
                if query_value not in haystack:
                    continue
            filtered.append(record)
        return filtered[: max(0, min(int(limit), self.max_records))]

    def get_record(self, record_id: str) -> Optional[dict[str, Any]]:
        record_id = _validate_record_id(record_id)
        if not self.db_path.exists():
            return None
        with self._connect_read() as conn:
            records = self._project(self._read_rows(conn))
        return next(
            (record for record in records if record["record_id"] == record_id),
            None,
        )

    def verify_integrity(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return {
                "status": "verified",
                "checked_records": 0,
                "checked_events": 0,
                "failure_code": None,
            }
        with self._connect_read() as conn:
            rows = self._read_rows(conn)
        if len(rows) > self.max_records * 2:
            return {
                "status": "failed",
                "checked_records": 0,
                "checked_events": self.max_records * 2,
                "failure_code": "bounds_exceeded",
            }
        states = self._integrity_by_record(rows)
        if any(value == "failed" for value in states.values()):
            overall = "failed"
            failure = "hash_mismatch"
        elif any(value == "legacy" for value in states.values()):
            overall = "legacy"
            failure = "migration_required"
        else:
            overall = "verified"
            failure = None
        return {
            "status": overall,
            "checked_records": len(states),
            "checked_events": len(rows),
            "failure_code": failure,
        }

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

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        record_id: str,
        event_type: str,
        created_at: str,
        category: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        source: str | None = None,
        tags_json: str | None = None,
        related_json: str | None = None,
        supersedes: str | None = None,
    ) -> None:
        previous_row = conn.execute(
            "SELECT event_hash FROM journal_events WHERE record_id=? "
            "ORDER BY event_id DESC LIMIT 1",
            (record_id,),
        ).fetchone()
        previous_hash = previous_row[0] if previous_row and previous_row[0] else None
        cursor = conn.execute(
            """INSERT INTO journal_events(
                record_id,event_type,category,title,summary,source,created_at,
                tags_json,related_json,supersedes,prev_event_hash,event_schema
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record_id,
                event_type,
                category,
                title,
                summary,
                source,
                created_at,
                tags_json,
                related_json,
                supersedes,
                previous_hash,
                _SCHEMA_VERSION,
            ),
        )
        row = conn.execute(
            JournalStore._full_select() + " WHERE event_id=?", (cursor.lastrowid,)
        ).fetchone()
        digest = _event_hash(row, previous_hash)
        conn.execute(
            "UPDATE journal_events SET event_hash=? WHERE event_id=?",
            (digest, cursor.lastrowid),
        )

    def create_record(
        self,
        *,
        category: str,
        title: str,
        summary: str,
        source: str,
        sealed: bool = False,
        tags: Any = None,
        related: Any = None,
        supersedes: Any = None,
    ) -> dict[str, Any]:
        if category not in VALID_CATEGORIES:
            raise InvalidJournalEntry("unsupported category")
        if source not in VALID_SOURCES:
            raise InvalidJournalEntry("unsupported source")
        title = _validate_text("title", title, 120)
        summary = _validate_text("summary", summary, 500)
        tag_values = _validate_tags(tags)
        related_values = _validate_related(related)
        supersedes_id = _validate_record_id(supersedes) if supersedes else None
        if supersedes_id and not self.db_path.exists():
            raise InvalidJournalEntry("superseded record does not exist")
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise InvalidJournalEntry("clock must return a timezone-aware datetime")
        created_at = _iso(now)
        record_id = uuid.uuid4().hex

        conn = self._connect_write()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if supersedes_id:
                exists = conn.execute(
                    "SELECT 1 FROM journal_events WHERE record_id=? "
                    "AND event_type='created' LIMIT 1",
                    (supersedes_id,),
                ).fetchone()
                if not exists:
                    raise InvalidJournalEntry("superseded record does not exist")
            self._append_event(
                conn,
                record_id=record_id,
                event_type="created",
                category=category,
                title=title,
                summary=summary,
                source=source,
                created_at=created_at,
                tags_json=json.dumps(tag_values, separators=(",", ":")),
                related_json=json.dumps(related_values, separators=(",", ":")),
                supersedes=supersedes_id,
            )
            if sealed:
                self._append_event(
                    conn,
                    record_id=record_id,
                    event_type="sealed",
                    created_at=created_at,
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
        if record is None:
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
            conn.execute("BEGIN IMMEDIATE")
            rows = self._read_record_rows(conn, record_id)
            projected = self._project(rows)
            if not projected:
                conn.rollback()
                raise RecordNotFound(record_id)
            if projected[0]["status"] == "sealed":
                conn.rollback()
                return projected[0]
            self._append_event(
                conn,
                record_id=record_id,
                event_type="sealed",
                created_at=sealed_at,
            )
            self._prune(conn, now)
            rows = self._read_record_rows(conn, record_id)
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
