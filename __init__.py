"""Newton Operations lifecycle hooks.

Hooks enqueue terse, sealed lifecycle markers only. They intentionally ignore all
raw task summaries, reasons, commands, descriptions, profile names and session
identifiers supplied by Hermes. Writes run on one bounded daemon worker so an
observability database can never hold up approvals or Kanban transitions.
"""
from __future__ import annotations

import logging
import queue
import sys
import threading
from pathlib import Path
from typing import Any

try:
    from .newton_ops_store import JournalStore
except ImportError:  # Direct-file imports used by test runners and some plugin loaders.
    root = str(Path(__file__).resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from newton_ops_store import JournalStore

log = logging.getLogger(__name__)
STORE_PATH = Path(__file__).resolve().parent / "data" / "operations.db"
_EVENT_QUEUE: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=64)
_WORKER_LOCK = threading.Lock()
_WORKER_STARTED = False


def _write_record(title: str, summary: str) -> None:
    try:
        JournalStore(STORE_PATH).create_record(
            category="lifecycle",
            title=title,
            summary=summary,
            source="hermes-hook",
            sealed=True,
        )
    except Exception as exc:  # Hooks must never affect Hermes lifecycle.
        log.debug("Newton Operations lifecycle record skipped: %s", type(exc).__name__)


def _journal_worker() -> None:
    while True:
        title, summary = _EVENT_QUEUE.get()
        try:
            _write_record(title, summary)
        finally:
            _EVENT_QUEUE.task_done()


def _ensure_worker() -> None:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        threading.Thread(
            target=_journal_worker,
            name="newton-operations-journal",
            daemon=True,
        ).start()
        _WORKER_STARTED = True


def _enqueue_record(title: str, summary: str) -> None:
    try:
        _EVENT_QUEUE.put_nowait((title, summary))
    except queue.Full:
        # Bounded best-effort observability: dropping a marker is safer than
        # delaying an approval, task transition, or process shutdown.
        log.debug("Newton Operations lifecycle queue full; marker skipped")


def _normalize_profile(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text or len(text) > 64:
        return ""
    return text if all(char.isalnum() or char in {"-", "_"} for char in text) else ""


def _runtime_profile_name(fields: dict[str, Any]) -> str:
    """Resolve the event's task-local profile, failing closed when ambiguous."""
    explicit = _normalize_profile(fields.get("profile_name"))
    if explicit:
        return explicit

    session_key = str(fields.get("session_key") or "")
    parts = session_key.split(":")
    if len(parts) >= 2 and parts[0] == "agent":
        namespace = _normalize_profile(parts[1] or "main")
        if namespace:
            return "default" if namespace == "main" else namespace

    try:
        from gateway.session_context import get_session_env, session_context_engaged

        session_profile = _normalize_profile(
            get_session_env("HERMES_SESSION_PROFILE", "")
        )
        if session_profile:
            return session_profile
        # In a multiplexed host, an engaged-but-unbound context is ambiguous.
        # Never fall back to the process profile in that case.
        if session_context_engaged():
            return ""
    except Exception:
        log.debug("Newton Operations session profile context unavailable")

    try:
        from hermes_cli.profiles import get_active_profile_name

        return _normalize_profile(get_active_profile_name())
    except Exception:
        return ""


def _profile_matches(installed_profile: str, fields: dict[str, Any]) -> bool:
    runtime_profile = _runtime_profile_name(fields)
    return bool(runtime_profile and runtime_profile == installed_profile)


def _on_kanban_completed(installed_profile: str, **fields: Any) -> None:
    if not _profile_matches(installed_profile, fields):
        return
    _enqueue_record(
        "Kanban task completed",
        "A Hermes Kanban task reached its completed state.",
    )


def _on_kanban_blocked(installed_profile: str, **fields: Any) -> None:
    if not _profile_matches(installed_profile, fields):
        return
    _enqueue_record(
        "Kanban task blocked",
        "A Hermes Kanban task entered the blocked state and needs attention.",
    )


def _on_approval_response(
    installed_profile: str,
    choice: str = "",
    **fields: Any,
) -> None:
    if not _profile_matches(installed_profile, fields):
        return
    allowed = {
        "once": "approved once",
        "session": "approved for the session",
        "always": "approved persistently",
        "deny": "denied",
        "timeout": "timed out",
        "smart_approve": "approved by smart mode",
        "smart_deny": "denied by smart mode",
    }
    decision = allowed.get(str(choice), "resolved")
    _enqueue_record(
        f"Command approval {decision}",
        f"A Hermes command approval request was {decision}.",
    )


def register(ctx) -> None:
    installed_profile = _normalize_profile(getattr(ctx, "profile_name", ""))
    if not installed_profile:
        installed_profile = _runtime_profile_name({})
    if not installed_profile:
        log.debug("Newton Operations hooks disabled: installation profile is ambiguous")
        return

    _ensure_worker()
    ctx.register_hook(
        "kanban_task_completed",
        lambda **fields: _on_kanban_completed(installed_profile, **fields),
    )
    ctx.register_hook(
        "kanban_task_blocked",
        lambda **fields: _on_kanban_blocked(installed_profile, **fields),
    )
    ctx.register_hook(
        "post_approval_response",
        lambda **fields: _on_approval_response(installed_profile, **fields),
    )
