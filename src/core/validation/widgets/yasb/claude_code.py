from __future__ import annotations

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class ClaudeCodeCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_label"
    on_right: str = "do_nothing"


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
    """The small pixel-art Claude mascot (rounded coral face, two block eyes,
    a row of pale "teeth" along the bottom) shown to the left of the bullet +
    status text (the bullet/text themselves are unaffected -- this is an
    addition, not a replacement). Bobs gently while thinking or running a
    tool; sits still at rest; dims with a permission dot while waiting on you.
    """

    enabled: bool = True
    size: int = Field(default=16, ge=8, le=48)
    color: str = "#E8825A"  # Claude coral
    eye_color: str = "#1E1E1E"
    mouth_color: str = "#FBEFE3"
    permission_dot_color: str = "#F2B82E"


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
    callbacks: ClaudeCodeCallbacksConfig = ClaudeCodeCallbacksConfig()
    keybindings: list[KeybindingConfig] = []
