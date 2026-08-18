#!/usr/bin/env python3
"""Measure the screen card's mode row with the real platform plugin.

Run from the project root::

    python tools/measure_mode_row.py

The row carries a title, a status line, the mode control and the power button,
and the translations differ in length by a lot. Whether it fits is a question
about font metrics, and the test suite runs under ``offscreen``, where those
metrics do not match what a person sees — the same reason screenshots are taken
with the real plugin. So this measures where it counts and prints JSON, and the
test drives it in a subprocess rather than asking Qt something Qt cannot answer
in that environment.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LANGUAGES = ("en", "ru", "es", "zh")
SIZES = ((860, 420), (1000, 700))


def _isolated_data_dir() -> None:
    """Never touch the real LumaBLE data — same care as shoot_screen."""
    from app import storage

    tmp = Path(tempfile.mkdtemp(prefix="lumable-measure-"))
    storage.DATA_DIR = tmp
    storage.SETTINGS_PATH = tmp / "settings.json"
    storage.PROFILES_PATH = tmp / "profiles.json"


def _row_of(widget):
    parent = widget.parentWidget()
    while parent is not None and parent.objectName() != "settingsRow":
        parent = parent.parentWidget()
    return parent


def main() -> int:
    _isolated_data_dir()

    from PySide6.QtWidgets import QApplication

    from app.localization import localization_manager
    from app.main_layout import select_section
    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    results = []
    try:
        window.setWindowOpacity(0.0)
        window.show()
        select_section(window, "ambient")
        row = _row_of(window.fusion_mode_segment)
        for language in LANGUAGES:
            localization_manager.set_language(language)
            # Through the app's own retranslation, not just the manager: a label
            # built once keeps its text until something rewrites it, and whether
            # that happens is part of what is being measured.
            window._ui_localization.apply_texts()
            for width, height in SIZES:
                window.resize(width, height)
                for _ in range(8):
                    app.processEvents()
                card = window.ambient_card
                label = window.ambient_mode_title_label
                results.append(
                    {
                        "language": language,
                        "size": f"{width}x{height}",
                        "row_needs": row.minimumSizeHint().width(),
                        "row_has": row.width(),
                        "title": label.text(),
                        "title_needs": label.fontMetrics().horizontalAdvance(label.text()),
                        "title_has": label.width(),
                        "segment_labels": [
                            window.fusion_mode_segment._labels[key]
                            for key in ("screen", "screen_music")
                        ],
                        "segment_right": window.fusion_mode_segment.mapTo(
                            card, window.fusion_mode_segment.rect().topRight()
                        ).x(),
                        "button_right": window.ambient_toggle_button.mapTo(
                            card, window.ambient_toggle_button.rect().topRight()
                        ).x(),
                        "card_width": card.width(),
                        "card_height": card.height(),
                    }
                )
    finally:
        window._fusion_ui.shutdown()
        window._ambient_ui.shutdown()
        window._music_ui.shutdown()
        window._ble.shutdown()
        window.close()
    # Written as UTF-8 explicitly: the console on a Russian Windows is cp1251
    # and would refuse the Chinese titles this exists to check.
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
