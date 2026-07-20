from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_api():
    path = ROOT / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("newton_operations_test_api", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


api = _load_api()


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _native_fixture(home: Path, rows: int = 3) -> list[str]:
    secrets = [
        "PROMPT-SECRET",
        "MESSAGE-SECRET",
        "COMMAND-SECRET",
        "ERROR-SECRET",
        "chat-user-123",
        "session-secret-id",
        "task-secret-id",
        "delegation-secret-id",
    ]

    _write_json(
        home / "gateway_state.json",
        {
            "gateway_state": "running",
            "active_agents": 2,
            "updated_at": "2026-07-19T12:00:00Z",
            "pid": 456,
            "argv": ["python", secrets[2]],
            "exit_reason": secrets[3],
            "platforms": {
                "telegram": {
                    "state": "connected",
                    "updated_at": "2026-07-19T12:00:00Z",
                    "error_message": secrets[3],
                    "chat_id": secrets[4],
                }
            },
        },
    )
    _write_json(
        home / "processes.json",
        [
            {
                "session_id": secrets[5],
                "command": f"run {secrets[2]}",
                "pid": 999,
                "cwd": "/secret/path",
                "started_at": 1_785_000_000 + i,
                "task_id": secrets[6],
                "watcher_chat_id": secrets[4],
                "watcher_user_id": secrets[4],
                "pid_scope": "host",
                "notify_on_complete": True,
            }
            for i in range(rows)
        ],
    )
    _write_json(
        home / "cron" / "jobs.json",
        {
            "jobs": [
                {
                    "id": f"job-secret-{i}",
                    "name": f"Safe job {i}",
                    "prompt": secrets[0],
                    "script": secrets[2],
                    "enabled": True,
                    "state": "scheduled",
                    "schedule_display": "every 5m",
                    "next_run_at": "2026-07-19T12:05:00Z",
                    "last_run_at": "2026-07-19T12:00:00Z",
                    "last_status": "success",
                    "last_error": secrets[3],
                    "origin": {"chat_id": secrets[4]},
                }
                for i in range(rows)
            ]
        },
    )

    state = sqlite3.connect(home / "state.db")
    state.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, source TEXT, user_id TEXT, chat_id TEXT,
            title TEXT, model TEXT, system_prompt TEXT, started_at REAL,
            ended_at REAL, message_count INTEGER, tool_call_count INTEGER,
            handoff_error TEXT
        );
        CREATE TABLE async_delegations (
            delegation_id TEXT PRIMARY KEY, origin_session TEXT,
            state TEXT, dispatched_at REAL, completed_at REAL,
            updated_at REAL, delivery_state TEXT, event_json TEXT,
            result_json TEXT, task_json TEXT
        );
        """
    )
    for i in range(rows):
        state.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"session-{i}-{secrets[5]}",
                "cli",
                secrets[4],
                secrets[4],
                f"Safe session title {i}",
                "safe-model",
                secrets[0],
                1_785_000_000 + i,
                None if i % 2 else 1_785_000_100 + i,
                5,
                2,
                secrets[3],
            ),
        )
        state.execute(
            "INSERT INTO async_delegations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"{secrets[7]}-{i}",
                secrets[5],
                "running" if i % 2 else "completed",
                1_785_000_000 + i,
                None,
                1_785_000_050 + i,
                "pending",
                secrets[1],
                secrets[1],
                secrets[0],
            ),
        )
    state.commit()
    state.close()

    executions = sqlite3.connect(home / "cron" / "executions.db")
    executions.execute(
        """CREATE TABLE executions (
            id TEXT PRIMARY KEY, job_id TEXT, source TEXT, process_id TEXT,
            pid INTEGER, status TEXT, claimed_at TEXT, started_at TEXT,
            finished_at TEXT, error TEXT
        )"""
    )
    for i in range(rows):
        executions.execute(
            "INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"execution-secret-{i}",
                f"job-secret-{i}",
                "built-in",
                "process-secret",
                123,
                "completed",
                "2026-07-19T12:00:00Z",
                "2026-07-19T12:00:01Z",
                "2026-07-19T12:00:02Z",
                secrets[3],
            ),
        )
    executions.commit()
    executions.close()

    kanban = sqlite3.connect(home / "kanban.db")
    kanban.executescript(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY, title TEXT, body TEXT, tenant TEXT, assignee TEXT,
            status TEXT, priority INTEGER, created_by TEXT,
            created_at INTEGER, started_at INTEGER, completed_at INTEGER,
            result TEXT, last_failure_error TEXT, session_id TEXT
        );
        CREATE TABLE task_links (parent_id TEXT, child_id TEXT);
        CREATE TABLE task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, profile TEXT, status TEXT,
            started_at INTEGER, ended_at INTEGER, outcome TEXT,
            last_heartbeat_at INTEGER, max_runtime_seconds INTEGER
        );
        """
    )
    for i in range(rows):
        kanban.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"{secrets[6]}-{i}",
                f"Safe task title {i}",
                secrets[1],
                "default",
                "default",
                "running" if i % 2 else "done",
                i,
                secrets[4],
                1_785_000_000 + i,
                1_785_000_010 + i,
                None,
                secrets[1],
                secrets[3],
                secrets[5],
            ),
        )
        kanban.execute(
            """INSERT INTO task_runs(
                task_id,profile,status,started_at,ended_at,outcome,last_heartbeat_at,max_runtime_seconds
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                f"{secrets[6]}-{i}",
                "default",
                "running" if i % 2 else "completed",
                1_785_000_010 + i,
                None if i % 2 else 1_785_000_020 + i,
                None if i % 2 else "success",
                1_785_000_050 + i,
                3600,
            ),
        )
    if rows >= 4:
        kanban.execute(
            "INSERT INTO task_links(parent_id,child_id) VALUES(?,?)",
            (f"{secrets[6]}-1", f"{secrets[6]}-3"),
        )
    kanban.commit()
    kanban.close()
    return secrets


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _load_plugin_module():
    path = ROOT / "__init__.py"
    name = "newton_operations_plugin_test"
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(ROOT)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PluginApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        root = Path(self._temp.name)
        self.home = root / "home"
        self.plugin_root = root / "plugin"
        self.home.mkdir(mode=0o700)

        old = (api.HERMES_HOME, api.PLUGIN_ROOT, api.STORE_PATH, api._gateway_liveness)
        api.HERMES_HOME = self.home
        api.PLUGIN_ROOT = self.plugin_root
        api.STORE_PATH = self.plugin_root / "data" / "operations.db"
        api._gateway_liveness = lambda: True
        self.addCleanup(self._restore_api_paths, old)

        app = FastAPI()
        app.include_router(api.router, prefix="/api/plugins/newton-operations")
        self.http = TestClient(app)

    @staticmethod
    def _restore_api_paths(old) -> None:
        api.HERMES_HOME, api.PLUGIN_ROOT, api.STORE_PATH, api._gateway_liveness = old

    def test_router_exposes_only_required_operations_routes(self):
        routes = {
            (route.path, tuple(sorted(route.methods or []))) for route in api.router.routes
        }
        self.assertEqual(
            routes,
            {
                ("/health", ("GET",)),
                ("/snapshot", ("GET",)),
                ("/journal", ("GET",)),
                ("/journal", ("POST",)),
                ("/journal/integrity", ("GET",)),
                ("/journal/export", ("GET",)),
                ("/journal/{record_id}/seal", ("POST",)),
            },
        )

    def test_all_get_endpoints_leave_missing_journal_store_untouched(self):
        self.assertEqual(
            self.http.get("/api/plugins/newton-operations/health").status_code, 200
        )
        self.assertEqual(
            self.http.get("/api/plugins/newton-operations/snapshot").status_code, 200
        )
        self.assertEqual(
            self.http.get("/api/plugins/newton-operations/journal").status_code, 200
        )
        self.assertEqual(
            self.http.get("/api/plugins/newton-operations/journal/integrity").status_code,
            200,
        )
        self.assertEqual(
            self.http.get("/api/plugins/newton-operations/journal/export").status_code,
            200,
        )
        shared = self.http.get(
            "/api/plugins/newton-operations/snapshot?share=true"
        )
        self.assertEqual(shared.status_code, 200)
        self.assertTrue(shared.json()["share_mode"])
        self.assertEqual(shared.json()["profile"], "sanitized")

        self.assertFalse(self.plugin_root.exists())
        self.assertFalse((self.plugin_root / "data" / "operations.db").exists())

    def test_snapshot_is_sanitized_and_each_native_component_is_bounded(self):
        secrets = _native_fixture(self.home, rows=80)

        response = self.http.get("/api/plugins/newton-operations/snapshot")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["gateway"]["status"], "ok")
        self.assertEqual(payload["gateway"]["state"], "running")
        self.assertLessEqual(len(payload["sessions"]["items"]), api.SESSION_LIMIT)
        self.assertLessEqual(
            len(payload["delegations"]["items"]), api.DELEGATION_LIMIT
        )
        self.assertLessEqual(len(payload["processes"]["items"]), api.PROCESS_LIMIT)
        self.assertLessEqual(len(payload["cron"]["jobs"]), api.CRON_JOB_LIMIT)
        self.assertLessEqual(
            len(payload["cron"]["executions"]), api.CRON_EXECUTION_LIMIT
        )
        self.assertLessEqual(len(payload["kanban"]["items"]), api.KANBAN_LIMIT)
        self.assertLessEqual(len(payload["kanban"]["edges"]), 24)
        self.assertLessEqual(len(payload["timeline"]["items"]), api.TIMELINE_LIMIT)
        self.assertLessEqual(len(payload["attention"]["items"]), api.ATTENTION_LIMIT)
        self.assertEqual(len(payload["diagnostics"]["items"]), 7)
        self.assertEqual(payload["schema_version"], 2)
        self.assertTrue(
            all(len(job.get("history", [])) <= api.CRON_HISTORY_LIMIT for job in payload["cron"]["jobs"])
        )
        self.assertTrue(
            all(
                len(task.get("run_history", [])) <= api.KANBAN_RUN_LIMIT
                for task in payload["kanban"]["items"]
            )
        )
        self.assertTrue(
            all(
                edge["parent"].startswith("K") and edge["child"].startswith("K")
                for edge in payload["kanban"]["edges"]
            )
        )
        self.assertLessEqual(
            len(payload["journal"]["items"]), api.JOURNAL_SNAPSHOT_LIMIT
        )

        serialized = json.dumps(payload, sort_keys=True)
        for secret in secrets:
            self.assertNotIn(secret, serialized)
        forbidden_keys = {
            "id",
            "session_id",
            "chat_id",
            "user_id",
            "task_id",
            "delegation_id",
            "command",
            "prompt",
            "message",
            "body",
            "error",
            "result",
            "argv",
            "pid",
            "cwd",
        }
        self.assertTrue(forbidden_keys.isdisjoint(set(_walk_keys(payload))))

        self.assertTrue(payload["sessions"]["items"][0]["title"].startswith("Safe session title"))
        self.assertTrue(payload["cron"]["jobs"][0]["name"].startswith("Safe job"))
        self.assertTrue(payload["kanban"]["items"][0]["title"].startswith("Safe task title"))

    def test_share_snapshot_uses_server_generated_neutral_data(self):
        secrets = _native_fixture(self.home, rows=4)

        payload = self.http.get(
            "/api/plugins/newton-operations/snapshot?share=true"
        ).json()

        serialized = json.dumps(payload, sort_keys=True)
        self.assertTrue(payload["share_mode"])
        self.assertEqual(payload["profile"], "sanitized")
        self.assertEqual(payload["journal"]["items"][0]["integrity_status"], "verified")
        self.assertNotIn("record_id", set(_walk_keys(payload)))
        self.assertNotIn("event_hash", set(_walk_keys(payload)))
        for secret in secrets:
            self.assertNotIn(secret, serialized)

    def test_nested_untrusted_json_values_are_not_stringified_into_projection(self):
        private_marker = "NESTED-PRIVATE-VALUE"
        _write_json(
            self.home / "gateway_state.json",
            {
                "gateway_state": "running",
                "updated_at": {"private": private_marker},
                "platforms": {
                    "channel": {
                        "state": "connected",
                        "updated_at": [private_marker],
                    }
                },
            },
        )
        _write_json(
            self.home / "processes.json",
            [
                {
                    "started_at": {"private": private_marker},
                    "pid_scope": [private_marker],
                    "notify_on_complete": {"private": private_marker},
                }
            ],
        )
        _write_json(
            self.home / "cron" / "jobs.json",
            {
                "jobs": [
                    {
                        "name": [private_marker],
                        "enabled": {"private": private_marker},
                        "schedule": {"cron": {"private": private_marker}},
                        "next_run_at": {"private": private_marker},
                        "last_run_at": [private_marker],
                    }
                ]
            },
        )

        payload = self.http.get("/api/plugins/newton-operations/snapshot").json()
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn(private_marker, serialized)
        self.assertIsNone(payload["gateway"]["updated_at"])
        self.assertIsNone(payload["processes"]["items"][0]["started_at"])
        self.assertEqual(payload["cron"]["jobs"][0]["schedule"], "Configured schedule")

    def test_profile_scoped_sources_exclude_other_profile_rows(self):
        state = sqlite3.connect(self.home / "state.db")
        state.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, session_key TEXT, profile_name TEXT,
                title TEXT, source TEXT, model TEXT, started_at REAL,
                ended_at REAL, message_count INTEGER, tool_call_count INTEGER,
                archived INTEGER
            );
            CREATE TABLE async_delegations (
                delegation_id TEXT PRIMARY KEY, origin_session TEXT,
                origin_ui_session_id TEXT, parent_session_id TEXT,
                state TEXT, dispatched_at REAL, completed_at REAL,
                updated_at REAL, delivery_state TEXT
            );
            """
        )
        for profile, suffix in (("default", "visible"), ("other", "hidden")):
            state.execute(
                "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"session-{suffix}",
                    f"key-{suffix}",
                    profile,
                    f"Session {suffix}",
                    "cli",
                    "model",
                    1_785_000_000,
                    None,
                    1,
                    1,
                    0,
                ),
            )
            state.execute(
                "INSERT INTO async_delegations VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    f"delegation-{suffix}",
                    f"key-{suffix}",
                    "",
                    f"session-{suffix}",
                    "running",
                    1_785_000_000,
                    None,
                    1_785_000_010,
                    "pending",
                ),
            )
        state.commit()
        state.close()

        kanban = sqlite3.connect(self.home / "kanban.db")
        kanban.execute(
            """CREATE TABLE tasks (
                id TEXT PRIMARY KEY, title TEXT, tenant TEXT, assignee TEXT, status TEXT,
                priority INTEGER, created_at REAL, started_at REAL,
                completed_at REAL
            )"""
        )
        kanban.execute(
            "INSERT INTO tasks VALUES('visible','Task visible','default','other','running',1,?,?,NULL)",
            (1_785_000_000, 1_785_000_010),
        )
        kanban.execute(
            "INSERT INTO tasks VALUES('hidden','Task hidden','other','default','running',1,?,?,NULL)",
            (1_785_000_000, 1_785_000_010),
        )
        kanban.commit()
        kanban.close()

        payload = self.http.get("/api/plugins/newton-operations/snapshot").json()
        serialized = json.dumps(payload, sort_keys=True)
        self.assertIn("Session visible", serialized)
        self.assertIn("Task visible", serialized)
        self.assertNotIn("Session hidden", serialized)
        self.assertNotIn("Task hidden", serialized)
        self.assertEqual(payload["delegations"]["active_count"], 1)

    def test_gateway_health_uses_canonical_liveness_not_persisted_state(self):
        _native_fixture(self.home, rows=1)
        api._gateway_liveness = lambda: False

        health = self.http.get("/api/plugins/newton-operations/health").json()
        snapshot = self.http.get("/api/plugins/newton-operations/snapshot").json()

        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["gateway"]["status"], "ok")
        self.assertEqual(health["gateway"]["state"], "stopped")
        self.assertTrue(
            any(
                item.get("title") == "Gateway is not running"
                and item.get("status") == "stopped"
                and item.get("source") == "gateway"
                and item.get("severity") == "critical"
                and item.get("why")
                and item.get("next_step")
                for item in snapshot["attention"]["items"]
            )
        )

    def test_gateway_health_fails_closed_when_liveness_check_is_unavailable(self):
        _native_fixture(self.home, rows=1)
        api._gateway_liveness = lambda: None

        health = self.http.get("/api/plugins/newton-operations/health").json()

        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["gateway"]["status"], "degraded")
        self.assertEqual(health["gateway"]["state"], "unknown")

    def test_non_connected_gateway_platform_becomes_sanitized_attention(self):
        _native_fixture(self.home, rows=1)
        _write_json(
            self.home / "gateway_state.json",
            {
                "gateway_state": "running",
                "platforms": {
                    "matrix": {
                        "state": "retrying",
                        "error_message": "PRIVATE-ERROR",
                        "chat_id": "PRIVATE-CHAT",
                    }
                },
            },
        )

        payload = self.http.get("/api/plugins/newton-operations/snapshot").json()
        self.assertTrue(
            any(
                item.get("title") == "Matrix channel retrying"
                and item.get("status") == "retrying"
                and item.get("source") == "gateway"
                and item.get("severity") == "warning"
                for item in payload["attention"]["items"]
            )
        )
        self.assertNotIn("PRIVATE-ERROR", json.dumps(payload))
        self.assertNotIn("PRIVATE-CHAT", json.dumps(payload))

    def test_snapshot_degrades_per_component_without_raw_exception_text(self):
        (self.home / "state.db").write_bytes(b"not a sqlite database: PRIVATE-ERROR")
        _write_json(self.home / "gateway_state.json", {"gateway_state": "running"})
        (self.home / "processes.json").write_text(
            "{broken PRIVATE-ERROR", encoding="utf-8"
        )

        payload = self.http.get(
            "/api/plugins/newton-operations/snapshot"
        ).json()

        self.assertEqual(payload["gateway"]["status"], "ok")
        self.assertEqual(payload["sessions"]["status"], "degraded")
        self.assertEqual(payload["delegations"]["status"], "degraded")
        self.assertEqual(payload["processes"]["status"], "degraded")
        self.assertEqual(payload["cron"]["status"], "missing")
        self.assertEqual(payload["kanban"]["status"], "missing")
        self.assertNotIn("PRIVATE-ERROR", json.dumps(payload))

    def test_journal_post_list_and_seal_round_trip(self):
        create = self.http.post(
            "/api/plugins/newton-operations/journal",
            json={
                "category": "decision",
                "title": "Keep Operations context-free",
                "summary": "Do not inject dashboard state into LLM messages.",
            },
        )
        self.assertEqual(create.status_code, 201)
        record = create.json()
        self.assertEqual(record["status"], "open")
        self.assertTrue((self.plugin_root / "data" / "operations.db").exists())

        listed = self.http.get("/api/plugins/newton-operations/journal?limit=10")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["items"], [record])

        sealed = self.http.post(
            f"/api/plugins/newton-operations/journal/{record['record_id']}/seal"
        )
        self.assertEqual(sealed.status_code, 200)
        self.assertEqual(sealed.json()["status"], "sealed")
        self.assertEqual(sealed.json()["event_count"], 2)

        missing = self.http.post(
            "/api/plugins/newton-operations/journal/ffffffffffffffffffffffffffffffff/seal"
        )
        self.assertEqual(missing.status_code, 404)

    def test_journal_metadata_search_export_and_supersession(self):
        first = self.http.post(
            "/api/plugins/newton-operations/journal",
            json={
                "category": "decision",
                "title": "Keep polling bounded",
                "summary": "Use adaptive refresh without adding another service.",
                "tags": ["architecture", "privacy"],
                "related": ["Operations timeline"],
            },
        )
        self.assertEqual(first.status_code, 201)
        original = first.json()

        replacement = self.http.post(
            "/api/plugins/newton-operations/journal",
            json={
                "category": "outcome",
                "title": "Adaptive polling shipped",
                "summary": "Refresh pauses in hidden tabs and backs off while idle.",
                "tags": ["architecture"],
                "related": ["Operations timeline"],
                "supersedes": original["record_id"],
            },
        )
        self.assertEqual(replacement.status_code, 201)
        newer = replacement.json()
        self.assertEqual(newer["supersedes"], original["record_id"])

        listed = self.http.get(
            "/api/plugins/newton-operations/journal?q=shipped&tag=architecture"
        ).json()["items"]
        self.assertEqual([item["record_id"] for item in listed], [newer["record_id"]])

        seal = self.http.post(
            f"/api/plugins/newton-operations/journal/{newer['record_id']}/seal"
        )
        self.assertEqual(seal.status_code, 200)
        self.assertEqual(seal.json()["integrity_status"], "verified")
        self.assertNotIn("event_hash", seal.json())
        integrity = self.http.get(
            "/api/plugins/newton-operations/journal/integrity"
        )
        self.assertEqual(integrity.status_code, 200)
        self.assertEqual(integrity.json()["status"], "verified")

        markdown = self.http.get(
            "/api/plugins/newton-operations/journal/export?format=markdown"
        )
        self.assertEqual(markdown.status_code, 200)
        self.assertIn("# Newton Operations journal", markdown.text)
        self.assertIn("Adaptive polling shipped", markdown.text)
        self.assertNotIn(original["record_id"], markdown.text)

        exported = self.http.get(
            "/api/plugins/newton-operations/journal/export?format=json"
        )
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.json()["schema_version"], 1)
        self.assertEqual(len(exported.json()["records"]), 2)

    def test_journal_api_rejects_invalid_manual_records_without_creating_store(self):
        bodies = [
            {"category": "lifecycle", "title": "Not manual", "summary": "No"},
            {"category": "decision", "title": "", "summary": "No"},
            {"category": "decision", "title": "Good", "summary": "bad\u0000value"},
            {
                "category": "decision",
                "title": "Good",
                "summary": "No",
                "tags": ["Not Safe"],
            },
            {
                "category": "decision",
                "title": "Good",
                "summary": "No",
                "supersedes": "f" * 32,
            },
        ]
        for body in bodies:
            with self.subTest(body=body):
                response = self.http.post(
                    "/api/plugins/newton-operations/journal", json=body
                )
                self.assertEqual(response.status_code, 422)
                self.assertFalse(self.plugin_root.exists())

    def test_hook_profile_resolution_uses_explicit_or_session_namespace(self):
        plugin = _load_plugin_module()

        self.assertEqual(
            plugin._runtime_profile_name({"profile_name": "profile-alpha"}),
            "profile-alpha",
        )
        self.assertEqual(
            plugin._runtime_profile_name({"session_key": "agent:main:signal:chat"}),
            "default",
        )
        self.assertEqual(
            plugin._runtime_profile_name({"session_key": "agent:profile-beta:signal:chat"}),
            "profile-beta",
        )

    def test_lifecycle_hooks_are_nonblocking_profile_scoped_and_private(self):
        plugin = _load_plugin_module()
        store_path = self.plugin_root / "data" / "operations.db"
        plugin.STORE_PATH = store_path

        callbacks = {}

        class Context:
            profile_name = "default"

            def register_hook(self, name, callback):
                callbacks[name] = callback

        plugin.register(Context())
        self.assertEqual(
            set(callbacks),
            {
                "kanban_task_completed",
                "kanban_task_blocked",
                "post_approval_response",
            },
        )

        # The runtime profile resolver is independently tested by Hermes; pin its
        # context fallback here while retaining explicit-profile precedence.
        plugin._runtime_profile_name = lambda fields: str(
            fields.get("profile_name") or "default"
        )
        callbacks["kanban_task_completed"](
            task_id="task-private-id",
            summary="raw private task result",
            assignee="private-user",
            profile_name="default",
        )
        callbacks["kanban_task_blocked"](
            task_id="task-private-id",
            reason="raw private error",
            assignee="private-user",
            profile_name="default",
        )
        callbacks["post_approval_response"](
            choice="deny",
            surface="gateway",
            command="rm -rf private-command",
            description="private description",
            session_key="private-session",
            tool_call_id="private-call",
        )
        # A multiplexed secondary-profile event must not enter this journal.
        callbacks["kanban_task_completed"](
            task_id="secondary-task",
            summary="secondary raw result",
            profile_name="secondary-profile",
        )
        plugin._EVENT_QUEUE.join()

        from newton_operations_plugin_test.newton_ops_store import JournalStore

        records = JournalStore(store_path).list_records(limit=10)
        self.assertEqual(len(records), 3)
        self.assertTrue(all(record["category"] == "lifecycle" for record in records))
        self.assertTrue(all(record["status"] == "sealed" for record in records))
        serialized = json.dumps(records)
        for private in (
            "task-private-id",
            "raw private task result",
            "private-user",
            "raw private error",
            "private-command",
            "private description",
            "private-session",
            "private-call",
            "secondary-task",
            "secondary raw result",
            "secondary-profile",
        ):
            self.assertNotIn(private, serialized)

        # Hook callbacks enqueue and return without waiting for SQLite or fsync.
        original_write = plugin._write_record
        release = threading.Event()

        def slow_write(title, summary):
            release.wait(timeout=1)
            original_write(title, summary)

        plugin._write_record = slow_write
        started = time.monotonic()
        self.assertIsNone(callbacks["post_approval_response"](choice="deny"))
        self.assertLess(time.monotonic() - started, 0.1)
        release.set()
        plugin._EVENT_QUEUE.join()

        # Broken journal storage is swallowed on the worker and cannot affect Hermes.
        plugin.STORE_PATH = Path(self._temp.name)  # sqlite path is a directory
        self.assertIsNone(callbacks["post_approval_response"](choice="deny"))
        plugin._EVENT_QUEUE.join()

    def test_plugin_manifest_declares_no_tools_or_context_hooks(self):
        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        self.assertNotIn("provides_tools", manifest)
        self.assertNotIn("pre_llm_call", manifest)
        self.assertNotIn("pre_gateway_dispatch", manifest)
        for hook in (
            "kanban_task_completed",
            "kanban_task_blocked",
            "post_approval_response",
        ):
            self.assertIn(hook, manifest)


if __name__ == "__main__":
    unittest.main()
