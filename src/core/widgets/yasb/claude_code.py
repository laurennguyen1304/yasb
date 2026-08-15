"""Claude Code activity widget.

Shows the live status of Claude Code sessions in the bar: idle, thinking (with a
rotating "thinking word"), the friendly name of a running tool, or an "awaiting
permission" state — with an animated Claude Code spinner while working and an
optional elapsed-time counter. Clicking jumps to the session's project folder.

It is a thin reader over ~/.claude/statusbar/state.json, rewritten by Claude
Code hooks on every lifecycle event and picked up instantly via a
QFileSystemWatcher. Windows/YASB counterpart to the macOS "claude-status-bar".
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QFileSystemWatcher, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QMovie, QPainter, QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from core.utils.tooltip import set_tooltip
from core.utils.utilities import PopupWidget, refresh_widget_style
from core.validation.widgets.yasb.claude_code import ClaudeCodeConfig
from core.widgets.base import BaseWidget

_STATES = {"idle": "idle", "thinking": "thinking", "tool": "tool", "permission": "permission"}
_ACTIVE = ("thinking", "tool")

_DEFAULT_STATE_FILE = os.path.join("~", ".claude", "statusbar", "state.json")

# Claude Code spinner glyphs (matches the macOS app's "Code" style). Used for
# icon_style="spinner" — the text-glyph fallback to the real image below.
SPINNER_FRAMES = ["✻", "✽", "✶", "✳", "✢"]

# icon_style="image": the real Claude spark mark, as 60x60 alpha-mask PNGs
# (see resources/claude_code/NOTICE.md), tinted at runtime with `icon_tint`.
_ASSETS_DIR = Path(__file__).resolve().parent / "resources" / "claude_code"
_SPARK_FRAME_PATHS = sorted(_ASSETS_DIR.glob("spark_*.png"))
_LOGO_PATH = _ASSETS_DIR / "logo.png"

# icon_style="dot": while thinking/running a tool, the static dot is swapped
# for this animated GIF; idle/permission stay a plain coloured dot (`icons`).
_WORKING_GIF_PATH = _ASSETS_DIR / "working.gif"


def _tinted_pixmap(path: Path, color: QColor, size: int, dpr: float) -> QPixmap:
    """Colorize a Claude spark alpha-mask PNG with `color`, scaled to `size` px."""
    src = QImage(str(path))
    if src.isNull():
        return QPixmap()
    tinted = QImage(src.size(), QImage.Format.Format_ARGB32_Premultiplied)
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawImage(0, 0, src)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), color)
    painter.end()
    physical = max(1, round(size * dpr))
    pixmap = QPixmap.fromImage(tinted).scaled(
        physical,
        physical,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


# Playful verbs shown while thinking; one is picked per turn.
THINKING_WORDS = [
    "Thinking",
    "Cooking",
    "Manifesting",
    "Pondering",
    "Conjuring",
    "Brewing",
    "Noodling",
    "Percolating",
    "Computing",
    "Vibing",
    "Scheming",
    "Tinkering",
    "Ruminating",
    "Crunching",
    "Musing",
    "Finagling",
    "Wrangling",
    "Concocting",
    "Puzzling",
    "Marinating",
    "Spelunking",
    "Simmering",
    "Whirring",
    "Plotting",
]

# Built-in tool-name -> friendly label. Extend via the `tool_labels` option.
TOOL_LABELS = {
    "Edit": "Editing",
    "MultiEdit": "Editing",
    "Write": "Writing",
    "NotebookEdit": "Editing",
    "Read": "Reading",
    "NotebookRead": "Reading",
    "Bash": "Running command",
    "PowerShell": "Running command",
    "Grep": "Searching",
    "Glob": "Finding files",
    "WebFetch": "Fetching",
    "WebSearch": "Searching the web",
    "Task": "Delegating",
    "TodoWrite": "Planning",
    "ExitPlanMode": "Planning",
}


def resolve_state_path(configured: str) -> str:
    raw = configured.strip() if configured else _DEFAULT_STATE_FILE
    return os.path.abspath(os.path.expanduser(os.path.expandvars(raw)))


def read_state(path: str) -> dict[str, Any]:
    """Parse the state file; {} on any error so the last value keeps showing."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read().lstrip("﻿").strip()
        return json.loads(raw) if raw else {}
    except (OSError, ValueError):
        return {}


def format_elapsed(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def friendly_tool_label(tool: str, overrides: dict[str, str]) -> str:
    """Human label for a tool name ('Edit' -> 'Editing', mcp__x__y -> 'Using y')."""
    if not tool:
        return "Working"
    if tool in overrides:
        return overrides[tool]
    if tool in TOOL_LABELS:
        return TOOL_LABELS[tool]
    if tool.startswith("mcp__"):
        name = tool.split("__")[-1].replace("_", " ").strip()
        return f"Using {name}" if name else "Using a tool"
    return tool


def resolve_view(
    state: dict[str, Any], config: ClaudeCodeConfig, now: int | None = None, thinking_word: str | None = None
) -> dict[str, str]:
    """Raw state dict -> display values. Pure (no Qt), easy to unit-test."""
    now = int(time.time()) if now is None else now
    phase = _STATES.get(str(state.get("state", "")).lower(), "idle")

    ts = _as_int(state.get("ts"))
    if config.stale_after and phase != "idle" and ts and (now - ts) > config.stale_after:
        phase = "idle"

    tool = str(state.get("label") or "").strip()
    cwd = str(state.get("cwd") or "").strip()
    project = str(state.get("project") or "").strip()

    if phase == "tool":
        status = friendly_tool_label(tool, config.tool_labels)
    elif phase == "thinking":
        status = f"{thinking_word}…" if (config.thinking_words and thinking_word) else config.thinking_text
    elif phase == "permission":
        status = config.permission_text
    else:
        status = config.idle_text

    started = _as_int(state.get("startedAt"))
    elapsed = ""
    if config.show_elapsed and phase in _ACTIVE and started > 0:
        elapsed = format_elapsed(now - started)

    return {"state": phase, "status": status, "tool": tool, "elapsed": elapsed, "cwd": cwd, "project": project}


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
        self._frame = 0
        self._turn_word = random.choice(THINKING_WORDS)
        self._last_state = "idle"
        self._image_frames: list[QPixmap] = []
        self._logo_pixmap: QPixmap | None = None
        if self.config.icon_style == "image":
            self._load_image_icons()
        self._movie: QMovie | None = None
        if self.config.icon_style == "dot" and _WORKING_GIF_PATH.exists():
            self._movie = QMovie(str(_WORKING_GIF_PATH))
            self._movie.setScaledSize(QSize(self.config.icon_size, self.config.icon_size))
            self._movie.setCacheMode(QMovie.CacheMode.CacheAll)

        self._init_container()
        self.build_widget_label(self.config.label, self.config.label_alt)

        self._menu: PopupWidget | None = None

        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("open_project", self._open_project)
        self.register_callback("show_sessions", self._show_sessions)
        self.register_callback("update", self._render)

        self.callback_left = self.config.callbacks.on_left
        self.callback_middle = self.config.callbacks.on_middle
        self.callback_right = self.config.callbacks.on_right

        # Instant state updates: watch the file and its directory (atomic renames
        # can drop a file-only watch).
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_fs_change)
        self._watcher.directoryChanged.connect(self._on_fs_change)
        self._ensure_watch()

        # Frame timer runs only while working (spinner animation + elapsed tick).
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._anim_tick)

        self._render()

    def _load_image_icons(self) -> None:
        try:
            dpr = self.screen().devicePixelRatio() if self.screen() else 1.0
        except Exception:
            dpr = 1.0
        color = QColor(self.config.icon_tint)
        size = self.config.icon_size
        self._image_frames = [_tinted_pixmap(p, color, size, dpr) for p in _SPARK_FRAME_PATHS]
        self._logo_pixmap = _tinted_pixmap(_LOGO_PATH, color, size, dpr)

    def _start_movie(self) -> None:
        if self._movie is not None and self._movie.state() != QMovie.MovieState.Running:
            self._movie.start()

    def _stop_movie(self) -> None:
        if self._movie is not None and self._movie.state() == QMovie.MovieState.Running:
            self._movie.stop()

    def _ensure_watch(self) -> None:
        directory = os.path.dirname(self._state_path)
        watched = set(self._watcher.files()) | set(self._watcher.directories())
        for path in (directory, self._state_path):
            if path and os.path.exists(path) and path not in watched:
                self._watcher.addPath(path)

    def _on_fs_change(self, _path: str) -> None:
        self._data = read_state(self._state_path)
        self._ensure_watch()
        self._render()

    def _anim_tick(self) -> None:
        self._frame += 1
        self._render()

    def _toggle_label(self) -> None:
        self._show_alt_label = not self._show_alt_label
        for widget in self._widgets:
            widget.setVisible(not self._show_alt_label)
        for widget in self._widgets_alt:
            widget.setVisible(self._show_alt_label)
        self._render()

    def _open_project(self) -> None:
        cwd = str(self._data.get("cwd") or "").strip()
        action = self.config.click_action
        if not cwd or action == "none":
            return
        cwd = os.path.expanduser(os.path.expandvars(cwd))
        if not os.path.isdir(cwd):
            return
        try:
            if action == "explorer":
                os.startfile(cwd)  # noqa: S606 - opening a folder the user owns
            elif action == "vscode":
                subprocess.Popen(["code", cwd], shell=True)
            elif action == "terminal":
                subprocess.Popen(["wt.exe", "-d", cwd], shell=True)
        except Exception:
            logging.exception("claude_code: failed to open project %r", cwd)

    def _sessions_dir(self) -> str:
        return os.path.join(os.path.dirname(self._state_path), "state.d")

    def _read_sessions(self) -> list[dict[str, Any]]:
        """Every live session's raw state, one file per session (see claude-hooks)."""
        directory = self._sessions_dir()
        try:
            names = os.listdir(directory)
        except OSError:
            return []
        sessions = []
        for name in names:
            if not name.endswith(".json"):
                continue
            data = read_state(os.path.join(directory, name))
            if data:
                sessions.append(data)
        return sessions

    def _session_icon(self, phase: str) -> tuple[str, QPixmap | None]:
        """(glyph, pixmap) for a session row, matching the main icon's current style/frame."""
        active = phase in _ACTIVE
        if self.config.icon_style == "image" and self._logo_pixmap is not None:
            pixmap = (
                self._image_frames[self._frame % len(self._image_frames)]
                if (active and self._image_frames)
                else self._logo_pixmap
            )
            return "", pixmap
        if active and self.config.icon_style == "spinner":
            return SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)], None
        return getattr(self.config.icons, phase), None

    def _build_session_row(self, data: dict[str, Any]) -> QFrame:
        view = resolve_view(data, self.config, thinking_word=None)
        phase = view["state"]
        glyph, pixmap = self._session_icon(phase)

        row = QFrame()
        row.setProperty("class", f"session-row {phase}")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        icon_label = QLabel()
        icon_label.setProperty("class", f"row-icon {phase}")
        if pixmap is not None:
            icon_label.setPixmap(pixmap)
        else:
            icon_label.setText(glyph)
        row_layout.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        project = view["project"] or "(unknown project)"
        entrypoint = str(data.get("entrypoint") or "").strip()
        title_label = QLabel(f"{project}  ·  {entrypoint}" if entrypoint else project)
        title_label.setProperty("class", "row-title")
        text_col.addWidget(title_label)

        status_text = view["status"]
        if view["elapsed"]:
            status_text += f"  ·  {view['elapsed']}"
        status_label = QLabel(status_text)
        status_label.setProperty("class", f"row-status {phase}")
        text_col.addWidget(status_label)

        row_layout.addLayout(text_col)
        row_layout.addStretch()
        return row

    def _show_sessions(self) -> None:
        sessions = self._read_sessions()
        sessions.sort(key=self._session_sort_key)

        self._menu = PopupWidget(
            self,
            self.config.menu.blur,
            self.config.menu.round_corners,
            self.config.menu.round_corners_type,
            self.config.menu.border_color,
        )
        self._menu.setProperty("class", "claude-code-menu")

        layout = QVBoxLayout(self._menu)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        count = len(sessions)
        header = QLabel(f"Claude Code — {count} session{'' if count == 1 else 's'}")
        header.setProperty("class", "header")
        layout.addWidget(header)

        if not sessions:
            empty = QLabel("No active sessions")
            empty.setProperty("class", "empty")
            layout.addWidget(empty)
        else:
            for data in sessions:
                layout.addWidget(self._build_session_row(data))

        self._menu.adjustSize()
        self._menu.setPosition(
            alignment=self.config.menu.alignment,
            direction=self.config.menu.direction,
            offset_left=self.config.menu.offset_left,
            offset_top=self.config.menu.offset_top,
        )
        self._menu.show()

    def _session_sort_key(self, data: dict[str, Any]) -> tuple[int, int]:
        phase = _STATES.get(str(data.get("state", "")).lower(), "idle")
        priority = {"permission": 0, "tool": 1, "thinking": 1}.get(phase, 2)
        return (priority, -_as_int(data.get("ts")))

    def _tooltip_text(self, view: dict[str, str]) -> str:
        head = f"Claude Code — {view['project']}" if view["project"] else "Claude Code"
        tip = f"{head}: {view['status']}"
        if view["elapsed"]:
            tip += f" · {view['elapsed']}"
        if view["cwd"] and self.config.click_action != "none":
            tip += f"\nClick to open {view['cwd']}"
        return tip

    def _render(self) -> None:
        view = resolve_view(self._data, self.config, thinking_word=self._turn_word)
        phase = view["state"]
        active = phase in _ACTIVE

        # Pick a fresh thinking word (and reset the spinner) when a new turn starts.
        if active and self._last_state not in _ACTIVE:
            self._turn_word = random.choice(THINKING_WORDS)
            self._frame = 0
            if phase == "thinking" and self.config.thinking_words:
                view["status"] = f"{self._turn_word}…"
        self._last_state = phase

        if self.config.hide_when_idle and phase == "idle":
            self._widget_frame.setVisible(False)
            self._anim.stop()
            return
        self._widget_frame.setVisible(True)

        # Animate while working; static icon otherwise. "image" renders the real
        # tinted Claude spark as a pixmap; "dot" swaps the static dot for the
        # working.gif while active; "spinner" renders an animated text glyph.
        icon_mode = "text"
        glyph = ""
        pixmap = None
        if self.config.icon_style == "image" and self._logo_pixmap is not None:
            icon_mode = "pixmap"
            if active and self._image_frames:
                pixmap = self._image_frames[self._frame % len(self._image_frames)]
                if not self._anim.isActive():
                    self._anim.start(self.config.frame_interval)
            else:
                pixmap = self._logo_pixmap
                self._anim.stop()
        elif self.config.icon_style == "dot" and active and self._movie is not None:
            icon_mode = "movie"
            self._start_movie()
            if self.config.show_elapsed:
                if not self._anim.isActive():
                    self._anim.start(max(500, self.config.frame_interval))
            else:
                self._anim.stop()
        elif active and self.config.icon_style == "spinner":
            glyph = SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]
            if not self._anim.isActive():
                self._anim.start(self.config.frame_interval)
        else:
            self._stop_movie()
            glyph = getattr(self.config.icons, phase)
            # Keep ticking (for the elapsed counter) if working in dot mode.
            if active and self.config.show_elapsed:
                if not self._anim.isActive():
                    self._anim.start(max(500, self.config.frame_interval))
            else:
                self._anim.stop()

        self._paint(view, glyph, pixmap, icon_mode)

    def _paint(self, view: dict[str, str], glyph: str, pixmap: QPixmap | None = None, icon_mode: str = "text") -> None:
        active_widgets = self._widgets_alt if self._show_alt_label else self._widgets
        template = self.config.label_alt if self._show_alt_label else self.config.label
        parts = [part for part in re.split(r"(<span.*?>.*?</span>)", template) if part.strip()]
        values = dict(view)
        values["icon"] = glyph

        for index, part in enumerate(parts):
            if index >= len(active_widgets):
                continue
            widget = active_widgets[index]
            is_icon = "<span" in part and "</span>" in part
            if is_icon:
                match = re.search(r'class=(["\'])([^"\']+?)\1', part)
                base = match.group(2) if match else "icon"
                if icon_mode == "movie":
                    if widget.movie() is not self._movie:
                        widget.setMovie(self._movie)
                    # The label's sizeHint was first established from the
                    # template's literal "{icon}" placeholder text; without an
                    # explicit minimum it can end up narrower than the GIF's
                    # frame, clipping its left/right edges.
                    widget.setMinimumSize(self.config.icon_size, self.config.icon_size)
                elif icon_mode == "pixmap":
                    if widget.movie() is not None:
                        widget.setMovie(None)
                    widget.setPixmap(pixmap)
                    widget.setMinimumSize(self.config.icon_size, self.config.icon_size)
                else:
                    if widget.movie() is not None:
                        widget.setMovie(None)
                    widget.setText(glyph)
                widget.setProperty("class", f"{base} {view['state']}")
            else:
                try:
                    widget.setText(part.strip().format(**values))
                except Exception:
                    widget.setText(part.strip())
                widget.setProperty("class", f"label {view['state']}")
            if self.config.tooltip:
                set_tooltip(widget, self._tooltip_text(view))

        refresh_widget_style(*active_widgets)
