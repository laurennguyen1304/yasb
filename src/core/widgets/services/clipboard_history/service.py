from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, ClassVar

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.utils.system import app_data_path

logger = logging.getLogger("clipboard_history")

# Hard cap on stored text length per entry (display truncation is separate and
# configurable per-widget; this just bounds memory/disk for pathological pastes).
MAX_STORED_CHARS = 20_000


def _cache_path() -> str:
    return str(app_data_path("clipboard_history.json"))


class ClipboardHistoryService(QObject):
    """Shared, app-wide clipboard history.

    One instance watches ``QClipboard.dataChanged`` (fired for *any* copy on the
    system, not just inside YASB) and keeps a capped, newest-first list of
    entries. Every ``clipboard_history`` widget instance (e.g. one per monitor)
    shares this single history instead of each keeping its own.
    """

    history_changed = pyqtSignal(list)

    _instance: ClassVar[ClipboardHistoryService | None] = None

    @classmethod
    def get_instance(cls, max_items: int, persist: bool) -> ClipboardHistoryService:
        if cls._instance is None:
            cls._instance = cls(max_items=max_items, persist=persist)
        else:
            # Multiple widgets (e.g. per-monitor bars) may request different
            # settings; take the most permissive of each so no widget is short-changed.
            cls._instance._max_items = max(cls._instance._max_items, max_items)
            cls._instance._persist = cls._instance._persist or persist
        return cls._instance

    def __init__(self, max_items: int, persist: bool):
        super().__init__()
        self._max_items = max_items
        self._persist = persist
        self._cache_path = _cache_path()
        self._entries: list[dict[str, Any]] = self._load() if persist else []
        self._suppress_next = False

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.dataChanged.connect(self._on_clipboard_changed)

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def _on_clipboard_changed(self) -> None:
        if self._suppress_next:
            self._suppress_next = False
            return

        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        mime = clipboard.mimeData()
        if mime is None:
            return

        if mime.hasText():
            text = mime.text()
            if not text.strip():
                return
            kind = "text"
        elif mime.hasImage():
            text = "[Image]"
            kind = "image"
        elif mime.hasUrls():
            text = "\n".join(u.toString() for u in mime.urls())
            if not text.strip():
                return
            kind = "text"
        else:
            return

        if len(text) > MAX_STORED_CHARS:
            text = text[:MAX_STORED_CHARS]

        # Skip exact repeats of the most recent entry (re-copying the same
        # value, or our own "copy again" action if it slipped past suppression).
        if self._entries and self._entries[0]["kind"] == kind and self._entries[0]["text"] == text:
            return

        entry = {"id": uuid.uuid4().hex, "text": text, "kind": kind, "ts": time.time()}
        self._entries.insert(0, entry)
        del self._entries[self._max_items :]
        self._save()
        self.history_changed.emit(self.entries())

    def copy_entry(self, entry_id: str) -> None:
        """Re-copy a past entry to the clipboard without re-recording it."""
        entry = next((e for e in self._entries if e["id"] == entry_id), None)
        if entry is None or entry["kind"] != "text":
            return
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        self._suppress_next = True
        clipboard.setText(entry["text"])

    def remove_entry(self, entry_id: str) -> None:
        before = len(self._entries)
        self._entries = [e for e in self._entries if e["id"] != entry_id]
        if len(self._entries) != before:
            self._save()
            self.history_changed.emit(self.entries())

    def clear(self) -> None:
        if not self._entries:
            return
        self._entries = []
        self._save()
        self.history_changed.emit(self.entries())

    def _load(self) -> list[dict[str, Any]]:
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(self._entries, f)
        except Exception as e:
            logger.debug("failed to write clipboard history cache: %s", e)
