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

# The three words the start/stop button can carry. Preview added the longest of
# them, and the button cannot grow: the row has six pixels of slack in Spanish
# at the smallest window, so a wider button would push the row over instead.
TOGGLE_KEYS = ("ambient.toggle_off", "ambient.toggle_on", "ambient.toggle_preview")


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
        # Measured in the combined mode: that is when the settings button is
        # shown, and a row that fits without it proves nothing about the row a
        # person actually sees while using the mode.
        window._fusion_ui.set_mode("screen_music", persist=False)
        window._ambient_ui.sync_mode_segment()
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
                # How much the collapsed panel costs, and how much it costs
                # open. Measured on a shown window, because a hidden one never
                # recomputes its layout and would report the two as equal.
                collapsed_height = card.height()
                window.fusion_tune_button.setChecked(True)
                window._ambient_ui._tune_anim.setCurrentTime(
                    window._ambient_ui._tune_anim.totalDuration()
                )
                for _ in range(6):
                    app.processEvents()
                opened_height = card.height()
                window.fusion_tune_button.setChecked(False)
                window._ambient_ui._tune_anim.setCurrentTime(
                    window._ambient_ui._tune_anim.totalDuration()
                )
                for _ in range(6):
                    app.processEvents()
                # Every word the toggle can carry, measured in the button it
                # has to fit. The button is a fixed size, so a long word is not
                # a wider row — it is a clipped word, which nothing reports.
                button = window.ambient_toggle_button
                original_label = button.text()
                toggle_needs = {}
                for key in TOGGLE_KEYS:
                    button.setText(window._tr(key))
                    app.processEvents()
                    toggle_needs[key] = {
                        "text": button.text(),
                        "needs": button.sizeHint().width(),
                    }
                button.setText(original_label)
                app.processEvents()
                results.append(
                    {
                        "language": language,
                        "size": f"{width}x{height}",
                        "toggle_button_width": button.width(),
                        "toggle_needs": toggle_needs,
                        "row_needs": row.minimumSizeHint().width(),
                        "row_has": row.width(),
                        "title": label.text(),
                        "title_needs": label.fontMetrics().horizontalAdvance(label.text()),
                        "title_has": label.width(),
                        "segment_labels": [
                            window.fusion_mode_segment._labels[key]
                            for key in ("screen", "screen_music")
                        ],
                        "panel_labels": [
                            window.fusion_source_segment._labels["system"],
                            window.fusion_source_segment._labels["mic"],
                            window.fusion_beat_label.text(),
                            window.fusion_tune_button.toolTip(),
                        ],
                        "segment_right": window.fusion_mode_segment.mapTo(
                            card, window.fusion_mode_segment.rect().topRight()
                        ).x(),
                        "button_right": window.ambient_toggle_button.mapTo(
                            card, window.ambient_toggle_button.rect().topRight()
                        ).x(),
                        "card_width": card.width(),
                        "card_height": card.height(),
                        "tune_button_shown": bool(window.fusion_tune_button.isVisible()),
                        "tune_row_shown": bool(window.fusion_tune_row.isVisible()),
                        "card_height_collapsed": collapsed_height,
                        "card_height_open": opened_height,
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
