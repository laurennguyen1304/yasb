from __future__ import annotations

import json
import logging
import os
import time
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
}


def _claude_config_dir() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def _cache_path() -> str:
    return str(app_data_path("claude_usage_cache.json"))


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
    array. Either can be missing/null on a given account, so both are optional.
    """
    obj = payload.get(top_key)
    if isinstance(obj, dict) and obj.get("utilization") is not None:
        return float(obj["utilization"]), obj.get("resets_at")
    limit = _pick_limit(payload.get("limits"), limit_groups)
    if limit is not None:
        return float(limit["percent"]), limit.get("resets_at")
    return None, None


def fetch_usage(cache_path: str, cache_ttl: int) -> dict[str, Any]:
    """Return a usage record, hitting the network only when the cache is stale.

    On any error (including HTTP 429 rate limiting) the last cached record is
    returned so the widget keeps showing the most recent known values. The OAuth
    token is read from Claude Code's credentials store and is never logged.
    """
    cache = _read_cache(cache_path)
    now = int(time.time())
    if cache and (now - int(cache.get("fetched_at", 0))) < cache_ttl:
        return cache

    try:
        cred_path = os.path.join(_claude_config_dir(), ".credentials.json")
        with open(cred_path, encoding="utf-8") as f:
            token = json.load(f)["claudeAiOauth"]["accessToken"]

        request = urllib.request.Request(
            USAGE_URL,
            headers={"Authorization": f"Bearer {token}", "anthropic-beta": OAUTH_BETA},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))

        # The endpoint has two shapes: legacy top-level five_hour/seven_day objects,
        # and a newer `limits` array (group "session" = 5h, "weekly" = 7d). Either
        # window can be null on a given account, so resolve each independently and
        # never let one missing field sink the whole fetch.
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
        }
        _write_cache(cache_path, record)
        return record
    except Exception as e:
        logger.debug("usage fetch failed: %s", e)
        if cache:
            return cache
        return dict(EMPTY_RECORD)


class _UsageWorker(QThread):
    """Runs the (blocking) credential read + HTTP request off the UI thread."""

    data_ready = pyqtSignal(dict)

    def __init__(self, cache_path: str, cache_ttl: int, parent: Any = None):
        super().__init__(parent)
        self._cache_path = cache_path
        self._cache_ttl = cache_ttl

    def run(self) -> None:
        self.data_ready.emit(fetch_usage(self._cache_path, self._cache_ttl))


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
    def get_instance(cls, update_interval_s: int, cache_ttl: int) -> ClaudeUsageService:
        key = (int(update_interval_s), int(cache_ttl))
        inst = cls._instances.get(key)
        if inst is None:
            inst = cls(update_interval_s=int(update_interval_s), cache_ttl=int(cache_ttl), _key=key)
            cls._instances[key] = inst
        inst._refcount += 1
        return inst

    def __init__(self, update_interval_s: int, cache_ttl: int, _key: tuple):
        super().__init__()
        self._key = _key
        self._refcount = 0
        self._cache_path = _cache_path()
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
        if self._worker is not None:
            return  # a fetch is already in flight
        worker = _UsageWorker(self._cache_path, self._cache_ttl, self)
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
