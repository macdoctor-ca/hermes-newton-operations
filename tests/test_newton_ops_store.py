from __future__ import annotations

import sqlite3
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from newton_ops_store import (  # noqa: E402
    InvalidJournalEntry,
    JournalStore,
    RecordNotFound,
)


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class JournalStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.tmp_path = Path(self._temp.name)

    def test_missing_store_read_does_not_create_directories_or_database(self):
        plugin_root = self.tmp_path / "plugin"
        db_path = plugin_root / "data" / "operations.db"
        store = JournalStore(db_path)

        self.assertEqual(store.list_records(), [])
        self.assertIsNone(store.get_record("0" * 32))
        self.assertFalse(plugin_root.exists())
        self.assertFalse(db_path.exists())

    def test_create_projection_and_idempotent_seal_are_append_only(self):
        db_path = self.tmp_path / "plugin" / "data" / "operations.db"
        clock = MutableClock(datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc))
        store = JournalStore(db_path, clock=clock)

        created = store.create_record(
            category="decision",
            title="Adopt bounded operations journal",
            summary="Keep explicit decisions without copying transcripts.",
            source="manual",
        )
        self.assertEqual(created["status"], "open")
        self.assertEqual(created["category"], "decision")
        self.assertEqual(created["event_count"], 1)
        self.assertIsNone(created["sealed_at"])

        clock.value += timedelta(minutes=5)
        sealed = store.seal_record(created["record_id"])
        self.assertEqual(sealed["status"], "sealed")
        self.assertEqual(sealed["event_count"], 2)
        self.assertEqual(sealed["sealed_at"], "2026-07-19T12:05:00Z")

        # Sealing an already-sealed record is idempotent and does not append.
        self.assertEqual(store.seal_record(created["record_id"]), sealed)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT event_type, title, summary FROM journal_events ORDER BY event_id"
            ).fetchall()
        self.assertEqual(
            rows,
            [
                (
                    "created",
                    "Adopt bounded operations journal",
                    "Keep explicit decisions without copying transcripts.",
                ),
                ("sealed", None, None),
            ],
        )

    def test_create_sealed_record_is_atomic_and_projected(self):
        store = JournalStore(self.tmp_path / "plugin" / "data" / "operations.db")

        record = store.create_record(
            category="lifecycle",
            title="Kanban task completed",
            summary="A Kanban task reached its completed state.",
            source="hermes-hook",
            sealed=True,
        )

        self.assertEqual(record["status"], "sealed")
        self.assertEqual(record["event_count"], 2)
        self.assertEqual(len(store.list_records()), 1)

    def test_metadata_filter_supersession_and_integrity_projection(self):
        db_path = self.tmp_path / "plugin" / "data" / "operations.db"
        clock = MutableClock(datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc))
        store = JournalStore(db_path, clock=clock)

        original = store.create_record(
            category="decision",
            title="Keep source projections bounded",
            summary="Never copy prompts, commands, paths, or raw errors.",
            source="manual",
            tags=["privacy", "architecture", "privacy"],
            related=["Operations timeline"],
        )
        replacement = store.create_record(
            category="outcome",
            title="Bounded projections verified",
            summary="The source privacy scan passed.",
            source="manual",
            tags=["privacy"],
            related=["Operations timeline"],
            supersedes=original["record_id"],
        )

        projected_original = store.get_record(original["record_id"])
        self.assertIsNotNone(projected_original)
        self.assertEqual(projected_original["superseded_by"], replacement["record_id"])
        self.assertEqual(replacement["supersedes"], original["record_id"])
        self.assertEqual(original["tags"], ["privacy", "architecture"])
        self.assertEqual(
            [item["record_id"] for item in store.list_records(query="verified")],
            [replacement["record_id"]],
        )
        self.assertEqual(
            [item["record_id"] for item in store.list_records(tag="architecture")],
            [original["record_id"]],
        )

        clock.value += timedelta(minutes=1)
        sealed = store.seal_record(replacement["record_id"])
        self.assertEqual(sealed["integrity_status"], "verified")
        self.assertEqual(
            store.seal_record(replacement["record_id"])["integrity_status"],
            "verified",
        )
        self.assertNotIn("event_hash", sealed)
        self.assertEqual(store.verify_integrity()["status"], "verified")

    def test_legacy_schema_is_read_without_mutation_then_migrated_on_write(self):
        db_path = self.tmp_path / "plugin" / "data" / "operations.db"
        db_path.parent.mkdir(parents=True)
        legacy_id = "a" * 32
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """CREATE TABLE journal_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN ('created','sealed')),
                    category TEXT,title TEXT,summary TEXT,source TEXT,created_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                """INSERT INTO journal_events(
                    record_id,event_type,category,title,summary,source,created_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    legacy_id,
                    "created",
                    "decision",
                    "Legacy decision",
                    "Preserve this record.",
                    "manual",
                    "2026-07-19T12:00:00Z",
                ),
            )

        store = JournalStore(db_path)
        legacy = store.list_records()[0]
        self.assertEqual(legacy["record_id"], legacy_id)
        self.assertEqual(legacy["tags"], [])
        with sqlite3.connect(db_path) as conn:
            columns_before = {row[1] for row in conn.execute("PRAGMA table_info(journal_events)")}
        self.assertNotIn("tags_json", columns_before)
        store.migration_backup_path.write_bytes(b"incomplete prior backup")

        created = store.create_record(
            category="outcome",
            title="Migration complete",
            summary="The legacy record remains intact.",
            source="manual",
            tags=["migration"],
            supersedes=legacy_id,
        )
        with sqlite3.connect(db_path) as conn:
            columns_after = {row[1] for row in conn.execute("PRAGMA table_info(journal_events)")}
        self.assertTrue(
            {
                "tags_json",
                "related_json",
                "supersedes",
                "prev_event_hash",
                "event_hash",
                "event_schema",
            }.issubset(columns_after)
        )
        self.assertTrue(store.migration_backup_path.exists())
        with sqlite3.connect(store.migration_backup_path) as backup:
            self.assertEqual(backup.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM journal_events").fetchone()[0], 1)
        self.assertEqual(
            list(store.migration_backup_path.parent.glob(".operations.pre-v1.1.db.tmp-*")),
            [],
        )
        self.assertEqual(store.get_record(legacy_id)["title"], "Legacy decision")
        self.assertEqual(store.get_record(legacy_id)["integrity_status"], "verified")
        self.assertEqual(created["tags"], ["migration"])

    def test_tampering_is_reported_without_exposing_hash_material(self):
        db_path = self.tmp_path / "plugin" / "data" / "operations.db"
        store = JournalStore(db_path)
        record = store.create_record(
            category="decision",
            title="Original decision",
            summary="This event is protected by a record-local chain.",
            source="manual",
        )

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE journal_events SET title='Changed after commit' WHERE record_id=?",
                (record["record_id"],),
            )

        projected = store.get_record(record["record_id"])
        self.assertEqual(projected["integrity_status"], "failed")
        self.assertNotIn("event_hash", projected)
        self.assertEqual(store.verify_integrity()["failure_code"], "hash_mismatch")
        with self.assertRaisesRegex(
            InvalidJournalEntry, "journal integrity verification failed"
        ):
            store.create_record(
                category="outcome",
                title="Blocked write",
                summary="Writes stop when retained history does not verify.",
                source="manual",
            )

    def test_event_schema_downgrade_cannot_bypass_tamper_detection(self):
        db_path = self.tmp_path / "plugin" / "data" / "operations.db"
        store = JournalStore(db_path)
        record = store.create_record(
            category="decision",
            title="Protected decision",
            summary="Both events must remain in the current integrity schema.",
            source="manual",
            sealed=True,
        )

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE journal_events SET title='Changed',event_schema=NULL "
                "WHERE record_id=? AND event_type='created'",
                (record["record_id"],),
            )

        projected = store.get_record(record["record_id"])
        self.assertEqual(projected["integrity_status"], "failed")
        self.assertEqual(store.verify_integrity()["failure_code"], "hash_mismatch")
        with self.assertRaisesRegex(
            InvalidJournalEntry, "journal integrity verification failed"
        ):
            store.create_record(
                category="outcome",
                title="Blocked downgrade",
                summary="The mixed integrity schema must fail closed.",
                source="manual",
            )

    def test_retention_and_max_records_prune_whole_record_histories(self):
        db_path = self.tmp_path / "plugin" / "data" / "operations.db"
        clock = MutableClock(datetime(2025, 1, 1, tzinfo=timezone.utc))
        store = JournalStore(db_path, retention_days=365, max_records=2, clock=clock)

        old = store.create_record(
            category="outcome",
            title="Old",
            summary="Expired outcome.",
            source="manual",
            sealed=True,
        )
        clock.value = datetime(2026, 1, 2, tzinfo=timezone.utc)
        first = store.create_record(
            category="outcome",
            title="First",
            summary="First retained outcome.",
            source="manual",
        )
        clock.value += timedelta(seconds=1)
        second = store.create_record(
            category="decision",
            title="Second",
            summary="Second retained decision.",
            source="manual",
        )
        clock.value += timedelta(seconds=1)
        third = store.create_record(
            category="decision",
            title="Third",
            summary="Third retained decision.",
            source="manual",
        )

        records = store.list_records(limit=20)
        self.assertEqual(
            [record["record_id"] for record in records],
            [third["record_id"], second["record_id"]],
        )
        self.assertIsNone(store.get_record(old["record_id"]))
        self.assertIsNone(store.get_record(first["record_id"]))

        with sqlite3.connect(db_path) as conn:
            remaining = {
                row[0]
                for row in conn.execute("SELECT DISTINCT record_id FROM journal_events")
            }
        self.assertEqual(remaining, {second["record_id"], third["record_id"]})

    @unittest.skipIf(sys.platform.startswith("win"), "POSIX mode bits are not enforced on Windows")
    def test_permissions_are_restrictive(self):
        plugin_root = self.tmp_path / "plugin"
        db_path = plugin_root / "data" / "operations.db"
        store = JournalStore(db_path)
        store.create_record(
            category="decision",
            title="Permission check",
            summary="Database and directories stay private.",
            source="manual",
        )

        self.assertEqual(_mode(plugin_root), 0o700)
        self.assertEqual(_mode(db_path.parent), 0o700)
        self.assertEqual(_mode(db_path), 0o600)
        for sidecar in (Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
            if sidecar.exists():
                self.assertEqual(_mode(sidecar), 0o600)

    def test_validation_and_not_found_do_not_append_events(self):
        db_path = self.tmp_path / "plugin" / "data" / "operations.db"
        store = JournalStore(db_path)

        invalid = [
            {"category": "prompt", "title": "No", "summary": "No", "source": "manual"},
            {"category": "decision", "title": "", "summary": "No", "source": "manual"},
            {
                "category": "decision",
                "title": "x" * 121,
                "summary": "No",
                "source": "manual",
            },
            {
                "category": "decision",
                "title": "No control\x00characters",
                "summary": "No",
                "source": "manual",
            },
            {
                "category": "decision",
                "title": "No",
                "summary": "x" * 501,
                "source": "manual",
            },
            {
                "category": "decision",
                "title": "No",
                "summary": "No",
                "source": "raw prompt",
            },
        ]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(InvalidJournalEntry):
                store.create_record(**values)

        self.assertFalse(
            db_path.exists(), "invalid input must be rejected before storage is created"
        )

        store.create_record(
            category="decision", title="Valid", summary="A valid decision.", source="manual"
        )
        with sqlite3.connect(db_path) as conn:
            before = conn.execute("SELECT COUNT(*) FROM journal_events").fetchone()[0]

        with self.assertRaises(RecordNotFound):
            store.seal_record("f" * 32)

        with sqlite3.connect(db_path) as conn:
            after = conn.execute("SELECT COUNT(*) FROM journal_events").fetchone()[0]
        self.assertEqual(after, before)

    def test_read_only_connection_uri_never_initializes_schema(self):
        db_path = self.tmp_path / "plugin" / "data" / "operations.db"
        db_path.parent.mkdir(parents=True)
        sqlite3.connect(db_path).close()  # Existing but uninitialized native-looking file.

        store = JournalStore(db_path)
        with self.assertRaises(sqlite3.DatabaseError):
            store.list_records()

        with sqlite3.connect(db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        self.assertEqual(tables, [])


if __name__ == "__main__":
    unittest.main()
