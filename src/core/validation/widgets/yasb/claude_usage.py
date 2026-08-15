from __future__ import annotations

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class ClaudeUsageCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_menu"
    on_right: str = "toggle_label"


class ClaudeUsageMenuConfig(CustomBaseModel):
    blur: bool = True
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "System"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0


class ClaudeUsageConfig(CustomBaseModel):
    label: str = "Claude {five_hour}%"
    label_alt: str = "Claude {seven_day}%"
    update_interval: int = Field(default=60, ge=30, le=3600)
    cache_ttl: int = Field(default=120, ge=0, le=3600)
    # Which Claude Code login to read. Empty = CLAUDE_CONFIG_DIR env var, or
    # ~/.claude. Point a second widget instance at a different profile
    # directory (e.g. one you logged into via `CLAUDE_CONFIG_DIR=... claude`)
    # to track a second account -- personal vs. company -- side by side.
    claude_config_dir: str = ""
    tooltip: bool = True
    # Most recently active local Claude Desktop / Cowork sessions, shown in the
    # popup menu below the 5h/7d bars. 0 hides the section.
    top_sessions_count: int = Field(default=3, ge=0, le=10)
    callbacks: ClaudeUsageCallbacksConfig = ClaudeUsageCallbacksConfig()
    menu: ClaudeUsageMenuConfig = ClaudeUsageMenuConfig()
    keybindings: list[KeybindingConfig] = []
