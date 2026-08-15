from __future__ import annotations

from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class ClaudeCodeCallbacksConfig(CallbacksConfig):
    on_left: str = "open_project"
    on_middle: str = "toggle_label"
    on_right: str = "show_sessions"


class ClaudeCodeIconsConfig(CustomBaseModel):
    """Static glyph per phase (used for the `dot` icon style, and for the
    idle/permission phases in `spinner` style). CSS colours it per state."""

    idle: str = "●"
    thinking: str = "●"
    tool: str = "●"
    permission: str = "●"


class ClaudeCodeMenuConfig(CustomBaseModel):
    """Popup shown by the `show_sessions` callback, listing every live session."""

    blur: bool = True
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "System"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0


class ClaudeCodeConfig(CustomBaseModel):
    label: str = "<span>{icon}</span> {status}"
    label_alt: str = "<span>{icon}</span> {status} {elapsed}"
    # Path to the state file written by the Claude Code hooks. Empty = the
    # default ~/.claude/statusbar/state.json. ~ and env vars are expanded.
    state_file: str = ""
    # Icon presentation: "dot" shows a static coloured dot per state (see
    # `icons`), swapped for the working.gif animation while thinking/running a
    # tool; "image" renders the real Claude spark mark instead (tinted,
    # animated while working); "spinner" animates text glyphs instead.
    icon_style: Literal["dot", "image", "spinner"] = "dot"
    # Tint colour applied to the "image" spark/logo (hex, e.g. "#D97756").
    icon_tint: str = "#D97756"
    # Rendered icon size in px, for icon_style="image" and the "dot" working.gif.
    icon_size: int = Field(default=16, ge=8, le=64)
    # Spinner animation speed in ms per frame.
    frame_interval: int = Field(default=150, ge=60, le=1000)
    # Rotate playful "thinking words" (Cooking…, Manifesting…) while thinking.
    thinking_words: bool = True
    show_elapsed: bool = True
    hide_when_idle: bool = False
    idle_text: str = "Idle"
    thinking_text: str = "Thinking…"
    permission_text: str = "Awaiting permission"
    # What a click does with the session's project directory (cwd).
    click_action: Literal["explorer", "vscode", "terminal", "none"] = "explorer"
    # Override or extend the built-in tool-name -> friendly-label map.
    tool_labels: dict[str, str] = {}
    # If > 0, a state older than this many seconds is treated as idle.
    stale_after: int = Field(default=0, ge=0)
    tooltip: bool = True
    icons: ClaudeCodeIconsConfig = ClaudeCodeIconsConfig()
    callbacks: ClaudeCodeCallbacksConfig = ClaudeCodeCallbacksConfig()
    menu: ClaudeCodeMenuConfig = ClaudeCodeMenuConfig()
    keybindings: list[KeybindingConfig] = []
