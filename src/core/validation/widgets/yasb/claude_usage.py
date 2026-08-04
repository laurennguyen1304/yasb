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
    # Aligned with cache_ttl by default: every tick does real work instead of
    # half of them firing, checking the cache is still fresh, and no-op'ing
    # (which is what update_interval < cache_ttl causes). 5 minutes is plenty
    # fresh for a usage percentage and keeps network/timer wakeups low for
    # battery.
    update_interval: int = Field(default=300, ge=30, le=3600)
    cache_ttl: int = Field(default=300, ge=0, le=3600)
    tooltip: bool = True
    callbacks: ClaudeUsageCallbacksConfig = ClaudeUsageCallbacksConfig()
    menu: ClaudeUsageMenuConfig = ClaudeUsageMenuConfig()
    keybindings: list[KeybindingConfig] = []
