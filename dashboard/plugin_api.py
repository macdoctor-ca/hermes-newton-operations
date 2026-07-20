"""Authenticated backend routes for the Newton Operations dashboard plugin."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from newton_ops_store import InvalidJournalEntry, JournalStore, RecordNotFound  # noqa: E402

try:  # Hermes runtime; tests intentionally exercise the fallback.
    from hermes_constants import get_process_hermes_home  # type: ignore[import-not-found]

    PROCESS_HERMES_HOME = get_process_hermes_home()
except Exception:  # pragma: no cover - runtime import availability
    PROCESS_HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")

HERMES_HOME = PROCESS_HERMES_HOME
STORE_PATH = PLUGIN_ROOT / "data" / "operations.db"

SESSION_LIMIT = 8
DELEGATION_LIMIT = 8
PROCESS_LIMIT = 12
CRON_JOB_LIMIT = 12
CRON_EXECUTION_LIMIT = 16
CRON_EXECUTION_SCAN_LIMIT = 160
CRON_HISTORY_LIMIT = 7
KANBAN_LIMIT = 12
KANBAN_SCAN_LIMIT = 32
KANBAN_RUN_LIMIT = 3
JOURNAL_SNAPSHOT_LIMIT = 8
TIMELINE_LIMIT = 40
ATTENTION_LIMIT = 16
MAX_JSON_BYTES = 5 * 1024 * 1024

router = APIRouter()
_SAFE_STATE_RE = re.compile(r"^[a-zA-Z0-9 _.-]{1,48}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
_ROUTES = {
    "gateway": "/operations#gateway",
    "sessions": "/sessions",
    "delegations": "/operations#runtime",
    "processes": "/operations#runtime",
    "cron": "/cron",
    "kanban": "/kanban",
    "journal": "/operations#journal",
    "diagnostics": "/operations#diagnostics",
}


class JournalCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    category: Literal["decision", "outcome"] = Field(
        validation_alias=AliasChoices("category", "kind")
    )
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=6)
    related: list[str] = Field(default_factory=list, max_length=6)
    supersedes: str | None = Field(default=None, max_length=32)

    @field_validator("title", "summary")
    @classmethod
    def safe_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or _CONTROL_RE.search(cleaned):
            raise ValueError("text contains unsupported control characters")
        return cleaned

    @field_validator("tags")
    @classmethod
    def safe_tags(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for raw in values:
            value = raw.strip().lower()
            if not _SAFE_TAG_RE.fullmatch(value):
                raise ValueError("tags must use lowercase letters, numbers, and hyphens")
            if value not in result:
                result.append(value)
        return result

    @field_validator("related")
    @classmethod
    def safe_related(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for raw in values:
            value = raw.strip()
            if not value or len(value) > 80 or _CONTROL_RE.search(value):
                raise ValueError("related references must be 1 to 80 safe characters")
            if value not in result:
                result.append(value)
        return result


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean(value: Any, maximum: int = 160, fallback: str = "") -> str:
    if value is None or not isinstance(value, (str, int, float, bool)):
        return fallback
    text = _CONTROL_RE.sub(" ", str(value)).strip()
    return text[:maximum] if text else fallback


def _state(value: Any, fallback: str = "unknown") -> str:
    text = _clean(value, 48, fallback).lower()
    return text if _SAFE_STATE_RE.fullmatch(text) else fallback


def _integer(value: Any, fallback: int = 0) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _boolean(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return fallback


def _parse_time(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    text = value.strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None:
        try:
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp(value: Any) -> str | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _schedule_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("display", "expr", "cron", "every", "at"):
            candidate = _clean(value.get(key), 80)
            if candidate:
                return candidate
        return "Configured schedule"
    return _clean(value, 80, "Configured schedule")


def _age_seconds(value: Any) -> int | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return max(0, int((_now() - parsed).total_seconds()))


def _duration_seconds(started: Any, finished: Any = None) -> int | None:
    start = _parse_time(started)
    end = _parse_time(finished) if finished not in (None, "") else _now()
    if start is None or end is None or end < start:
        return None
    return min(int((end - start).total_seconds()), 31_536_000)


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(path.name)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("oversized")
    return json.loads(path.read_text(encoding="utf-8"))


def _connect_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path.name)
    encoded = quote(str(path.resolve()), safe="/")
    conn = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=2000")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    safe = table.replace('"', '""')
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{safe}")')}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
        ).fetchone()
        is not None
    )


def _row_value(row: sqlite3.Row, name: str) -> Any:
    return row[name] if name in row.keys() else None


def _missing(**values: Any) -> dict[str, Any]:
    return {"status": "missing", **values}


def _degraded(**values: Any) -> dict[str, Any]:
    return {"status": "degraded", **values}


def _gateway_liveness() -> bool | None:
    """Return canonical gateway liveness without mutating stale PID state."""
    try:
        from gateway.status import get_running_pid_cached

        return (
            get_running_pid_cached(
                HERMES_HOME / "gateway.pid",
                cleanup_stale=False,
            )
            is not None
        )
    except Exception:
        return None


def _gateway() -> dict[str, Any]:
    try:
        data = _read_json(HERMES_HOME / "gateway_state.json")
        if not isinstance(data, dict):
            raise ValueError("shape")
        platforms = []
        raw_platforms = data.get("platforms") or {}
        if isinstance(raw_platforms, dict):
            for name, value in sorted(raw_platforms.items()):
                if not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", str(name)):
                    continue
                value = value if isinstance(value, dict) else {}
                platforms.append(
                    {
                        "name": str(name),
                        "state": _state(value.get("state")),
                        "updated_at": _timestamp(value.get("updated_at")),
                    }
                )
        live = _gateway_liveness()
        if live is None:
            return _degraded(
                state="unknown",
                active_agents=0,
                updated_at=_timestamp(data.get("updated_at")),
                profile=_profile_name(),
                platforms=platforms[:16],
            )
        return {
            "status": "ok",
            "state": "running" if live else "stopped",
            "active_agents": max(0, _integer(data.get("active_agents"))),
            "updated_at": _timestamp(data.get("updated_at")),
            "profile": _profile_name(),
            "platforms": platforms[:16],
        }
    except FileNotFoundError:
        return _missing(state="unknown", active_agents=0, platforms=[])
    except Exception:
        return _degraded(state="unknown", active_agents=0, platforms=[])


def _sessions() -> dict[str, Any]:
    try:
        with _connect_ro(HERMES_HOME / "state.db") as conn:
            cols = _columns(conn, "sessions")
            required = {"title", "source", "started_at", "ended_at", "message_count", "tool_call_count"}
            if not required.issubset(cols):
                raise sqlite3.DatabaseError("schema")
            archived = "archived" in cols
            has_model = "model" in cols
            profiled = "profile_name" in cols
            profile = _profile_name()
            if profiled and archived:
                total = conn.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM sessions "
                    "WHERE profile_name=? AND COALESCE(archived,0)=0 LIMIT 10001)",
                    (profile,),
                ).fetchone()[0]
            elif profiled:
                total = conn.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM sessions "
                    "WHERE profile_name=? LIMIT 10001)",
                    (profile,),
                ).fetchone()[0]
            elif archived:
                total = conn.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM sessions "
                    "WHERE COALESCE(archived,0)=0 LIMIT 10001)"
                ).fetchone()[0]
            else:
                total = conn.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM sessions LIMIT 10001)"
                ).fetchone()[0]
            if profiled and archived and has_model:
                query = (
                    "SELECT title,source,model,started_at,ended_at,message_count,tool_call_count "
                    "FROM sessions WHERE profile_name=? AND COALESCE(archived,0)=0 "
                    "ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?"
                )
                parameters = (profile, SESSION_LIMIT)
            elif profiled and archived:
                query = (
                    "SELECT title,source,NULL AS model,started_at,ended_at,message_count,tool_call_count "
                    "FROM sessions WHERE profile_name=? AND COALESCE(archived,0)=0 "
                    "ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?"
                )
                parameters = (profile, SESSION_LIMIT)
            elif profiled and has_model:
                query = (
                    "SELECT title,source,model,started_at,ended_at,message_count,tool_call_count "
                    "FROM sessions WHERE profile_name=? "
                    "ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?"
                )
                parameters = (profile, SESSION_LIMIT)
            elif profiled:
                query = (
                    "SELECT title,source,NULL AS model,started_at,ended_at,message_count,tool_call_count "
                    "FROM sessions WHERE profile_name=? "
                    "ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?"
                )
                parameters = (profile, SESSION_LIMIT)
            elif archived and has_model:
                query = (
                    "SELECT title,source,model,started_at,ended_at,message_count,tool_call_count "
                    "FROM sessions WHERE COALESCE(archived,0)=0 "
                    "ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?"
                )
                parameters = (SESSION_LIMIT,)
            elif archived:
                query = (
                    "SELECT title,source,NULL AS model,started_at,ended_at,message_count,tool_call_count "
                    "FROM sessions WHERE COALESCE(archived,0)=0 "
                    "ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?"
                )
                parameters = (SESSION_LIMIT,)
            elif has_model:
                query = (
                    "SELECT title,source,model,started_at,ended_at,message_count,tool_call_count "
                    "FROM sessions ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?"
                )
                parameters = (SESSION_LIMIT,)
            else:
                query = (
                    "SELECT title,source,NULL AS model,started_at,ended_at,message_count,tool_call_count "
                    "FROM sessions ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?"
                )
                parameters = (SESSION_LIMIT,)
            rows = conn.execute(query, parameters).fetchall()
        items = [
            {
                "title": _clean(row["title"], 120, "Untitled session"),
                "source": _state(row["source"], "unknown"),
                "model": _clean(row["model"], 80) or None,
                "status": "active" if row["ended_at"] is None else "completed",
                "started_at": _timestamp(row["started_at"]),
                "ended_at": _timestamp(row["ended_at"]),
                "updated_at": _timestamp(row["ended_at"] or row["started_at"]),
                "message_count": max(0, _integer(row["message_count"])),
                "tool_call_count": max(0, _integer(row["tool_call_count"])),
                "route": _ROUTES["sessions"],
            }
            for row in rows
        ]
        return {
            "status": "ok",
            "total": int(total),
            "total_is_lower_bound": int(total) >= 10_001,
            "items": items,
        }
    except FileNotFoundError:
        return _missing(total=0, items=[])
    except Exception:
        return _degraded(total=0, items=[])


def _delegations() -> dict[str, Any]:
    try:
        with _connect_ro(HERMES_HOME / "state.db") as conn:
            cols = _columns(conn, "async_delegations")
            required = {"state", "dispatched_at", "completed_at", "updated_at", "delivery_state"}
            if not required.issubset(cols):
                raise sqlite3.DatabaseError("schema")
            session_cols = _columns(conn, "sessions") if _table_exists(conn, "sessions") else set()
            profiled = {"id", "session_key", "profile_name"}.issubset(session_cols)
            if profiled:
                profile = _profile_name()
                total = conn.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM async_delegations d WHERE "
                    "EXISTS (SELECT 1 FROM sessions s WHERE s.profile_name=? AND "
                    "(s.id=d.parent_session_id OR s.id=d.origin_ui_session_id "
                    "OR s.session_key=d.origin_session)) LIMIT 10001)",
                    (profile,),
                ).fetchone()[0]
                active = conn.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM async_delegations d WHERE "
                    "EXISTS (SELECT 1 FROM sessions s WHERE s.profile_name=? AND "
                    "(s.id=d.parent_session_id OR s.id=d.origin_ui_session_id "
                    "OR s.session_key=d.origin_session)) "
                    "AND d.state IN ('running','finalizing') LIMIT 10001)",
                    (profile,),
                ).fetchone()[0]
                rows = conn.execute(
                    "SELECT d.state,d.dispatched_at,d.completed_at,d.updated_at,d.delivery_state "
                    "FROM async_delegations d WHERE "
                    "EXISTS (SELECT 1 FROM sessions s WHERE s.profile_name=? AND "
                    "(s.id=d.parent_session_id OR s.id=d.origin_ui_session_id "
                    "OR s.session_key=d.origin_session)) "
                    "AND d.state IN ('running','finalizing') "
                    "ORDER BY d.updated_at DESC LIMIT ?",
                    (profile, DELEGATION_LIMIT),
                ).fetchall()
            else:
                total = conn.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM async_delegations LIMIT 10001)"
                ).fetchone()[0]
                active = conn.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM async_delegations "
                    "WHERE state IN ('running','finalizing') LIMIT 10001)"
                ).fetchone()[0]
                rows = conn.execute(
                    "SELECT state,dispatched_at,completed_at,updated_at,delivery_state "
                    "FROM async_delegations WHERE state IN ('running','finalizing') "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (DELEGATION_LIMIT,),
                ).fetchall()
        items = [
            {
                "title": "Delegated agent task",
                "state": _state(row["state"]),
                "delivery_state": _state(row["delivery_state"]),
                "started_at": _timestamp(row["dispatched_at"]),
                "completed_at": _timestamp(row["completed_at"]),
                "updated_at": _timestamp(row["updated_at"]),
                "elapsed_seconds": _duration_seconds(row["dispatched_at"], row["completed_at"]),
                "route": _ROUTES["delegations"],
            }
            for row in rows
        ]
        return {
            "status": "ok",
            "total": int(total),
            "total_is_lower_bound": int(total) >= 10_001,
            "active_count": int(active),
            "active_is_lower_bound": int(active) >= 10_001,
            "items": items,
        }
    except FileNotFoundError:
        return _missing(total=0, active_count=0, items=[])
    except Exception:
        return _degraded(total=0, active_count=0, items=[])


def _processes() -> dict[str, Any]:
    try:
        data = _read_json(HERMES_HOME / "processes.json")
        if not isinstance(data, list):
            raise ValueError("shape")
        items = []
        for value in data[:PROCESS_LIMIT]:
            if not isinstance(value, dict):
                continue
            items.append(
                {
                    "title": "Background process",
                    "status": "running",
                    "started_at": _timestamp(value.get("started_at")),
                    "elapsed_seconds": _duration_seconds(value.get("started_at")),
                    "pid_scope": _state(value.get("pid_scope"), "unknown"),
                    "notify_on_complete": _boolean(value.get("notify_on_complete")),
                    "route": _ROUTES["processes"],
                }
            )
        return {"status": "ok", "count": len(data), "items": items}
    except FileNotFoundError:
        return _missing(count=0, items=[])
    except Exception:
        return _degraded(count=0, items=[])


def _cron() -> dict[str, Any]:
    jobs_path = HERMES_HOME / "cron" / "jobs.json"
    db_path = HERMES_HOME / "cron" / "executions.db"
    if not jobs_path.exists() and not db_path.exists():
        return _missing(total=0, enabled_count=0, overdue_count=0, jobs=[], executions=[])

    jobs: list[dict[str, Any]] = []
    raw_job_rows: list[dict[str, Any]] = []
    job_names: dict[str, str] = {}
    status_value = "ok"
    try:
        data = _read_json(jobs_path)
        raw_jobs = data.get("jobs", []) if isinstance(data, dict) else []
        if not isinstance(raw_jobs, list):
            raise ValueError("shape")
        for value in raw_jobs:
            if not isinstance(value, dict):
                continue
            opaque = str(value.get("id") or "")
            name = _clean(value.get("name"), 100, "Scheduled job")
            if opaque:
                job_names[opaque] = name
            raw_job_rows.append(value)
            if len(jobs) < CRON_JOB_LIMIT:
                enabled = _boolean(value.get("enabled"), value.get("state") != "paused")
                job_state = "paused" if not enabled else _state(
                    value.get("last_status") or value.get("state"), "scheduled"
                )
                next_run = value.get("next_run_at")
                overdue = bool(enabled and (_age_seconds(next_run) or 0) > 120 and job_state != "running")
                jobs.append(
                    {
                        "name": name,
                        "enabled": enabled,
                        "state": job_state,
                        "schedule": _schedule_text(value.get("schedule_display") or value.get("schedule")),
                        "last_run_at": _timestamp(value.get("last_run_at")),
                        "next_run_at": _timestamp(next_run),
                        "no_agent": _boolean(value.get("no_agent")),
                        "overdue": overdue,
                        "history": [],
                        "success_count": 0,
                        "failure_count": 0,
                        "reliability_percent": None,
                        "last_duration_seconds": None,
                        "route": _ROUTES["cron"],
                        "_opaque": opaque,
                    }
                )
        total = len(raw_job_rows)
        enabled_count = sum(
            1
            for value in raw_job_rows
            if _boolean(value.get("enabled"), value.get("state") != "paused")
        )
    except FileNotFoundError:
        total = enabled_count = 0
        status_value = "degraded"
    except Exception:
        total = enabled_count = 0
        status_value = "degraded"

    executions: list[dict[str, Any]] = []
    history_by_job: dict[str, list[dict[str, Any]]] = {}
    try:
        with _connect_ro(db_path) as conn:
            cols = _columns(conn, "executions")
            required = {"job_id", "status", "started_at", "finished_at"}
            if not required.issubset(cols):
                raise sqlite3.DatabaseError("schema")
            rows = conn.execute(
                "SELECT job_id,status,started_at,finished_at FROM executions "
                "ORDER BY COALESCE(finished_at,started_at) DESC LIMIT ?",
                (CRON_EXECUTION_SCAN_LIMIT,),
            ).fetchall()
        for row in rows:
            job_key = str(row["job_id"] or "")
            execution = {
                "name": job_names.get(job_key, "Scheduled job"),
                "status": _state(row["status"]),
                "started_at": _timestamp(row["started_at"]),
                "finished_at": _timestamp(row["finished_at"]),
                "duration_seconds": _duration_seconds(row["started_at"], row["finished_at"]),
                "route": _ROUTES["cron"],
            }
            if len(executions) < CRON_EXECUTION_LIMIT:
                executions.append(execution)
            history_by_job.setdefault(job_key, []).append(execution)
        for job in jobs:
            opaque = str(job.pop("_opaque", ""))
            history = history_by_job.get(opaque, [])[:CRON_HISTORY_LIMIT]
            history.reverse()
            job["history"] = [item["status"] for item in history]
            success_count = sum(1 for item in history if item["status"] in {"success", "completed"})
            failure_count = sum(1 for item in history if item["status"] in {"failed", "error", "timeout"})
            finished_count = success_count + failure_count
            job["success_count"] = success_count
            job["failure_count"] = failure_count
            job["reliability_percent"] = (
                round((success_count / finished_count) * 100) if finished_count else None
            )
            if history:
                job["last_duration_seconds"] = history[-1].get("duration_seconds")
    except FileNotFoundError:
        if status_value == "ok":
            status_value = "degraded"
        for job in jobs:
            job.pop("_opaque", None)
    except Exception:
        status_value = "degraded"
        for job in jobs:
            job.pop("_opaque", None)

    overdue_count = sum(1 for job in jobs if job.get("overdue"))
    return {
        "status": status_value,
        "total": total,
        "enabled_count": enabled_count,
        "overdue_count": overdue_count,
        "jobs": jobs,
        "executions": executions,
    }


def _kanban() -> dict[str, Any]:
    try:
        profile = _profile_name()
        with _connect_ro(_kanban_path()) as conn:
            cols = _columns(conn, "tasks")
            required = {
                "id",
                "title",
                "tenant",
                "assignee",
                "status",
                "priority",
                "created_at",
                "started_at",
                "completed_at",
            }
            if not required.issubset(cols):
                raise sqlite3.DatabaseError("schema")
            total = conn.execute(
                "SELECT COUNT(*) FROM (SELECT 1 FROM tasks WHERE tenant=? LIMIT 10001)",
                (profile,),
            ).fetchone()[0]
            status_counts = {
                _state(row[0]): int(row[1])
                for row in conn.execute(
                    "SELECT status,COUNT(*) FROM "
                    "(SELECT status FROM tasks WHERE tenant=? LIMIT 10001) GROUP BY status",
                    (profile,),
                )
            }
            rows = conn.execute(
                "SELECT * FROM tasks WHERE tenant=? "
                "AND status NOT IN ('done','archived') "
                "ORDER BY priority DESC,created_at ASC LIMIT ?",
                (profile, KANBAN_SCAN_LIMIT),
            ).fetchall()
            internal_ids = [str(row["id"]) for row in rows]
            selected_ids = set(internal_ids)
            aliases = {opaque: f"K{index + 1:02d}" for index, opaque in enumerate(internal_ids)}

            parent_counts: dict[str, int] = {opaque: 0 for opaque in internal_ids}
            open_parent_counts: dict[str, int] = {opaque: 0 for opaque in internal_ids}
            child_counts: dict[str, int] = {opaque: 0 for opaque in internal_ids}
            edges: list[dict[str, str]] = []
            if internal_ids and _table_exists(conn, "task_links"):
                link_rows = conn.execute(
                    "SELECT l.parent_id,l.child_id,p.status AS parent_status "
                    "FROM task_links l "
                    "LEFT JOIN tasks p ON p.id=l.parent_id "
                    "LEFT JOIN tasks c ON c.id=l.child_id "
                    "WHERE c.tenant=? AND p.tenant=? LIMIT ?",
                    (profile, profile, 5000),
                ).fetchall()
                for link in link_rows:
                    parent = str(link["parent_id"])
                    child = str(link["child_id"])
                    if parent not in selected_ids and child not in selected_ids:
                        continue
                    if child in parent_counts:
                        parent_counts[child] += 1
                        if _state(link["parent_status"], "todo") not in {"done", "archived"}:
                            open_parent_counts[child] += 1
                    if parent in child_counts:
                        child_counts[parent] += 1
                    if parent in aliases and child in aliases and len(edges) < 24:
                        edges.append({"parent": aliases[parent], "child": aliases[child]})

            runs_by_task: dict[str, list[dict[str, Any]]] = {}
            if internal_ids and _table_exists(conn, "task_runs"):
                run_cols = _columns(conn, "task_runs")
                needed = {"task_id", "profile", "status", "started_at", "ended_at"}
                if needed.issubset(run_cols):
                    run_rows = conn.execute(
                        "SELECT * FROM task_runs WHERE profile=? ORDER BY id DESC LIMIT ?",
                        (profile, 1000),
                    ).fetchall()
                    for run in run_rows:
                        key = str(run["task_id"])
                        if key not in selected_ids:
                            continue
                        bucket = runs_by_task.setdefault(key, [])
                        if len(bucket) >= KANBAN_RUN_LIMIT:
                            continue
                        outcome = _row_value(run, "outcome")
                        heartbeat = _row_value(run, "last_heartbeat_at")
                        max_runtime = _row_value(run, "max_runtime_seconds")
                        bucket.append(
                            {
                                "status": _state(run["status"]),
                                "outcome": _state(outcome, "unknown"),
                                "started_at": _timestamp(run["started_at"]),
                                "ended_at": _timestamp(run["ended_at"]),
                                "duration_seconds": _duration_seconds(run["started_at"], run["ended_at"]),
                                "last_heartbeat_at": _timestamp(heartbeat),
                                "max_runtime_seconds": _integer(max_runtime) or None,
                            }
                        )

        items: list[dict[str, Any]] = []
        for row in rows[:KANBAN_LIMIT]:
            opaque = str(row["id"])
            task_status = _state(row["status"], "todo")
            assignee = _row_value(row, "assignee")
            consecutive_failures = _row_value(row, "consecutive_failures")
            max_retries = _row_value(row, "max_retries")
            max_runtime = _row_value(row, "max_runtime_seconds")
            last_heartbeat = _row_value(row, "last_heartbeat_at")
            block_kind = _row_value(row, "block_kind")
            heartbeat_at = last_heartbeat or row["started_at"]
            heartbeat_age = _age_seconds(heartbeat_at)
            heartbeat_state = "unknown"
            if task_status == "running" and heartbeat_age is not None:
                heartbeat_state = "stale" if heartbeat_age > 900 else "live"
            elif task_status != "running":
                heartbeat_state = "idle"
            run_history = runs_by_task.get(opaque, [])
            items.append(
                {
                    "node": aliases[opaque],
                    "title": _clean(row["title"], 120, "Kanban task"),
                    "status": task_status,
                    "priority": _integer(row["priority"]),
                    "assignment": "assigned" if assignee else "unassigned",
                    "created_at": _timestamp(row["created_at"]),
                    "started_at": _timestamp(row["started_at"]),
                    "completed_at": _timestamp(row["completed_at"]),
                    "elapsed_seconds": _duration_seconds(row["started_at"], row["completed_at"]),
                    "last_heartbeat_at": _timestamp(last_heartbeat),
                    "heartbeat_state": heartbeat_state,
                    "parent_count": parent_counts.get(opaque, 0),
                    "open_parent_count": open_parent_counts.get(opaque, 0),
                    "child_count": child_counts.get(opaque, 0),
                    "attempt_count": len(run_history),
                    "consecutive_failures": max(0, _integer(consecutive_failures)),
                    "max_retries": max(0, _integer(max_retries)) or None,
                    "max_runtime_seconds": max(0, _integer(max_runtime)) or None,
                    "block_kind": _state(block_kind, "unknown") if block_kind else None,
                    "run_history": run_history,
                    "route": _ROUTES["kanban"],
                }
            )
        return {
            "status": "ok",
            "total": int(total),
            "total_is_lower_bound": int(total) >= 10_001,
            "active_count": len(items),
            "status_counts": status_counts,
            "items": items,
            "edges": edges,
        }
    except FileNotFoundError:
        return _missing(total=0, active_count=0, status_counts={}, items=[], edges=[])
    except Exception:
        return _degraded(total=0, active_count=0, status_counts={}, items=[], edges=[])


def _journal(limit: int = JOURNAL_SNAPSHOT_LIMIT) -> dict[str, Any]:
    try:
        items = JournalStore(STORE_PATH).list_records(limit=limit)
        return {"status": "ok", "count": len(items), "items": items}
    except Exception:
        return _degraded(count=0, items=[])


def _profile_name() -> str:
    canonical_profile = ""
    try:
        if HERMES_HOME.resolve() == PROCESS_HERMES_HOME.resolve():
            from hermes_cli.profiles import (  # type: ignore[import-not-found]
                get_active_profile_name,
            )

            canonical_profile = _clean(get_active_profile_name(), 48, "default")
    except Exception:
        canonical_profile = ""
    if canonical_profile:
        return canonical_profile
    parts = HERMES_HOME.resolve().parts
    if "profiles" in parts:
        index = parts.index("profiles")
        if index + 1 < len(parts):
            return _clean(parts[index + 1], 48, "custom")
    return "default"


def _kanban_path() -> Path:
    canonical_path: Path | None = None
    try:
        if HERMES_HOME.resolve() == PROCESS_HERMES_HOME.resolve():
            from hermes_cli.kanban_db import (  # type: ignore[import-not-found]
                kanban_db_path,
            )

            canonical_path = Path(kanban_db_path())
    except Exception:
        canonical_path = None
    if canonical_path is not None:
        return canonical_path
    home = HERMES_HOME.resolve()
    root = home.parent.parent if home.parent.name == "profiles" else home
    return root / "kanban.db"


def _latest_value(component: dict[str, Any], keys: tuple[str, ...]) -> Any:
    candidates: list[Any] = []
    for key in keys:
        value = component.get(key)
        if value:
            candidates.append(value)
    for collection in ("items", "jobs", "executions", "platforms"):
        for item in component.get(collection, []) or []:
            if not isinstance(item, dict):
                continue
            for key in keys:
                if item.get(key):
                    candidates.append(item[key])
    parsed = [(value, _parse_time(value)) for value in candidates]
    parsed = [pair for pair in parsed if pair[1] is not None]
    return max(parsed, key=lambda pair: pair[1])[0] if parsed else None


def _diagnostics(components: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    latest_keys = {
        "gateway": ("updated_at",),
        "sessions": ("updated_at", "ended_at", "started_at"),
        "delegations": ("updated_at", "completed_at", "started_at"),
        "processes": ("started_at",),
        "cron": ("finished_at", "started_at", "last_run_at", "next_run_at"),
        "kanban": ("last_heartbeat_at", "started_at", "created_at"),
        "journal": ("updated_at", "created_at"),
    }
    results: list[dict[str, Any]] = []
    for source in ("gateway", "sessions", "delegations", "processes", "cron", "kanban", "journal"):
        component = components[source]
        source_status = _state(component.get("status"), "unknown")
        latest = _latest_value(component, latest_keys[source])
        age = _age_seconds(latest)
        stale_after = 300 if source == "gateway" else 86_400
        if source_status in {"missing", "degraded"}:
            freshness = "unavailable"
            detail = "Source is unavailable; other panels remain independent."
        elif latest is None:
            freshness = "unknown"
            detail = "Source is readable but has no recent timestamp."
        elif age is not None and age > stale_after:
            freshness = "stale"
            detail = "Source is readable but its newest safe timestamp is old."
        else:
            freshness = "fresh"
            detail = "Source read succeeded with a compatible bounded projection."
        results.append(
            {
                "source": source,
                "status": source_status,
                "freshness": freshness,
                "latest_at": _timestamp(latest),
                "age_seconds": age,
                "schema": "compatible" if source_status == "ok" else "unverified",
                "detail": detail,
                "route": _ROUTES.get(source, _ROUTES["diagnostics"]),
            }
        )
    return results


def _timeline(components: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def add(*, source: str, kind: str, title: Any, event_status: Any, at: Any, detail: Any = "") -> None:
        if _parse_time(at) is None:
            return
        events.append(
            {
                "source": source,
                "kind": kind,
                "title": _clean(title, 120, "Operational event"),
                "status": _state(event_status),
                "at": _timestamp(at),
                "detail": _clean(detail, 180),
                "route": _ROUTES.get(source, "/operations"),
            }
        )

    gateway = components["gateway"]
    add(
        source="gateway",
        kind="gateway",
        title="Gateway posture checked",
        event_status=gateway.get("state"),
        at=gateway.get("updated_at"),
        detail="Canonical process liveness and channel state.",
    )
    for platform in gateway.get("platforms", []):
        add(
            source="gateway",
            kind="channel",
            title=f"{_clean(platform.get('name'), 32, 'Channel').title()} channel",
            event_status=platform.get("state"),
            at=platform.get("updated_at"),
        )
    for item in components["sessions"].get("items", []):
        add(
            source="sessions",
            kind="session",
            title=item.get("title"),
            event_status=item.get("status"),
            at=item.get("updated_at"),
            detail=f"{_state(item.get('source'))} session metadata",
        )
    for item in components["delegations"].get("items", []):
        add(
            source="delegations",
            kind="delegation",
            title="Delegated agent task",
            event_status=item.get("state"),
            at=item.get("updated_at") or item.get("started_at"),
            detail="Durable asynchronous delegation.",
        )
    for item in components["processes"].get("items", []):
        add(
            source="processes",
            kind="process",
            title="Background process",
            event_status=item.get("status"),
            at=item.get("started_at"),
            detail="Bounded process metadata only.",
        )
    for item in components["cron"].get("executions", []):
        add(
            source="cron",
            kind="cron",
            title=item.get("name"),
            event_status=item.get("status"),
            at=item.get("finished_at") or item.get("started_at"),
            detail="Scheduled execution finished." if item.get("finished_at") else "Scheduled execution started.",
        )
    for item in components["kanban"].get("items", []):
        add(
            source="kanban",
            kind="kanban",
            title=item.get("title"),
            event_status=item.get("status"),
            at=item.get("last_heartbeat_at") or item.get("started_at") or item.get("created_at"),
            detail=f"{item.get('node', 'Task')} · {item.get('open_parent_count', 0)} open dependencies",
        )
    for item in components["journal"].get("items", []):
        add(
            source="journal",
            kind=_state(item.get("category"), "record"),
            title=item.get("title"),
            event_status=item.get("status"),
            at=item.get("updated_at") or item.get("created_at"),
            detail=item.get("summary"),
        )

    events.sort(key=lambda item: _parse_time(item["at"]) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return events[:TIMELINE_LIMIT]


def _attention(
    components: dict[str, dict[str, Any]], diagnostics: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(
        *,
        source: str,
        title: Any,
        item_status: Any,
        severity: str,
        why: str,
        next_step: str,
        at: Any = None,
    ) -> None:
        safe_title = _clean(title, 120, "Operational notice")
        safe_status = _state(item_status, "attention")
        key = (source, safe_title, safe_status)
        if key in seen or len(items) >= ATTENTION_LIMIT:
            return
        seen.add(key)
        items.append(
            {
                "title": safe_title,
                "status": safe_status,
                "severity": severity,
                "source": source,
                "why": _clean(why, 220),
                "next_step": _clean(next_step, 160),
                "age_seconds": _age_seconds(at),
                "route": _ROUTES.get(source, _ROUTES["diagnostics"]),
            }
        )

    for diagnostic in diagnostics:
        if diagnostic["status"] in {"missing", "degraded"}:
            source = diagnostic["source"]
            add(
                source=source,
                title=f"{source.title()} data unavailable",
                item_status=diagnostic["status"],
                severity="critical" if source == "gateway" else "warning",
                why="The source could not produce its bounded read model; other panels remain available.",
                next_step="Review source diagnostics and the native Hermes page.",
                at=diagnostic.get("latest_at"),
            )

    gateway = components["gateway"]
    if gateway.get("status") == "ok" and gateway.get("state") not in {"running", "ready"}:
        add(
            source="gateway",
            title="Gateway is not running",
            item_status=gateway.get("state", "stopped"),
            severity="critical",
            why="Canonical process verification does not report a live gateway.",
            next_step="Review the gateway service before relying on messaging or dispatch.",
            at=gateway.get("updated_at"),
        )
    for platform in gateway.get("platforms", []):
        platform_state = platform.get("state", "unknown")
        if platform_state not in {"connected", "running", "ready", "ok"}:
            add(
                source="gateway",
                title=f"{str(platform.get('name', 'Channel')).title()} channel {platform_state}",
                item_status=platform_state,
                severity="warning",
                why="The channel is not currently reporting a connected state.",
                next_step="Review platform status and gateway logs.",
                at=platform.get("updated_at"),
            )

    for item in components["kanban"].get("items", []):
        if item.get("status") == "blocked":
            add(
                source="kanban",
                title=item.get("title", "Blocked Kanban task"),
                item_status="blocked",
                severity="warning",
                why="The task is waiting for human input, recovery, or an unresolved prerequisite.",
                next_step="Open the Kanban board, review comments, then unblock or reassign it.",
                at=item.get("last_heartbeat_at") or item.get("started_at") or item.get("created_at"),
            )
        if item.get("heartbeat_state") == "stale":
            add(
                source="kanban",
                title=item.get("title", "Stalled Kanban task"),
                item_status="stale",
                severity="critical",
                why="A running task has not emitted a safe heartbeat for more than 15 minutes.",
                next_step="Review run history and reclaim or reassign the task if the worker is gone.",
                at=item.get("last_heartbeat_at") or item.get("started_at"),
            )
        if item.get("consecutive_failures", 0) > 0:
            add(
                source="kanban",
                title=item.get("title", "Retrying Kanban task"),
                item_status="retrying",
                severity="warning",
                why=f"The task has {item.get('consecutive_failures')} consecutive failed attempts.",
                next_step="Review bounded run outcomes before the retry circuit breaker trips.",
                at=item.get("last_heartbeat_at") or item.get("started_at"),
            )

    for job in components["cron"].get("jobs", []):
        if job.get("overdue"):
            add(
                source="cron",
                title=job.get("name", "Overdue cron job"),
                item_status="overdue",
                severity="warning",
                why="The next scheduled timestamp is in the past and no running state is reported.",
                next_step="Open Cron to inspect the schedule and recent execution history.",
                at=job.get("next_run_at"),
            )
        if job.get("state") in {"failed", "error", "timeout"} or job.get("failure_count", 0) > 0:
            add(
                source="cron",
                title=job.get("name", "Failed cron job"),
                item_status="failed",
                severity="critical" if job.get("state") in {"failed", "error"} else "warning",
                why="At least one recent bounded execution ended unsuccessfully.",
                next_step="Review the native Cron execution and repair the job before retrying.",
                at=job.get("last_run_at"),
            )

    for item in components["delegations"].get("items", []):
        if (_age_seconds(item.get("updated_at")) or 0) > 1800:
            add(
                source="delegations",
                title="Delegated agent may be stalled",
                item_status="stale",
                severity="warning",
                why="The durable delegation has not updated for more than 30 minutes.",
                next_step="Review active agents and wait for or stop the parent workflow as appropriate.",
                at=item.get("updated_at"),
            )

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    items.sort(key=lambda item: (severity_order.get(item["severity"], 9), -(item.get("age_seconds") or 0)))
    return items[:ATTENTION_LIMIT]


def _build_snapshot() -> dict[str, Any]:
    gateway = _gateway()
    sessions = _sessions()
    delegations = _delegations()
    processes = _processes()
    cron = _cron()
    kanban = _kanban()
    journal = _journal()
    components = {
        "gateway": gateway,
        "sessions": sessions,
        "delegations": delegations,
        "processes": processes,
        "cron": cron,
        "kanban": kanban,
        "journal": journal,
    }
    degraded_components = [
        name for name, value in components.items() if value.get("status") in {"missing", "degraded"}
    ]
    diagnostics = _diagnostics(components)
    attention = _attention(components, diagnostics)
    timeline = _timeline(components)

    current_work: list[dict[str, Any]] = []
    current_work.extend({"_surface": "kanban", **item} for item in kanban.get("items", []))
    current_work.extend(
        {"_surface": "delegation", **item}
        for item in delegations.get("items", [])
        if item.get("state") in {"running", "finalizing"}
    )
    current_work.extend({"_surface": "process", **item} for item in processes.get("items", []))
    current_work.extend(
        {"_surface": "cron", **item}
        for item in cron.get("executions", [])
        if item.get("status") in {"running", "claimed"}
    )

    return {
        "schema_version": 2,
        "generated_at": _now_iso(),
        "profile": _profile_name(),
        "gateway": gateway,
        "sessions": sessions,
        "delegations": delegations,
        "processes": processes,
        "cron": cron,
        "kanban": kanban,
        "journal": journal,
        "current_work": {"status": "ok", "count": len(current_work), "items": current_work[:16]},
        "attention": {"status": "ok", "count": len(attention), "items": attention},
        "timeline": {"status": "ok", "count": len(timeline), "items": timeline},
        "diagnostics": {"status": "ok", "count": len(diagnostics), "items": diagnostics},
        "degraded_components": degraded_components,
    }


def _build_share_snapshot() -> dict[str, Any]:
    """Return an authenticated, content-neutral snapshot without reading live stores."""
    now = _now().replace(microsecond=0)

    def ago(minutes: int) -> str:
        return (now - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")

    routes = _ROUTES
    gateway = {
        "status": "ok",
        "state": "running",
        "active_agents": 2,
        "updated_at": ago(1),
        "profile": "sanitized",
        "platforms": [
            {"name": "channel-1", "state": "connected", "updated_at": ago(1)},
            {"name": "channel-2", "state": "connected", "updated_at": ago(1)},
            {"name": "channel-3", "state": "connected", "updated_at": ago(2)},
        ],
    }
    sessions = {
        "status": "ok",
        "total": 6,
        "items": [
            {
                "title": "Operations review",
                "source": "dashboard",
                "model": None,
                "status": "active",
                "started_at": ago(18),
                "ended_at": None,
                "updated_at": ago(2),
                "message_count": 12,
                "tool_call_count": 5,
                "route": routes["sessions"],
            },
            {
                "title": "Release verification",
                "source": "cli",
                "model": None,
                "status": "completed",
                "started_at": ago(70),
                "ended_at": ago(34),
                "updated_at": ago(34),
                "message_count": 9,
                "tool_call_count": 4,
                "route": routes["sessions"],
            },
        ],
    }
    delegations = {
        "status": "ok",
        "total": 1,
        "active_count": 1,
        "items": [
            {
                "title": "Delegated agent task",
                "state": "running",
                "delivery_state": "pending",
                "started_at": ago(7),
                "completed_at": None,
                "updated_at": ago(1),
                "elapsed_seconds": 420,
                "route": routes["delegations"],
            }
        ],
    }
    processes = {
        "status": "ok",
        "count": 1,
        "items": [
            {
                "title": "Background process",
                "status": "running",
                "started_at": ago(4),
                "elapsed_seconds": 240,
                "pid_scope": "host",
                "notify_on_complete": True,
                "route": routes["processes"],
            }
        ],
    }
    cron = {
        "status": "ok",
        "total": 4,
        "enabled_count": 4,
        "overdue_count": 0,
        "jobs": [
            {
                "name": "Nightly maintenance",
                "enabled": True,
                "state": "success",
                "schedule": "Daily schedule",
                "last_run_at": ago(44),
                "next_run_at": ago(-1_396),
                "no_agent": True,
                "overdue": False,
                "history": ["completed"] * 7,
                "success_count": 7,
                "failure_count": 0,
                "reliability_percent": 100,
                "last_duration_seconds": 84,
                "route": routes["cron"],
            },
            {
                "name": "Morning brief",
                "enabled": True,
                "state": "scheduled",
                "schedule": "Daily schedule",
                "last_run_at": ago(1_020),
                "next_run_at": ago(-420),
                "no_agent": False,
                "overdue": False,
                "history": ["completed"] * 6 + ["success"],
                "success_count": 7,
                "failure_count": 0,
                "reliability_percent": 100,
                "last_duration_seconds": 28,
                "route": routes["cron"],
            },
        ],
        "executions": [],
    }
    kanban = {
        "status": "ok",
        "total": 3,
        "active_count": 3,
        "status_counts": {"running": 1, "ready": 1, "review": 1},
        "edges": [{"parent": "K01", "child": "K03"}, {"parent": "K02", "child": "K03"}],
        "items": [
            {
                "node": "K01",
                "title": "Implement timeline",
                "status": "running",
                "priority": 2,
                "assignment": "assigned",
                "created_at": ago(70),
                "started_at": ago(18),
                "completed_at": None,
                "elapsed_seconds": 1_080,
                "last_heartbeat_at": ago(1),
                "heartbeat_state": "live",
                "parent_count": 0,
                "open_parent_count": 0,
                "child_count": 1,
                "attempt_count": 1,
                "consecutive_failures": 0,
                "max_retries": 3,
                "max_runtime_seconds": 3_600,
                "block_kind": None,
                "run_history": [{"status": "running", "outcome": "unknown"}],
                "route": routes["kanban"],
            },
            {
                "node": "K02",
                "title": "Verify privacy boundary",
                "status": "review",
                "priority": 2,
                "assignment": "assigned",
                "created_at": ago(80),
                "started_at": ago(40),
                "completed_at": None,
                "elapsed_seconds": 2_400,
                "last_heartbeat_at": ago(4),
                "heartbeat_state": "idle",
                "parent_count": 0,
                "open_parent_count": 0,
                "child_count": 1,
                "attempt_count": 1,
                "consecutive_failures": 0,
                "max_retries": 3,
                "max_runtime_seconds": 3_600,
                "block_kind": None,
                "run_history": [{"status": "completed", "outcome": "success"}],
                "route": routes["kanban"],
            },
            {
                "node": "K03",
                "title": "Publish release",
                "status": "ready",
                "priority": 1,
                "assignment": "assigned",
                "created_at": ago(55),
                "started_at": None,
                "completed_at": None,
                "elapsed_seconds": None,
                "last_heartbeat_at": None,
                "heartbeat_state": "idle",
                "parent_count": 2,
                "open_parent_count": 1,
                "child_count": 0,
                "attempt_count": 0,
                "consecutive_failures": 0,
                "max_retries": 3,
                "max_runtime_seconds": 3_600,
                "block_kind": None,
                "run_history": [],
                "route": routes["kanban"],
            },
        ],
    }
    journal = {
        "status": "ok",
        "count": 2,
        "items": [
            {
                "category": "decision",
                "title": "Keep native stores authoritative",
                "summary": "Newton observes Hermes and writes only to its bounded journal.",
                "source": "manual",
                "tags": ["architecture", "privacy"],
                "related": ["Operations dashboard"],
                "supersedes": None,
                "superseded_by": None,
                "status": "sealed",
                "created_at": ago(120),
                "updated_at": ago(90),
                "sealed_at": ago(90),
                "integrity_status": "verified",
                "event_count": 2,
            },
            {
                "category": "outcome",
                "title": "Release checks completed",
                "summary": "Quality, security, privacy, and clean-install verification passed.",
                "source": "manual",
                "tags": ["release"],
                "related": ["Release task"],
                "supersedes": None,
                "superseded_by": None,
                "status": "open",
                "created_at": ago(60),
                "updated_at": ago(60),
                "sealed_at": None,
                "integrity_status": "verified",
                "event_count": 1,
            },
        ],
    }
    timeline_items = [
        {"source": "gateway", "kind": "gateway", "title": "Gateway posture checked", "status": "running", "at": ago(1), "detail": "Canonical process liveness and channel state.", "route": routes["gateway"]},
        {"source": "kanban", "kind": "kanban", "title": "Implement timeline", "status": "running", "at": ago(2), "detail": "K01 · 0 open dependencies", "route": routes["kanban"]},
        {"source": "cron", "kind": "cron", "title": "Nightly maintenance", "status": "completed", "at": ago(44), "detail": "Scheduled execution finished.", "route": routes["cron"]},
        {"source": "journal", "kind": "outcome", "title": "Release checks completed", "status": "open", "at": ago(60), "detail": "Quality verification completed.", "route": routes["journal"]},
        {"source": "sessions", "kind": "session", "title": "Release verification", "status": "completed", "at": ago(34), "detail": "CLI session metadata", "route": routes["sessions"]},
    ]
    diagnostics = [
        {"source": source, "status": "ok", "freshness": "fresh", "latest_at": ago(index + 1), "age_seconds": (index + 1) * 60, "schema": "compatible", "detail": "Source read succeeded with a compatible bounded projection.", "route": routes.get(source, routes["diagnostics"])}
        for index, source in enumerate(("gateway", "sessions", "delegations", "processes", "cron", "kanban", "journal"))
    ]
    attention = [
        {"title": "Cron schedule review", "status": "review", "severity": "warning", "source": "cron", "why": "A demonstration schedule is ready for operator review.", "next_step": "Open Cron to inspect the schedule.", "age_seconds": 240, "route": routes["cron"]}
    ]
    return {
        "schema_version": 2,
        "share_mode": True,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "profile": "sanitized",
        "gateway": gateway,
        "sessions": sessions,
        "delegations": delegations,
        "processes": processes,
        "cron": cron,
        "kanban": kanban,
        "journal": journal,
        "current_work": {"status": "ok", "count": 3, "items": []},
        "attention": {"status": "ok", "count": len(attention), "items": attention},
        "timeline": {"status": "ok", "count": len(timeline_items), "items": timeline_items},
        "diagnostics": {"status": "ok", "count": len(diagnostics), "items": diagnostics},
        "degraded_components": [],
    }


def _markdown_export(records: list[dict[str, Any]]) -> str:
    lines = ["# Newton Operations journal", "", f"Exported: {_now_iso()}", ""]
    for record in records:
        lines.extend(
            [
                f"## {_clean(record.get('title'), 120, 'Journal record')}",
                "",
                f"- Type: {_state(record.get('category'), 'record')}",
                f"- Status: {_state(record.get('status'), 'unknown')}",
                f"- Created: {_clean(record.get('created_at'), 40, 'unknown')}",
            ]
        )
        if record.get("tags"):
            lines.append("- Tags: " + ", ".join(record["tags"]))
        if record.get("related"):
            lines.append("- Related: " + ", ".join(record["related"]))
        if record.get("integrity_status"):
            lines.append("- Integrity: " + _state(record["integrity_status"], "unverified"))
        lines.extend(["", _clean(record.get("summary"), 500), ""])
    return "\n".join(lines).rstrip() + "\n"


@router.get("/health")
def health() -> dict[str, Any]:
    gateway = _gateway()
    state = gateway.get("state", "unknown")
    overall = "healthy" if gateway.get("status") == "ok" and state in {"running", "ready"} else "degraded"
    return {
        "status": overall,
        "profile": _profile_name(),
        "generated_at": _now_iso(),
        "gateway": gateway,
    }


@router.get("/snapshot")
def snapshot(share: bool = Query(False)) -> dict[str, Any]:
    return _build_share_snapshot() if share else _build_snapshot()


@router.get("/journal")
def get_journal(
    limit: int = Query(100, ge=1, le=200),
    q: str | None = Query(default=None, max_length=80),
    category: Literal["decision", "outcome", "lifecycle"] | None = None,
    journal_status: Literal["open", "sealed"] | None = Query(default=None, alias="status"),
    tag: str | None = Query(default=None, max_length=24),
) -> dict[str, Any]:
    try:
        items = JournalStore(STORE_PATH).list_records(
            limit=limit,
            query=q,
            category=category,
            record_status=journal_status,
            tag=tag,
        )
        return {"status": "ok", "count": len(items), "items": items}
    except Exception:
        return {"status": "degraded", "count": 0, "items": []}


@router.get("/journal/integrity")
def journal_integrity() -> dict[str, Any]:
    try:
        return JournalStore(STORE_PATH).verify_integrity()
    except Exception:
        return {
            "status": "unavailable",
            "checked_records": 0,
            "checked_events": 0,
            "failure_code": "read_unavailable",
        }


@router.get("/journal/export")
def export_journal(
    format: Literal["json", "markdown"] = "json",
    limit: int = Query(200, ge=1, le=200),
) -> Response:
    try:
        records = JournalStore(STORE_PATH).list_records(limit=limit)
    except Exception:
        records = []
    if format == "markdown":
        return Response(
            content=_markdown_export(records),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="newton-operations-journal.md"'},
        )
    payload = json.dumps(
        {"schema_version": 1, "exported_at": _now_iso(), "records": records},
        indent=2,
        sort_keys=True,
    )
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="newton-operations-journal.json"'},
    )


@router.post("/journal", status_code=status.HTTP_201_CREATED)
def create_journal(body: JournalCreate) -> dict[str, Any]:
    try:
        return JournalStore(STORE_PATH).create_record(
            category=body.category,
            title=body.title,
            summary=body.summary,
            source="manual",
            tags=body.tags,
            related=body.related,
            supersedes=body.supersedes,
        )
    except InvalidJournalEntry as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/journal/{record_id}/seal")
def seal_journal(record_id: str) -> dict[str, Any]:
    try:
        return JournalStore(STORE_PATH).seal_record(record_id)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="record not found") from exc
    except InvalidJournalEntry as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
