"""Authenticated backend routes for the Newton Operations dashboard plugin."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from newton_ops_store import InvalidJournalEntry, JournalStore, RecordNotFound  # noqa: E402

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
STORE_PATH = PLUGIN_ROOT / "data" / "operations.db"

SESSION_LIMIT = 8
DELEGATION_LIMIT = 8
PROCESS_LIMIT = 12
CRON_JOB_LIMIT = 12
CRON_EXECUTION_LIMIT = 8
KANBAN_LIMIT = 12
JOURNAL_SNAPSHOT_LIMIT = 8
MAX_JSON_BYTES = 5 * 1024 * 1024

router = APIRouter()
_SAFE_STATE_RE = re.compile(r"^[a-zA-Z0-9 _.-]{1,48}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class JournalCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    category: Literal["decision", "outcome"] = Field(
        validation_alias=AliasChoices("category", "kind")
    )
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)

    @field_validator("title", "summary")
    @classmethod
    def safe_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or _CONTROL_RE.search(cleaned):
            raise ValueError("text contains unsupported control characters")
        return cleaned


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean(value: Any, maximum: int = 160, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = _CONTROL_RE.sub(" ", str(value)).strip()
    return text[:maximum] if text else fallback


def _state(value: Any, fallback: str = "unknown") -> str:
    text = _clean(value, 48, fallback).lower()
    return text if _SAFE_STATE_RE.fullmatch(text) else fallback


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


def _missing(**values: Any) -> dict[str, Any]:
    return {"status": "missing", **values}


def _degraded(**values: Any) -> dict[str, Any]:
    return {"status": "degraded", **values}


def _gateway_liveness() -> bool | None:
    """Return canonical gateway liveness without mutating stale PID state.

    ``gateway_state.json`` is telemetry, not a process-liveness guarantee. The
    host helper verifies the runtime lock, PID record, process identity, and
    kernel start time. ``None`` means that check was unavailable, so callers
    must fail closed rather than trust persisted state.
    """
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
                        "updated_at": _clean(value.get("updated_at"), 40) or None,
                    }
                )
        live = _gateway_liveness()
        if live is None:
            return _degraded(
                state="unknown",
                active_agents=0,
                updated_at=_clean(data.get("updated_at"), 40) or None,
                profile=_profile_name(),
                platforms=platforms[:16],
            )
        return {
            "status": "ok",
            "state": "running" if live else "stopped",
            "active_agents": max(0, int(data.get("active_agents") or 0)),
            "updated_at": _clean(data.get("updated_at"), 40) or None,
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
            if archived:
                total = conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE COALESCE(archived,0)=0"
                ).fetchone()[0]
            else:
                total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            if archived and has_model:
                query = (
                    "SELECT title,source,model,started_at,ended_at,message_count,tool_call_count "
                    "FROM sessions WHERE COALESCE(archived,0)=0 "
                    "ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?"
                )
            elif archived:
                query = (
                    "SELECT title,source,NULL AS model,started_at,ended_at,message_count,tool_call_count "
                    "FROM sessions WHERE COALESCE(archived,0)=0 "
                    "ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?"
                )
            elif has_model:
                query = (
                    "SELECT title,source,model,started_at,ended_at,message_count,tool_call_count "
                    "FROM sessions ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?"
                )
            else:
                query = (
                    "SELECT title,source,NULL AS model,started_at,ended_at,message_count,tool_call_count "
                    "FROM sessions ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?"
                )
            rows = conn.execute(query, (SESSION_LIMIT,)).fetchall()
        items = []
        for row in rows:
            items.append(
                {
                    "title": _clean(row["title"], 120, "Untitled session"),
                    "source": _state(row["source"], "unknown"),
                    "model": _clean(row["model"], 80) or None,
                    "status": "active" if row["ended_at"] is None else "completed",
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "updated_at": row["ended_at"] or row["started_at"],
                    "message_count": max(0, int(row["message_count"] or 0)),
                    "tool_call_count": max(0, int(row["tool_call_count"] or 0)),
                }
            )
        return {"status": "ok", "total": int(total), "items": items}
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
            total = conn.execute("SELECT COUNT(*) FROM async_delegations").fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM async_delegations WHERE state IN ('running','finalizing')"
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
                "started_at": row["dispatched_at"],
                "completed_at": row["completed_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
        return {"status": "ok", "total": int(total), "active_count": int(active), "items": items}
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
                    "started_at": value.get("started_at"),
                    "pid_scope": _state(value.get("pid_scope"), "unknown"),
                    "notify_on_complete": bool(value.get("notify_on_complete")),
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
        return _missing(total=0, enabled_count=0, jobs=[], executions=[])
    jobs: list[dict[str, Any]] = []
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
            if len(jobs) < CRON_JOB_LIMIT:
                enabled = bool(value.get("enabled", value.get("state") != "paused"))
                job_state = "paused" if not enabled else _state(
                    value.get("last_status") or value.get("state"), "scheduled"
                )
                jobs.append(
                    {
                        "name": name,
                        "enabled": enabled,
                        "state": job_state,
                        "schedule": _clean(value.get("schedule_display") or value.get("schedule"), 80),
                        "last_run_at": value.get("last_run_at"),
                        "next_run_at": value.get("next_run_at"),
                        "no_agent": bool(value.get("no_agent")),
                    }
                )
        total = len(raw_jobs)
        enabled_count = sum(
            1 for value in raw_jobs if isinstance(value, dict) and bool(value.get("enabled", True))
        )
    except FileNotFoundError:
        total = enabled_count = 0
        status_value = "degraded"
    except Exception:
        total = enabled_count = 0
        status_value = "degraded"

    executions: list[dict[str, Any]] = []
    try:
        with _connect_ro(db_path) as conn:
            rows = conn.execute(
                "SELECT job_id,status,started_at,finished_at FROM executions "
                "ORDER BY COALESCE(finished_at,started_at) DESC LIMIT ?",
                (CRON_EXECUTION_LIMIT,),
            ).fetchall()
        executions = [
            {
                "name": job_names.get(str(row["job_id"]), "Scheduled job"),
                "status": _state(row["status"]),
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            }
            for row in rows
        ]
    except FileNotFoundError:
        if status_value == "ok":
            status_value = "degraded"
    except Exception:
        status_value = "degraded"
    return {
        "status": status_value,
        "total": total,
        "enabled_count": enabled_count,
        "jobs": jobs,
        "executions": executions,
    }


def _kanban() -> dict[str, Any]:
    try:
        with _connect_ro(HERMES_HOME / "kanban.db") as conn:
            cols = _columns(conn, "tasks")
            required = {"title", "status", "priority", "created_at", "started_at", "completed_at"}
            if not required.issubset(cols):
                raise sqlite3.DatabaseError("schema")
            total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            rows = conn.execute(
                "SELECT title,status,priority,created_at,started_at,completed_at FROM tasks "
                "WHERE status NOT IN ('done','archived') "
                "ORDER BY priority DESC,created_at ASC LIMIT ?",
                (KANBAN_LIMIT,),
            ).fetchall()
        items = [
            {
                "title": _clean(row["title"], 120, "Kanban task"),
                "status": _state(row["status"], "todo"),
                "priority": int(row["priority"] or 0),
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
            }
            for row in rows
        ]
        return {"status": "ok", "total": int(total), "active_count": len(items), "items": items}
    except FileNotFoundError:
        return _missing(total=0, active_count=0, items=[])
    except Exception:
        return _degraded(total=0, active_count=0, items=[])


def _journal(limit: int = JOURNAL_SNAPSHOT_LIMIT) -> dict[str, Any]:
    try:
        items = JournalStore(STORE_PATH).list_records(limit=limit)
        return {"status": "ok", "count": len(items), "items": items}
    except Exception:
        return _degraded(count=0, items=[])


def _profile_name() -> str:
    parts = HERMES_HOME.resolve().parts
    if "profiles" in parts:
        index = parts.index("profiles")
        if index + 1 < len(parts):
            return _clean(parts[index + 1], 48, "custom")
    return "default"


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
    attention: list[dict[str, Any]] = []
    for name in degraded_components:
        attention.append(
            {
                "title": f"{name.title()} data unavailable",
                "status": components[name]["status"],
                "source": name,
                "detail": "The rest of the operations snapshot remains available.",
            }
        )
    if gateway.get("status") == "ok" and gateway.get("state") not in {"running", "ready"}:
        attention.append(
            {
                "title": "Gateway is not running",
                "status": gateway.get("state", "stopped"),
                "source": "gateway",
            }
        )
    for platform in gateway.get("platforms", []):
        platform_state = platform.get("state", "unknown")
        if platform_state not in {"connected", "running", "ready", "ok"}:
            attention.append(
                {
                    "title": f"{str(platform.get('name', 'Channel')).title()} channel {platform_state}",
                    "status": platform_state,
                    "source": "gateway",
                }
            )
    for item in kanban.get("items", []):
        if item.get("status") == "blocked":
            attention.append(
                {
                    "title": item.get("title", "Blocked Kanban task"),
                    "status": "blocked",
                    "source": "kanban",
                }
            )
    for item in cron.get("jobs", []):
        if item.get("state") in {"failed", "error"}:
            attention.append(
                {"title": item.get("name", "Failed cron job"), "status": "failed", "source": "cron"}
            )

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
        "schema_version": 1,
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
        "attention": {"status": "ok", "count": len(attention), "items": attention[:16]},
        "degraded_components": degraded_components,
    }


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
def snapshot() -> dict[str, Any]:
    return _build_snapshot()


@router.get("/journal")
def get_journal(limit: int = Query(100, ge=1, le=200)) -> dict[str, Any]:
    try:
        items = JournalStore(STORE_PATH).list_records(limit=limit)
        return {"status": "ok", "count": len(items), "items": items}
    except Exception:
        return {"status": "degraded", "count": 0, "items": []}


@router.post("/journal", status_code=status.HTTP_201_CREATED)
def create_journal(body: JournalCreate) -> dict[str, Any]:
    try:
        return JournalStore(STORE_PATH).create_record(
            category=body.category,
            title=body.title,
            summary=body.summary,
            source="manual",
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
