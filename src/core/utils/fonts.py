from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtGui import QFontDatabase

_FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "fonts"

# Bundled directly in the repo (see assets/fonts/NOTICE.md for license) so bar
# icon glyphs render on a fresh install without any network download.
_BUNDLED_FONT_FILES = [
    "JetBrainsMonoNerdFontPropo-Regular.ttf",
    "JetBrainsMonoNerdFontPropo-Bold.ttf",
]


def load_bundled_fonts() -> None:
    """Register the fonts shipped in assets/fonts with the app.

    Must run after the QApplication instance is created (QFontDatabase
    needs it) and before anything checks font availability, such as the
    first-run setup wizard.
    """
    for filename in _BUNDLED_FONT_FILES:
        font_path = _FONTS_DIR / filename
        if not font_path.is_file():
            logging.warning("Bundled font missing: %s", font_path)
            continue
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id == -1:
            logging.warning("Failed to load bundled font: %s", font_path)
