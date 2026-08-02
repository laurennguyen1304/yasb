from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, ClassVar

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from core.utils.system import app_data_path

logger = logging.getLogger("clipboard_history")

# Hard cap on stored text length per entry (display truncation is separate and
# configurable per-widget; this just bounds memory/disk for pathological pastes).
MAX_STORED_CHARS = 20_000

# Images are downscaled to this on the long side before being kept in memory
# (or on disk), so a full-resolution screenshot doesn't balloon 50 cached entries.
MAX_IMAGE_DIM = 800


def _cache_path() -> str:
    return str(app_data_path("clipboard_history.json"))


def _image_cache_dir() -> Path:
    d = app_data_path("clipboard_images")
    d.mkdir(parents=True, exist_ok=True)
    return d


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
        # In-memory image cache, keyed by entry id. Never put directly into
        # self._entries (which gets json.dump'd) -- entries only ever carry a
        # serializable "image_path" string when persistence is on.
        self._images: dict[str, QImage] = {}
        self._suppress_next = False

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.dataChanged.connect(self._on_clipboard_changed)

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def get_image(self, entry_id: str) -> QImage | None:
        """Return the cached image for an entry, lazily loading it from the
        on-disk cache (persist mode) if it isn't already in memory."""
        image = self._images.get(entry_id)
        if image is not None:
            return image
        entry = next((e for e in self._entries if e["id"] == entry_id), None)
        path = entry.get("image_path") if entry else None
        if not path:
            return None
        image = QImage(path)
        if image.isNull():
            return None
        self._images[entry_id] = image
        return image

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

        image: QImage | None = None
        # Check image *before* text: many real image copies (browsers,
        # screenshot tools) also carry incidental text (alt text, a filename)
        # alongside the bitmap, which would otherwise misclassify the entry.
        if mime.hasImage():
            candidate = clipboard.image()
            if candidate.isNull():
                return
            if candidate.width() > MAX_IMAGE_DIM or candidate.height() > MAX_IMAGE_DIM:
                candidate = candidate.scaled(
                    MAX_IMAGE_DIM,
                    MAX_IMAGE_DIM,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            image = candidate
            text = f"[Image {image.width()}×{image.height()}]"
            kind = "image"
        elif mime.hasText():
            text = mime.text()
            if not text.strip():
                return
            kind = "text"
        elif mime.hasUrls():
            text = "\n".join(u.toString() for u in mime.urls())
            if not text.strip():
                return
            kind = "text"
        else:
            return

        if kind == "text" and len(text) > MAX_STORED_CHARS:
            text = text[:MAX_STORED_CHARS]

        # Skip exact repeats of the most recent entry: re-copying the same
        # value, our own "copy again" action if it slipped past suppression,
        # or -- notably for images -- a single OS clipboard write that fires
        # dataChanged more than once (a real, observed Windows quirk).
        if self._entries and self._entries[0]["kind"] == kind:
            if kind == "text" and self._entries[0]["text"] == text:
                return
            if kind == "image" and image == self._images.get(self._entries[0]["id"]):
                return

        entry_id = uuid.uuid4().hex
        entry: dict[str, Any] = {"id": entry_id, "text": text, "kind": kind, "ts": time.time()}

        if image is not None:
            self._images[entry_id] = image
            if self._persist:
                path = _image_cache_dir() / f"{entry_id}.png"
                if image.save(str(path), "PNG"):
                    entry["image_path"] = str(path)

        self._entries.insert(0, entry)
        dropped = self._entries[self._max_items :]
        del self._entries[self._max_items :]
        self._forget_images(dropped)
        self._save()
        self.history_changed.emit(self.entries())

    def copy_entry(self, entry_id: str) -> None:
        """Re-copy a past entry to the clipboard without re-recording it."""
        entry = next((e for e in self._entries if e["id"] == entry_id), None)
        if entry is None:
            return
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        if entry["kind"] == "image":
            image = self.get_image(entry_id)
            if image is None:
                return
            self._suppress_next = True
            clipboard.setImage(image)
        else:
            self._suppress_next = True
            clipboard.setText(entry["text"])

    def remove_entry(self, entry_id: str) -> None:
        before = len(self._entries)
        removed = [e for e in self._entries if e["id"] == entry_id]
        self._entries = [e for e in self._entries if e["id"] != entry_id]
        if len(self._entries) != before:
            self._forget_images(removed)
            self._save()
            self.history_changed.emit(self.entries())

    def clear(self) -> None:
        if not self._entries:
            return
        removed, self._entries = self._entries, []
        self._forget_images(removed)
        self._save()
        self.history_changed.emit(self.entries())

    def _forget_images(self, removed: list[dict[str, Any]]) -> None:
        """Drop cached images and any on-disk PNGs for entries no longer kept."""
        for entry in removed:
            self._images.pop(entry["id"], None)
            path = entry.get("image_path")
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception as e:
                    logger.debug("failed to remove cached clipboard image %s: %s", path, e)

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
