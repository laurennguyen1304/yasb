from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, ClassVar

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from core.utils.system import app_data_path

logger = logging.getLogger("claude_usage")

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
# Beta header the Claude Code CLI sends for the OAuth usage endpoint.
OAUTH_BETA = "oauth-2025-04-20"

EMPTY_RECORD: dict[str, Any] = {
    "five": None,
    "five_raw": None,
    "five_reset_iso": None,
    "seven": None,
    "seven_raw": None,
    "seven_reset_iso": None,
    "fetched_at": 0,
    "error": None,
}


def _claude_config_dir(override: str = "") -> str:
    """Directory holding .credentials.json for one Claude Code login.

    `override` (from the widget's `claude_config_dir` option) lets a second
    widget instance point at a different profile -- e.g. a company account
    logged in via `CLAUDE_CONFIG_DIR=... claude` -- without touching the
    CLAUDE_CONFIG_DIR env var Claude Code itself uses. Falls back to that env
    var, then the default ~/.claude, exactly like the CLI does.
    """
    if override:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(override)))
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def _cache_path(config_dir: str = "") -> str:
    """Per-profile cache file, so two accounts never clobber each other's cache."""
    if not config_dir:
        return str(app_data_path("claude_usage_cache.json"))
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", config_dir.strip("\\/"))[-64:]
    return str(app_data_path(f"claude_usage_cache_{slug}.json"))


def _read_cache(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(path: str, data: dict[str, Any]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        logger.debug("failed to write cache: %s", e)


def _pick_limit(limits: Any, groups: set[str]) -> dict[str, Any] | None:
    """Return the highest-utilization entry in ``limits`` matching any of ``groups``
    (matched against the ``group`` or ``kind`` field). None if there's no match."""
    if not isinstance(limits, list):
        return None
    matches = [
        item
        for item in limits
        if isinstance(item, dict)
        and (item.get("group") in groups or item.get("kind") in groups)
        and item.get("percent") is not None
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: item.get("percent", 0))


def _window(payload: dict[str, Any], top_key: str, limit_groups: set[str]) -> tuple[float | None, str | None]:
    """Resolve a usage window (utilization %, reset ISO) from the payload.

    Prefers the legacy top-level object (``five_hour`` / ``seven_day``) when it
    still carries a utilization, and otherwise falls back to the newer ``limits``
    array. Either can be missing/null on a given account -- or present but empty,
    e.g. a top-level object with utilization 0 and no resets_at while the real
    number lives in ``limits`` -- so both are checked and neither sinks the fetch.
    """
    obj = payload.get(top_key)
    if isinstance(obj, dict) and obj.get("utilization") is not None and obj.get("resets_at"):
        return float(obj["utilization"]), obj.get("resets_at")
    limit = _pick_limit(payload.get("limits"), limit_groups)
    if limit is not None:
        return float(limit["percent"]), limit.get("resets_at")
    if isinstance(obj, dict) and obj.get("utilization") is not None:
        return float(obj["utilization"]), obj.get("resets_at")
    return None, None


def _error_record(cache: dict[str, Any] | None, kind: str, now: int) -> dict[str, Any]:
    """Last-known-good values (if any) tagged with why the latest fetch failed.

    Deliberately not persisted to disk: a transient failure shouldn't overwrite
    the on-disk "last successful fetch" with an error state that would then
    survive a restart.
    """
    record = dict(cache) if cache else dict(EMPTY_RECORD)
    record["error"] = kind
    record["checked_at"] = now
    return record


def fetch_usage(cache_path: str, cache_ttl: int, force: bool = False, config_dir: str = "") -> dict[str, Any]:
    """Return a usage record, hitting the network only when the cache is stale.

    On error, the last cached record is returned (so the widget keeps showing
    the most recent known values) tagged with an `error` ("auth" for an
    expired/invalid OAuth token, "network" otherwise) so callers can tell a
    live number from a stale one instead of silently trusting a wrong value
    forever. `force=True` bypasses the cache_ttl check for a manual refresh.
    The OAuth token is read from Claude Code's credentials store (`config_dir`,
    or ~/.claude by default -- see `_claude_config_dir`) and is never logged.
    """
    cache = _read_cache(cache_path)
    now = int(time.time())
    if not force and cache and (now - int(cache.get("fetched_at", 0))) < cache_ttl:
        return cache

    try:
        cred_path = os.path.join(_claude_config_dir(config_dir), ".credentials.json")
        with open(cred_path, encoding="utf-8") as f:
            token = json.load(f)["claudeAiOauth"]["accessToken"]

        request = urllib.request.Request(
            USAGE_URL,
            headers={"Authorization": f"Bearer {token}", "anthropic-beta": OAUTH_BETA},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))

        five_raw, five_reset = _window(payload, "five_hour", {"session"})
        seven_raw, seven_reset = _window(payload, "seven_day", {"weekly", "weekly_scoped"})
        record = {
            "five": round(five_raw) if five_raw is not None else None,
            "five_raw": five_raw,
            "five_reset_iso": five_reset,
            "seven": round(seven_raw) if seven_raw is not None else None,
            "seven_raw": seven_raw,
            "seven_reset_iso": seven_reset,
            "fetched_at": now,
            "error": None,
        }
        _write_cache(cache_path, record)
        return record
    except urllib.error.HTTPError as e:
        kind = "auth" if e.code in (401, 403) else "network"
        logger.debug("usage fetch failed: HTTP %s", e.code)
        return _error_record(cache, kind, now)
    except Exception as e:
        logger.debug("usage fetch failed: %s", e)
        return _error_record(cache, "network", now)


class _UsageWorker(QThread):
    """Runs the (blocking) credential read + HTTP request off the UI thread."""

    data_ready = pyqtSignal(dict)

    def __init__(
        self, cache_path: str, cache_ttl: int, parent: Any = None, force: bool = False, config_dir: str = ""
    ):
        super().__init__(parent)
        self._cache_path = cache_path
        self._cache_ttl = cache_ttl
        self._force = force
        self._config_dir = config_dir

    def run(self) -> None:
        self.data_ready.emit(
            fetch_usage(self._cache_path, self._cache_ttl, force=self._force, config_dir=self._config_dir)
        )


class ClaudeUsageService(QObject):
    """Shared Claude usage poller.

    One service instance fetches the usage record on a timer and shares it with
    every widget that requests the same ``(update_interval, cache_ttl)`` pair, so
    multiple Claude widgets never duplicate the network request or the on-disk
    cache. Instances are reference-counted and released when the last widget goes
    away (mirrors the ``server_monitor`` service).
    """

    data_ready = pyqtSignal(dict)

    _instances: ClassVar[dict[tuple, ClaudeUsageService]] = {}

    @classmethod
    def get_instance(cls, update_interval_s: int, cache_ttl: int, config_dir: str = "") -> ClaudeUsageService:
        key = (int(update_interval_s), int(cache_ttl), config_dir)
        inst = cls._instances.get(key)
        if inst is None:
            inst = cls(
                update_interval_s=int(update_interval_s), cache_ttl=int(cache_ttl), _key=key, config_dir=config_dir
            )
            cls._instances[key] = inst
        inst._refcount += 1
        return inst

    def __init__(self, update_interval_s: int, cache_ttl: int, _key: tuple, config_dir: str = ""):
        super().__init__()
        self._key = _key
        self._refcount = 0
        self._config_dir = config_dir
        self._cache_path = _cache_path(config_dir)
        self._cache_ttl = cache_ttl
        self._worker: _UsageWorker | None = None
        self._data: dict[str, Any] = _read_cache(self._cache_path) or dict(EMPTY_RECORD)

        self._timer = QTimer(self)
        self._timer.setInterval(max(int(update_interval_s), 1) * 1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

    def latest(self) -> dict[str, Any]:
        """The most recent usage record (cached value, available immediately)."""
        return self._data

    def release(self) -> None:
        self._refcount -= 1
        if self._refcount > 0:
            return
        self._timer.stop()
        ClaudeUsageService._instances.pop(self._key, None)
        if self._worker is not None and self._worker.isRunning():
            # Tear down only once the in-flight fetch finishes, so we never block the
            # GUI thread (or destroy a running QThread) during a config reload.
            self._worker.finished.connect(self.deleteLater)
        else:
            self.deleteLater()

    def _tick(self) -> None:
        self._start_fetch(force=False)

    def force_refresh(self) -> None:
        """Bypass cache_ttl and re-check now (e.g. the user opened the menu)."""
        self._start_fetch(force=True)

    def _start_fetch(self, force: bool) -> None:
        if self._worker is not None:
            return  # a fetch is already in flight
        worker = _UsageWorker(self._cache_path, self._cache_ttl, self, force=force, config_dir=self._config_dir)
        worker.data_ready.connect(self._on_data)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        worker.start()

    def _on_data(self, data: dict[str, Any]) -> None:
        self._data = data
        self.data_ready.emit(data)

    def _on_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
