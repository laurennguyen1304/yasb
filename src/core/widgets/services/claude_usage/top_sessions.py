"""Most recently active local Claude Desktop / Cowork sessions.

Reads only the lightweight per-session metadata Claude Desktop writes to disk
(title, timestamps, turn count) -- never message content. These are the
Desktop app's own agent/Cowork sessions (its "claude-code-sessions" and
"local-agent-mode-sessions" stores); plain claude.ai web chat threads aren't
kept locally in this form, so they can't be included here.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger("claude_usage")


def _session_dirs() -> list[str]:
    appdata = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    base = os.path.join(appdata, "Claude")
    return [
        os.path.join(base, "claude-code-sessions"),
        os.path.join(base, "local-agent-mode-sessions"),
    ]


def _read_session(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if data.get("isArchived"):
        return None
    session_id = data.get("sessionId") or path
    return {
        "sessionId": session_id,
        "title": data.get("title") or "Untitled session",
        "lastActivityAt": data.get("lastActivityAt") or 0,
        "completedTurns": data.get("completedTurns") or 0,
        "cwd": data.get("cwd") or "",
    }


def top_active_sessions(limit: int = 3, max_age_days: int = 14) -> list[dict[str, Any]]:
    """The `limit` most recently active sessions, newest first.

    Sessions with no activity in `max_age_days` or that are archived are
    excluded. Returns [] if the Desktop app isn't installed or has no local
    session data yet.
    """
    if limit <= 0:
        return []
    cutoff_ms = (time.time() - max_age_days * 86400) * 1000
    by_id: dict[str, dict[str, Any]] = {}
    for directory in _session_dirs():
        try:
            paths = glob.glob(os.path.join(directory, "**", "local_*.json"), recursive=True)
        except Exception as e:
            logger.debug("top_sessions: scan failed for %s: %s", directory, e)
            continue
        for path in paths:
            session = _read_session(path)
            if not session or session["lastActivityAt"] < cutoff_ms:
                continue
            existing = by_id.get(session["sessionId"])
            if existing is None or session["lastActivityAt"] > existing["lastActivityAt"]:
                by_id[session["sessionId"]] = session

    sessions = sorted(by_id.values(), key=lambda s: s["lastActivityAt"], reverse=True)
    return sessions[:limit]
