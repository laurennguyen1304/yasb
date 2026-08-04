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
from __future__ import annotations

import json
import math
import os
import re
import time
from typing import Any

from PyQt6.QtCore import QFileSystemWatcher, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

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


_MASCOT_BOB_MS = 50  # smooth continuous motion, not discrete frames
_MASCOT_BOB_AMPLITUDE = 0.09  # fraction of icon size


class ClaudeMascotIcon(QWidget):
    """Small pixel-art Claude mascot (rounded coral face, two block eyes, a
    row of pale "teeth" along the bottom edge), drawn at runtime with
    QPainter -- no image assets. Bobs gently while thinking or running a
    tool; sits still at rest; dims with a permission dot while waiting on
    you.

    The bob timer only runs while actually animating -- stopped the instant
    the phase goes idle/permission -- so it costs nothing in the background.
    """

    def __init__(self, size: int, color: str, eye_color: str, mouth_color: str, dot_color: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._size = size
        self._color = QColor(color)
        self._eye_color = QColor(eye_color)
        self._mouth_color = QColor(mouth_color)
        self._dot_color = QColor(dot_color)
        self._phase = "idle"
        self._t = 0.0
        self.setFixedSize(size, size)

        self._timer = QTimer(self)
        self._timer.setInterval(_MASCOT_BOB_MS)
        self._timer.timeout.connect(self._tick)

    def set_phase(self, phase: str) -> None:
        animate = phase in ("thinking", "tool")
        if phase != self._phase:
            self._phase = phase
            if not animate:
                self._t = 0.0
        if animate and not self._timer.isActive():
            self._timer.start()
        elif not animate and self._timer.isActive():
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._t += _MASCOT_BOB_MS / 1000.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bob = 0.0
        if self._phase in ("thinking", "tool"):
            bob = math.sin(self._t * 2 * math.pi * 1.4) * (self._size * _MASCOT_BOB_AMPLITUDE)

        painter.save()
        painter.translate(0, bob)
        alpha = 140 if self._phase == "permission" else 255
        self._draw_face(painter, alpha)
        painter.restore()

        if self._phase == "permission":
            d = self._size * 0.34
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(self._dot_color))
            painter.drawEllipse(QPointF(self._size * 0.78, self._size * 0.22), d / 2, d / 2)

        painter.end()

    def _draw_face(self, painter: QPainter, alpha: int) -> None:
        size = self._size
        grid = size / 12.0

        # Rounded coral body -- rounded top corners, square bottom corners
        # (the pixel-art teeth read as sitting flush on a flat base).
        radius = size * 0.22
        path = QPainterPath()
        path.moveTo(0, size)
        path.lineTo(0, radius)
        path.arcTo(QRectF(0, 0, radius * 2, radius * 2), 180, -90)
        path.lineTo(size - radius, 0)
        path.arcTo(QRectF(size - radius * 2, 0, radius * 2, radius * 2), 90, -90)
        path.lineTo(size, size)
        path.closeSubpath()

        body_color = QColor(self._color)
        body_color.setAlpha(alpha)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(body_color))
        painter.drawPath(path)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        eye_color = QColor(self._eye_color)
        eye_color.setAlpha(alpha)
        painter.setBrush(QBrush(eye_color))
        for col in (3, 7):
            painter.drawRect(QRectF(col * grid, 4 * grid, 2 * grid, 2 * grid))

        mouth_color = QColor(self._mouth_color)
        mouth_color.setAlpha(alpha)
        painter.setBrush(QBrush(mouth_color))
        for col in (1, 4, 7, 10):
            painter.drawRect(QRectF(col * grid, 10 * grid, grid, 2 * grid))

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)


class ClaudeCodeWidget(BaseWidget):
    validation_schema = ClaudeCodeConfig

    def __init__(self, config: ClaudeCodeConfig):
        super().__init__(class_name="claude-code")
        self.config = config
        self._show_alt_label = False
        self._state_path = resolve_state_path(config.state_file)
        self._data: dict[str, Any] = read_state(self._state_path)

        self._init_container()

        # Added to the left of the bullet+text label (which is unaffected --
        # this is purely additive), so it must be inserted before build_widget_label.
        self._mascot: ClaudeMascotIcon | None = None
        if self.config.mascot.enabled:
            self._mascot = ClaudeMascotIcon(
                size=self.config.mascot.size,
                color=self.config.mascot.color,
                eye_color=self.config.mascot.eye_color,
                mouth_color=self.config.mascot.mouth_color,
                dot_color=self.config.mascot.permission_dot_color,
            )
            self._mascot.setProperty("class", "mascot")
            self._widget_container_layout.addWidget(self._mascot)
            # Container layout spacing is 0 (build_widget_label's other parts
            # rely on that), so without an explicit gap the mascot and the
            # bullet glyph render touching each other.
            self._widget_container_layout.addSpacing(self.config.mascot.gap)

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

        if self._mascot is not None:
            self._mascot.set_phase(view["state"])

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
