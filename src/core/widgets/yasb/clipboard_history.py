from __future__ import annotations

import datetime
import re
import time
from typing import Any

from PyQt6.QtCore import QBuffer, QIODevice, QMimeData, Qt, QUrl
from PyQt6.QtGui import QDrag, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.utils.tooltip import set_tooltip
from core.utils.utilities import PopupWidget, refresh_widget_style
from core.validation.widgets.yasb.clipboard_history import ClipboardHistoryConfig
from core.widgets.base import BaseWidget
from core.widgets.services.clipboard_history.service import ClipboardHistoryService


# Qt's own startDragDistance() (~10px) is easy to exceed with an ordinary,
# no-drag-intended mouse click -- a bit of hand tremor between press and
# release is normal and would otherwise silently turn a click into an
# accidental (and usually invalid) drag. Require a much more deliberate
# movement before treating it as a real drag.
_DRAG_THRESHOLD = 20


def _friendly_time(ts: float) -> str:
    """Short relative time ('2 min ago') from a unix timestamp, falling back to a date."""
    delta = time.time() - ts
    if delta < 60:
        return "Just now"
    if delta < 3600:
        minutes = int(delta // 60)
        return f"{minutes} min ago"
    if delta < 86400:
        hours = int(delta // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(delta // 86400)
    if days == 1:
        return "Yesterday"
    if days < 30:
        return f"{days} days ago"
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


class ClipboardHistoryWidget(BaseWidget):
    """Bar segment showing a running count of everything copied to the clipboard
    (system-wide, not just from YASB). Click to expand a popup listing the
    history; click an entry to copy it again (or drag it out to paste directly
    into another window), or delete/clear individual items. Image entries show
    a thumbnail preview."""

    validation_schema = ClipboardHistoryConfig

    def __init__(self, config: ClipboardHistoryConfig):
        super().__init__(class_name="clipboard-history-widget")
        self.config = config
        self._show_alt_label = False
        self._menu: PopupWidget | None = None

        self._service = ClipboardHistoryService.get_instance(self.config.max_items, self.config.persist)
        self._service.history_changed.connect(self._on_history_changed)

        self._init_container()
        self.build_widget_label(self.config.label, self.config.label_alt)

        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("toggle_menu", self._toggle_menu)
        self.register_callback("clear_history", self._clear_history)

        self.callback_left = self.config.callbacks.on_left
        self.callback_middle = self.config.callbacks.on_middle
        self.callback_right = self.config.callbacks.on_right

        self._update_label()

    def _on_history_changed(self, _entries: list[dict[str, Any]]) -> None:
        self._update_label()
        self._refresh_menu_list()

    def _toggle_label(self) -> None:
        self._show_alt_label = not self._show_alt_label
        for widget in self._widgets:
            widget.setVisible(not self._show_alt_label)
        for widget in self._widgets_alt:
            widget.setVisible(self._show_alt_label)
        self._update_label()

    def _update_label(self) -> None:
        active_widgets = self._widgets_alt if self._show_alt_label else self._widgets
        active_template = self.config.label_alt if self._show_alt_label else self.config.label
        count = len(self._service.entries())

        if count == 0 and self.config.hide_empty:
            self.setVisible(False)
        else:
            self.setVisible(True)

        label_parts = [part for part in re.split(r"(<span.*?>.*?</span>)", active_template) if part.strip()]
        for index, part in enumerate(label_parts):
            if index >= len(active_widgets):
                continue
            widget = active_widgets[index]
            if "<span" in part and "</span>" in part:
                continue  # static icon glyph already set by build_widget_label
            widget.setText(part.strip().replace("{count}", str(count)))

        if self.config.tooltip:
            set_tooltip(self._widget_container, f"Clipboard history - {count} item{'s' if count != 1 else ''}")

        refresh_widget_style(*active_widgets)

    def _on_menu_destroyed(self, *_args) -> None:
        self._menu = None

    def _toggle_menu(self) -> None:
        self._show_menu()

    def _clear_history(self) -> None:
        self._service.clear()

    def _show_menu(self) -> None:
        self._menu = PopupWidget(
            self,
            self.config.menu.blur,
            self.config.menu.round_corners,
            self.config.menu.round_corners_type,
            self.config.menu.border_color,
        )
        # PopupWidget.hide()/hide_animated() schedule the underlying C++ object
        # for deletion (deleteLater()), and it can close itself through several
        # paths we don't control directly (click outside, Escape, re-toggling).
        # Null out our reference the instant it's actually destroyed so any
        # later check (e.g. a clipboard change arriving after close) sees a
        # clean None instead of crashing on a dangling wrapper.
        self._menu.destroyed.connect(self._on_menu_destroyed)
        self._menu.setProperty("class", "clipboard-history-menu")

        main_layout = QVBoxLayout(self._menu)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        header = QFrame()
        header.setProperty("class", "header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        title = QLabel("Clipboard History")
        title.setProperty("class", "title")
        header_layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignLeft)
        header_layout.addStretch()

        clear_btn = QPushButton(self.config.icons.clear)
        clear_btn.setProperty("class", "clear-button")
        clear_btn.clicked.connect(self._clear_history)
        header_layout.addWidget(clear_btn)

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
        scroll_widget.setProperty("class", "scroll-widget")
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(0)

        self._populate_entries(scroll_layout)

        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)

        self._menu.adjustSize()
        self._menu.setPosition(
            alignment=self.config.menu.alignment,
            direction=self.config.menu.direction,
            offset_left=self.config.menu.offset_left,
            offset_top=self.config.menu.offset_top,
        )
        self._menu.show()

    def _populate_entries(self, layout: QVBoxLayout) -> None:
        entries = self._service.entries()
        if not entries:
            empty_icon = QLabel(self.config.icons.empty)
            empty_icon.setProperty("class", "empty-icon")
            empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_text = QLabel("Nothing copied yet.")
            empty_text.setProperty("class", "empty-text")
            empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty_icon)
            layout.addWidget(empty_text)
            return
        for entry in entries:
            layout.addWidget(self._build_entry_row(entry))

    def _build_entry_row(self, entry: dict[str, Any]) -> QFrame:
        row = ClipboardEntryFrame(self, entry)
        row.setProperty("class", f"entry {entry['kind']}")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        if entry["kind"] == "image":
            row_layout.addWidget(self._build_thumbnail(entry), alignment=Qt.AlignmentFlag.AlignTop)

        text_container = QWidget()
        text_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        if entry["kind"] == "image":
            preview_label = QLabel(entry["text"])  # "[Image WxH]"
        else:
            preview = " ".join(entry["text"].strip().splitlines())
            max_chars = self.config.max_preview_chars
            if len(preview) > max_chars:
                preview = preview[: max_chars - 1] + "..."
            preview_label = QLabel(preview)
        preview_label.setProperty("class", "preview")
        preview_label.setWordWrap(True)
        text_layout.addWidget(preview_label)

        time_label = QLabel(_friendly_time(entry["ts"]))
        time_label.setProperty("class", "time")
        text_layout.addWidget(time_label)

        row_layout.addWidget(text_container)

        delete_btn = QPushButton(self.config.icons.delete)
        delete_btn.setProperty("class", "delete-button")
        delete_btn.clicked.connect(lambda _, entry_id=entry["id"]: self._delete_entry(entry_id))
        row_layout.addWidget(delete_btn, alignment=Qt.AlignmentFlag.AlignTop)

        return row

    def _build_thumbnail(self, entry: dict[str, Any]) -> QLabel:
        thumb = QLabel()
        thumb.setProperty("class", "thumbnail")
        thumb.setFixedSize(48, 48)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image = self._service.get_image(entry["id"])
        if image is not None:
            pixmap = QPixmap.fromImage(image).scaled(
                48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            thumb.setPixmap(pixmap)
        return thumb

    def _copy_and_close(self, entry_id: str) -> None:
        self._service.copy_entry(entry_id)
        if self._menu:
            try:
                self._menu.hide()
            except RuntimeError:
                self._menu = None  # already gone; nothing to close

    def _delete_entry(self, entry_id: str) -> None:
        self._service.remove_entry(entry_id)

    def _refresh_menu_list(self) -> None:
        if not self._menu:
            return
        try:
            if not self._menu.isVisible():
                return
        except RuntimeError:
            # Underlying popup was already destroyed (e.g. closed by a path
            # that hasn't fired the destroyed-signal cleanup yet); treat it
            # the same as "no popup" rather than crashing the whole bar.
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
        self._populate_entries(layout)


class ClipboardEntryFrame(QFrame):
    """A single clipboard-history row.

    A plain click (no movement) re-copies the entry and closes the popup,
    mirroring the native Win+V clipboard history UX. Pressing and dragging
    past the OS drag threshold instead starts a real drag-and-drop operation,
    so the entry (text or image) can be dropped straight into another window
    without going through the clipboard at all.
    """

    def __init__(self, owner: ClipboardHistoryWidget, entry: dict[str, Any]):
        super().__init__()
        self._owner = owner
        self._entry = entry
        self._drag_start_position = None
        self._dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_position = event.pos()
            self._dragging = False

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._drag_start_position is None:
            return
        moved = (event.pos() - self._drag_start_position).manhattanLength()
        if moved < _DRAG_THRESHOLD:
            return
        self._dragging = True
        self._start_drag()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._dragging:
            self._owner._copy_and_close(self._entry["id"])
        self._drag_start_position = None
        self._dragging = False

    def _start_drag(self) -> None:
        mime = QMimeData()
        if self._entry["kind"] == "image":
            image = self._owner._service.get_image(self._entry["id"])
            if image is None:
                return
            mime.setImageData(image)
            # Also attach raw PNG bytes under the standard mime type, and a
            # real file reference (most drop targets people actually use --
            # Explorer, chat/mail apps, browser upload dropzones -- only
            # accept a file, not inline image bytes or Qt's own variant).
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            mime.setData("image/png", buffer.data())
            file_path = self._owner._service.get_image_file_path(self._entry["id"])
            if file_path:
                mime.setUrls([QUrl.fromLocalFile(file_path)])
            pixmap = QPixmap.fromImage(image).scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        else:
            mime.setText(self._entry["text"])
            pixmap = None

        drag = QDrag(self)
        drag.setMimeData(mime)
        if pixmap is not None:
            drag.setPixmap(pixmap)

        # The drag's native event loop runs while this popup is still open;
        # make sure our own "click outside closes the popup" behavior doesn't
        # tear the popup (and this row) down mid-drag.
        menu = self._owner._menu
        if menu is not None:
            try:
                menu.set_auto_close_enabled(False)
            except RuntimeError:
                menu = None  # already gone; nothing to guard or re-enable later
        try:
            drag.exec(Qt.DropAction.CopyAction)
        finally:
            if menu is not None:
                try:
                    menu.set_auto_close_enabled(True)
                except RuntimeError:
                    pass  # popup was destroyed during the drag; nothing to re-enable
