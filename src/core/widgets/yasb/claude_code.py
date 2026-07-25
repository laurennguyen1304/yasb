"""Claude Code activity widget.

Shows the live status of Claude Code sessions in the bar: idle, thinking, the
name of a running tool, or a "waiting" state when Claude needs permission, plus
an optional live elapsed-time counter for the current turn.

It is a thin reader over ~/.claude/statusbar/state.json, a small JSON file that
Claude Code hooks rewrite on every lifecycle event (session start, prompt, tool
start/stop, notification, stop). The file is picked up instantly through a
QFileSystemWatcher; a modest timer only advances the elapsed counter. This is
the Windows/YASB counterpart to the macOS "claude-status-bar" menu-bar app and
consumes the exact same state-file contract.
"""

import json
import os
import re
import time
from typing import Any

from PyQt6.QtCore import QFileSystemWatcher, QTimer

from core.utils.tooltip import set_tooltip
from core.utils.utilities import refresh_widget_style
from core.validation.widgets.yasb.claude_code import ClaudeCodeConfig
from core.widgets.base import BaseWidget

# state string -> css state class. Unknown/missing states fall back to idle.
_STATES = {"idle": "idle", "thinking": "thinking", "tool": "tool", "permission": "permission"}

_DEFAULT_STATE_FILE = os.path.join("~", ".claude", "statusbar", "state.json")


def resolve_state_path(configured: str) -> str:
    """Absolute path to the state file, expanding ~ and environment variables."""
    raw = configured.strip() if configured else _DEFAULT_STATE_FILE
    return os.path.abspath(os.path.expanduser(os.path.expandvars(raw)))


def read_state(path: str) -> dict[str, Any]:
    """Read and parse the state file. Returns {} on any error (missing file,
    partial write, locked file) so the caller can keep showing the last value."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read().lstrip("﻿").strip()
        return json.loads(raw) if raw else {}
    except (OSError, ValueError):
        return {}


def format_elapsed(seconds: int) -> str:
    """'12s', '1m 4s', '1h 2m' — mirrors the macOS app's compact timer."""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def resolve_view(state: dict[str, Any], config: ClaudeCodeConfig, now: int | None = None) -> dict[str, str]:
    """Turn a raw state dict into display values: css state class, icon glyph,
    status text and elapsed string. Pure function — no Qt, easy to unit-test."""
    now = int(time.time()) if now is None else now
    phase = _STATES.get(str(state.get("state", "")).lower(), "idle")

    # A stale "working" state (crashed session) collapses back to idle.
    ts = _as_int(state.get("ts"))
    if config.stale_after and phase != "idle" and ts and (now - ts) > config.stale_after:
        phase = "idle"

    icon = getattr(config.icons, phase)
    tool = str(state.get("label") or "").strip()

    if phase == "tool":
        status = tool or "tool"
    elif phase == "thinking":
        status = config.thinking_text
    elif phase == "permission":
        status = config.permission_text
    else:
        status = config.idle_text

    started_at = _as_int(state.get("startedAt"))
    elapsed = ""
    if config.show_elapsed and phase in ("thinking", "tool") and started_at > 0:
        elapsed = format_elapsed(now - started_at)

    return {"state": phase, "icon": icon, "status": status, "tool": tool, "elapsed": elapsed}


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class ClaudeCodeWidget(BaseWidget):
    validation_schema = ClaudeCodeConfig

    def __init__(self, config: ClaudeCodeConfig):
        super().__init__(class_name="claude-code")
        self.config = config
        self._show_alt_label = False
        self._state_path = resolve_state_path(config.state_file)
        self._data: dict[str, Any] = read_state(self._state_path)

        self._init_container()
        self.build_widget_label(self.config.label, self.config.label_alt)

        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("update", self._render)

        self.callback_left = self.config.callbacks.on_left
        self.callback_middle = self.config.callbacks.on_middle
        self.callback_right = self.config.callbacks.on_right

        # Instant updates: watch both the file and its directory (the hooks write
        # atomically via a temp file + rename, which can drop a file-only watch).
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_fs_change)
        self._watcher.directoryChanged.connect(self._on_fs_change)
        self._ensure_watch()

        # Timer only advances the elapsed counter; state itself arrives via watch.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._render)
        self.timer.start(self.config.update_interval)

        self._render()

    def _ensure_watch(self) -> None:
        directory = os.path.dirname(self._state_path)
        watched = set(self._watcher.files()) | set(self._watcher.directories())
        for path in (directory, self._state_path):
            if path and os.path.exists(path) and path not in watched:
                self._watcher.addPath(path)

    def _on_fs_change(self, _path: str) -> None:
        self._data = read_state(self._state_path)
        self._ensure_watch()  # re-arm the file watch after an atomic replace
        self._render()

    def _toggle_label(self) -> None:
        self._show_alt_label = not self._show_alt_label
        for widget in self._widgets:
            widget.setVisible(not self._show_alt_label)
        for widget in self._widgets_alt:
            widget.setVisible(self._show_alt_label)
        self._render()

    def _render(self) -> None:
        view = resolve_view(self._data, self.config)

        if self.config.hide_when_idle and view["state"] == "idle":
            self._widget_frame.setVisible(False)
            return
        self._widget_frame.setVisible(True)

        active_widgets = self._widgets_alt if self._show_alt_label else self._widgets
        active_template = self.config.label_alt if self._show_alt_label else self.config.label
        # Keep template parts aligned with the QLabels build_widget_label created
        # (it drops whitespace-only parts), otherwise multi-<span> labels misalign.
        label_parts = [part for part in re.split(r"(<span.*?>.*?</span>)", active_template) if part.strip()]

        for index, part in enumerate(label_parts):
            if index >= len(active_widgets):
                continue
            widget = active_widgets[index]
            is_icon = "<span" in part and "</span>" in part
            if is_icon:
                # The icon span is dynamic: show the current phase glyph, coloured
                # per state via CSS (e.g. .icon.permission { color: yellow }).
                match = re.search(r'class=(["\'])([^"\']+?)\1', part)
                base = match.group(2) if match else "icon"
                widget.setText(view["icon"])
                widget.setProperty("class", f"{base} {view['state']}")
            else:
                try:
                    widget.setText(part.strip().format(**view))
                except Exception:
                    widget.setText(part.strip())
                widget.setProperty("class", f"label {view['state']}")

            if self.config.tooltip:
                tip = f"Claude Code — {view['status']}"
                if view["elapsed"]:
                    tip += f" · {view['elapsed']}"
                set_tooltip(widget, tip)

        refresh_widget_style(*active_widgets)
