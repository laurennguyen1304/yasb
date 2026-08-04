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
import os
import re
import time
from typing import Any

from PyQt6.QtCore import QFileSystemWatcher, QPointF, QSize, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QMovie, QPainter
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from core.utils.tooltip import set_tooltip
from core.utils.utilities import PopupWidget, refresh_widget_style
from core.validation.widgets.yasb.claude_code import ClaudeCodeConfig
from core.widgets.base import BaseWidget
from settings import SCRIPT_PATH

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


_SESSIONS_SUBDIR = "sessions.d"
_SESSION_STATE_TEXT = {"idle": "Idle", "thinking": "Thinking", "tool": "Working", "permission": "Waiting"}


def resolve_sessions_dir(state_path: str) -> str:
    """The sessions.d/ directory the hooks write per-session records into,
    always a sibling of state.json."""
    return os.path.join(os.path.dirname(state_path), _SESSIONS_SUBDIR)


def _iter_session_files(sessions_dir: str) -> list[tuple[str, dict[str, Any]]]:
    """(path, record) for every parsable session file. Anything that fails to
    parse -- a leftover empty marker from before this format existed, or a
    write caught mid-flight -- is silently skipped rather than shown broken."""
    try:
        names = os.listdir(sessions_dir)
    except OSError:
        return []
    out = []
    for name in names:
        if name.endswith(".tmp"):
            continue
        path = os.path.join(sessions_dir, name)
        record = read_state(path)
        if record and record.get("sessionId"):
            out.append((path, record))
    return out


def resolve_sessions(
    sessions_dir: str, stale_after: int, prune_after: int, now: int | None = None
) -> list[dict[str, Any]]:
    """Live, non-stale session records, oldest first. Mirrors the macOS app's
    SessionAggregator: stale_after hides a record from the UI, prune_after
    deletes its file outright (almost certainly a crashed session that never
    fired Stop/End)."""
    now = int(time.time()) if now is None else now
    live = []
    for path, record in _iter_session_files(sessions_dir):
        updated_at = _as_int(record.get("updatedAt")) or _as_int(record.get("startedAt"))
        age = now - updated_at if updated_at else 0
        if prune_after and updated_at and age > prune_after:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        if stale_after and updated_at and age > stale_after:
            continue
        live.append(record)
    live.sort(key=lambda r: _as_int(r.get("startedAt")))
    return live


def session_view(record: dict[str, Any], now: int | None = None) -> dict[str, str]:
    """Turn a raw session record into popup-row display values. Pure
    function -- no Qt, easy to unit-test -- mirroring resolve_view above."""
    now = int(time.time()) if now is None else now
    phase = _STATES.get(str(record.get("state", "")).lower(), "idle")
    label = str(record.get("label") or "").strip()
    status = label if (phase == "tool" and label) else _SESSION_STATE_TEXT.get(phase, "Idle")

    cwd = str(record.get("cwd") or "").strip()
    project = os.path.basename(cwd.rstrip("/\\")) or cwd or "session"

    anchor = _as_int(record.get("busySince")) or _as_int(record.get("startedAt"))
    elapsed = format_elapsed(now - anchor) if phase in ("thinking", "tool") and anchor > 0 else ""

    return {
        "sessionId": str(record.get("sessionId") or ""),
        "state": phase,
        "status": status,
        "project": project,
        "cwd": cwd,
        "elapsed": elapsed,
    }


_MASCOT_GIF_PATH = os.path.join(SCRIPT_PATH, "assets", "images", "claude_mascot.gif")


class ClaudeMascotIcon(QWidget):
    """The actual Claude mascot GIF (squash-and-stretch bounce, 10 frames at
    70ms each -- bundled verbatim as assets/images/claude_mascot.gif, not
    redrawn), played via QMovie while thinking or running a tool; held on its
    resting frame otherwise; dimmed with a permission dot while waiting on
    you.

    QMovie only decodes/advances frames while running() -- stopped the
    instant the phase goes idle/permission -- so it costs nothing in the
    background.
    """

    def __init__(self, size: int, dot_color: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._size = size
        self._dot_color = QColor(dot_color)
        self._phase = "idle"
        self.setFixedSize(size, size)

        self._movie = QMovie(_MASCOT_GIF_PATH)
        self._movie.setScaledSize(QSize(size, size))
        self._movie.setCacheMode(QMovie.CacheMode.CacheAll)
        self._movie.frameChanged.connect(lambda _frame: self.update())
        self._movie.jumpToFrame(0)

    def set_phase(self, phase: str) -> None:
        if phase == self._phase:
            return
        self._phase = phase
        animate = phase in ("thinking", "tool")
        running = self._movie.state() == QMovie.MovieState.Running
        if animate and not running:
            self._movie.start()
        elif not animate and running:
            self._movie.stop()
            self._movie.jumpToFrame(0)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._phase == "permission":
            painter.setOpacity(0.55)
        painter.drawPixmap(0, 0, self._movie.currentPixmap())
        painter.setOpacity(1.0)

        if self._phase == "permission":
            d = self._size * 0.34
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(self._dot_color))
            painter.drawEllipse(QPointF(self._size * 0.78, self._size * 0.22), d / 2, d / 2)

        painter.end()


class ClaudeCodeWidget(BaseWidget):
    validation_schema = ClaudeCodeConfig

    def __init__(self, config: ClaudeCodeConfig):
        super().__init__(class_name="claude-code")
        self.config = config
        self._show_alt_label = False
        self._state_path = resolve_state_path(config.state_file)
        self._data: dict[str, Any] = read_state(self._state_path)
        self._sessions_dir = resolve_sessions_dir(self._state_path)
        self._menu: PopupWidget | None = None

        self._init_container()

        # Added to the left of the bullet+text label (which is unaffected --
        # this is purely additive), so it must be inserted before build_widget_label.
        self._mascot: ClaudeMascotIcon | None = None
        if self.config.mascot.enabled:
            self._mascot = ClaudeMascotIcon(
                size=self.config.mascot.size,
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
        self.register_callback("show_sessions", self._toggle_sessions_menu)
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
        self.timer.timeout.connect(self._refresh_sessions_menu)
        self.timer.start(self.config.update_interval)

        self._render()

    def _ensure_watch(self) -> None:
        directory = os.path.dirname(self._state_path)
        watched = set(self._watcher.files()) | set(self._watcher.directories())
        paths = [directory, self._state_path]
        if self.config.sessions.enabled:
            paths.append(self._sessions_dir)
        for path in paths:
            if path and os.path.exists(path) and path not in watched:
                self._watcher.addPath(path)

    def _on_fs_change(self, _path: str) -> None:
        self._data = read_state(self._state_path)
        self._ensure_watch()  # re-arm the file watch after an atomic replace
        self._render()
        self._refresh_sessions_menu()

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

    def _on_menu_destroyed(self, *_args) -> None:
        self._menu = None

    def _toggle_sessions_menu(self) -> None:
        self._show_sessions_menu()

    def _show_sessions_menu(self) -> None:
        if not self.config.sessions.enabled:
            return
        self._menu = PopupWidget(
            self,
            self.config.sessions.menu.blur,
            self.config.sessions.menu.round_corners,
            self.config.sessions.menu.round_corners_type,
            self.config.sessions.menu.border_color,
        )
        # See ClipboardHistoryWidget for why this null-out matters: hide()
        # schedules deleteLater() and the popup can also close itself via a
        # path we don't control (click outside, Escape, re-toggling).
        self._menu.destroyed.connect(self._on_menu_destroyed)
        self._menu.setProperty("class", "claude-code-menu")

        main_layout = QVBoxLayout(self._menu)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Claude Code Sessions")
        header.setProperty("class", "header")
        main_layout.addWidget(header)

        scroll_area = QScrollArea()
        scroll_area.setProperty("class", "scroll-area")
        scroll_area.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { border: none; background: transparent; width: 4px; }
            QScrollBar::handle:vertical { background: rgba(120, 120, 120, 0.35); min-height: 20px; border-radius: 2px; }
            QScrollBar::handle:vertical:hover { background: rgba(120, 120, 120, 0.55); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(0)

        self._populate_sessions(scroll_layout)

        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)

        self._menu.adjustSize()
        self._menu.setPosition(
            alignment=self.config.sessions.menu.alignment,
            direction=self.config.sessions.menu.direction,
            offset_left=self.config.sessions.menu.offset_left,
            offset_top=self.config.sessions.menu.offset_top,
        )
        self._menu.show()

    def _populate_sessions(self, layout: QVBoxLayout) -> None:
        sessions = resolve_sessions(
            self._sessions_dir, self.config.sessions.stale_after, self.config.sessions.prune_after
        )
        if not sessions:
            empty = QLabel("No active sessions.")
            empty.setProperty("class", "empty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty)
            return
        for record in sessions:
            layout.addWidget(self._build_session_row(record))

    def _build_session_row(self, record: dict[str, Any]) -> QFrame:
        view = session_view(record)
        row = QFrame()
        row.setProperty("class", "session-row")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        icon = QLabel(getattr(self.config.icons, view["state"], "●"))
        icon.setProperty("class", f"row-icon {view['state']}")
        row_layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)

        text_container = QWidget()
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        title = QLabel(view["project"])
        title.setProperty("class", "row-title")
        set_tooltip(title, view["cwd"] or view["project"])
        text_layout.addWidget(title)

        status_text = view["status"]
        if view["elapsed"]:
            status_text += f" · {view['elapsed']}"
        status = QLabel(status_text)
        status.setProperty("class", f"row-status {view['state']}")
        text_layout.addWidget(status)

        row_layout.addWidget(text_container)
        return row

    def _refresh_sessions_menu(self) -> None:
        if not self._menu:
            return
        try:
            if not self._menu.isVisible():
                return
        except RuntimeError:
            # Underlying popup was already destroyed via a path that hasn't
            # fired the destroyed-signal cleanup yet; treat as "no popup".
            self._menu = None
            return
        scroll_areas = self._menu.findChildren(QScrollArea)
        if not scroll_areas:
            return
        scroll_widget = scroll_areas[0].widget()
        if not scroll_widget:
            return
        layout = scroll_widget.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self._populate_sessions(layout)
