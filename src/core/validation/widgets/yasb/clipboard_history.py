from __future__ import annotations

from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class ClipboardHistoryCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_menu"
    on_middle: str = "do_nothing"
    on_right: str = "toggle_label"


class ClipboardHistoryMenuConfig(CustomBaseModel):
    blur: bool = True
    round_corners: bool = True
    round_corners_type: Literal["normal", "small"] = "normal"
    border_color: str = "System"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0


class ClipboardHistoryIconsConfig(CustomBaseModel):
    """Glyphs/labels used by the widget and its popup."""

    empty: str = ""
    delete: str = "×"
    clear: str = "Clear all"


class ClipboardHistoryConfig(CustomBaseModel):
    label: str = '<span class="icon"></span> {count}'
    label_alt: str = '<span class="icon"></span> Clipboard'
    # Entries kept in memory (and on disk, if persist is enabled).
    max_items: int = Field(default=50, ge=1, le=500)
    # Entries live in memory for the session either way; persist=True additionally
    # writes them to disk so history survives a restart. Off by default because
    # clipboard content routinely includes passwords/tokens/secrets.
    persist: bool = False
    # Characters shown per entry in the popup before truncating with "...".
    max_preview_chars: int = Field(default=160, ge=20, le=2000)
    hide_empty: bool = False
    tooltip: bool = True
    icons: ClipboardHistoryIconsConfig = ClipboardHistoryIconsConfig()
    callbacks: ClipboardHistoryCallbacksConfig = ClipboardHistoryCallbacksConfig()
    menu: ClipboardHistoryMenuConfig = ClipboardHistoryMenuConfig()
    keybindings: list[KeybindingConfig] = []
