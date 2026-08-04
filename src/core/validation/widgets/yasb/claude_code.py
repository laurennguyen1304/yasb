from __future__ import annotations

from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class ClaudeCodeCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_label"
    on_right: str = "show_sessions"


class ClaudeCodeIconsConfig(CustomBaseModel):
    """Glyph shown for each activity phase.

    Defaults to a plain dot (U+25CF) which renders in any font; the CSS colours
    it per state. Swap in Nerd Font glyphs to match the rest of your bar.
    """

    idle: str = "●"
    thinking: str = "●"
    tool: str = "●"
    permission: str = "●"


class ClaudeCodeMascotConfig(CustomBaseModel):
    """The Claude mascot GIF (assets/images/claude_mascot.gif -- a
    squash-and-stretch bounce, 10 frames at 70ms each) shown to the left of
    the bullet + status text (the bullet/text themselves are unaffected --
    this is an addition, not a replacement). Plays while thinking or running
    a tool; held on its resting frame otherwise; dims with a permission dot
    while waiting on you.
    """

    enabled: bool = True
    size: int = Field(default=16, ge=8, le=48)
    permission_dot_color: str = "#F2B82E"
    # Gap between the mascot and the bullet+text that follows it. The
    # container layout's own spacing is 0, so without this they touch.
    gap: int = Field(default=6, ge=0, le=32)


class ClaudeCodeSessionsMenuConfig(CustomBaseModel):
    blur: bool = True
    round_corners: bool = True
    round_corners_type: Literal["normal", "small"] = "normal"
    border_color: str = "System"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0


class ClaudeCodeSessionsConfig(CustomBaseModel):
    """Popup listing every concurrently-open Claude Code session, not just
    whichever one wrote state.json last -- read from the per-session records
    the hooks maintain under state_file's sibling sessions.d/ directory.
    Mirrors the sessions popover in the sibling macOS app
    (juzser/claude-status-bar-macos).
    """

    enabled: bool = True
    # A session untouched longer than this is hidden from the popup (almost
    # certainly a crashed process that never fired its Stop/End hook).
    stale_after: int = Field(default=900, ge=0)
    # A session untouched longer than this has its record file deleted outright.
    prune_after: int = Field(default=7 * 24 * 3600, ge=0)
    menu: ClaudeCodeSessionsMenuConfig = ClaudeCodeSessionsMenuConfig()


class ClaudeCodeConfig(CustomBaseModel):
    label: str = "<span>{icon}</span> {status}"
    label_alt: str = "<span>{icon}</span> {status} {elapsed}"
    # Path to the state file written by the Claude Code hooks. Empty = the
    # default ~/.claude/statusbar/state.json. ~ and env vars are expanded.
    state_file: str = ""
    # Timer tick (ms) used to advance the live elapsed timer. File changes are
    # picked up instantly via a filesystem watcher regardless of this value.
    update_interval: int = Field(default=1000, ge=200, le=60000)
    show_elapsed: bool = True
    hide_when_idle: bool = False
    idle_text: str = "idle"
    thinking_text: str = "thinking"
    permission_text: str = "waiting"
    # If > 0, a state older than this many seconds is treated as idle (guards
    # against a crashed session leaving a stale "working" state on the bar).
    stale_after: int = Field(default=0, ge=0)
    tooltip: bool = True
    icons: ClaudeCodeIconsConfig = ClaudeCodeIconsConfig()
    mascot: ClaudeCodeMascotConfig = ClaudeCodeMascotConfig()
    sessions: ClaudeCodeSessionsConfig = ClaudeCodeSessionsConfig()
    callbacks: ClaudeCodeCallbacksConfig = ClaudeCodeCallbacksConfig()
    keybindings: list[KeybindingConfig] = []
