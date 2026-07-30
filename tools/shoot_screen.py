#!/usr/bin/env python3
"""Render one section of the app to a PNG, for visual review of a change.

Run from the project root:

    python tools/shoot_screen.py automations --size 1280x860 --theme dark

Two things it is careful about, because both have bitten this repo before:

* **It never touches the real LumaBLE data.** The storage paths are pointed at a
  throwaway directory before anything is imported that might read them, so a run
  cannot leave demo rules in the user's settings.
* **It uses the real platform plugin, not ``offscreen``.** Offscreen renders every
  glyph as a box on Windows, which makes a screenshot useless for exactly the thing
  a screenshot is for. The window is opened fully transparent instead, so nothing
  flashes on screen while it is grabbed.

``--demo automations`` fills the automations screen with a rule of every kind, a
pause the machine has not been told about, and the 0.3.5 bridge card — the state a
screenshot has to show to be worth reviewing, and one nobody's real settings are in.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEMO_RULES = [
    {
        "id": "evening",
        "name": "Evening",
        "trigger": {"kind": "time", "time_at": "21:00", "days": [0, 1, 2, 3, 4, 5, 6]},
        "action": {"type": "set_power", "power": True, "target": "primary"},
        "execution": "background",
    },
    {
        "id": "weekend-night",
        "name": "",
        "trigger": {"kind": "time", "time_at": "23:30", "days": [4, 5]},
        "action": {"type": "set_power", "power": False, "target": "primary"},
        "execution": "background",
    },
    {
        "id": "coding",
        "name": "Coding",
        "trigger": {"kind": "app_foreground", "app": "code.exe"},
        "action": {"type": "apply_scene", "scene_id": "scene-desk"},
    },
    {
        "id": "away",
        "name": "",
        "trigger": {"kind": "no_input", "minutes": 20},
        "action": {"type": "set_power", "power": False, "target": "primary"},
        "enabled": False,
    },
    {
        "id": "fallback",
        "name": "Movie night",
        "trigger": {"kind": "always"},
        "action": {"type": "apply_scene", "scene_id": "scene-gone"},
    },
]

DEMO_SCENES = [
    {"scene_id": "scene-desk", "name": "Warm desk", "state": {"rgb": [255, 170, 90], "brightness": 60}}
]


def _isolated_data_dir(theme: str, language: str) -> Path:
    """Point storage at a throwaway directory holding just enough settings."""
    from app import storage

    data_dir = Path(tempfile.mkdtemp(prefix="lumable-shot-"))
    storage.DATA_DIR = data_dir
    storage.SETTINGS_PATH = data_dir / "settings.json"
    storage.PROFILES_PATH = data_dir / "profiles.json"
    storage._migration_done = True
    storage._legacy_migration_pairs = lambda: []
    storage.SETTINGS_PATH.write_text(
        json.dumps(
            {
                "theme_mode": theme,
                "language": language,
                "onboarding_seen": True,
            }
        ),
        encoding="utf-8",
    )
    return data_dir


def _demo_journal_entries():
    """A handful of entries covering all four outcomes, newest first."""
    from datetime import datetime, timedelta

    from app.automation.journal import (
        KIND_CANCELLED,
        KIND_ERROR,
        KIND_SKIPPED,
        KIND_SUCCESS,
        JournalEntry,
    )

    now = datetime.now().replace(second=0, microsecond=0)
    rows = [
        (KIND_SUCCESS, "coding", "scene_applied", "", 1, now - timedelta(minutes=4)),
        (KIND_SKIPPED, "evening", "", "disconnected", 6, now - timedelta(minutes=38)),
        (KIND_ERROR, "weekend-night", "execution_timeout", "", 1, now - timedelta(hours=3)),
        (KIND_CANCELLED, "fallback", "execution_cancelled", "", 1, now - timedelta(hours=9)),
        (KIND_SUCCESS, "gone-rule", "power_set", "", 1, now - timedelta(days=1, hours=2)),
    ]
    return [
        JournalEntry(
            id=index,
            kind=kind,
            rule_id=rule_id,
            message_code=code,
            reason=reason,
            count=count,
            first_seen=seen,
            last_seen=seen,
            uid=f"demo-{index}",
        )
        for index, (kind, rule_id, code, reason, count, seen) in enumerate(rows)
    ]


def _apply_automations_demo(window) -> None:
    from app.automation.windows_tasks import TaskSyncResult
    from app.automation_ui_controller import PAUSE_PENDING

    window._settings["automations"] = {
        "enabled": True,
        "rules": DEMO_RULES,
        "legacy_bridge": True,
    }
    window._settings["scenes"] = DEMO_SCENES
    controller = window._automations
    # The screen reads these; the engine behind them is not running in a screenshot.
    controller.is_running = lambda: True
    controller.pause_status = lambda: PAUSE_PENDING
    controller.paused_until = lambda: None
    controller._last_task_result = TaskSyncResult(unchanged=("evening", "weekend-night"))
    entries = _demo_journal_entries()
    controller.journal = lambda limit=100: entries[:limit]
    window._automation_ui.sync_controls()


def _apply_journal_demo(window) -> None:
    """The page scrolled to the history card, which is below the fold on any window."""
    from PySide6.QtWidgets import QApplication

    _apply_automations_demo(window)
    # The page has just been filled in; without letting the layout settle first, the
    # scroll would be computed against geometry that is still all zeroes.
    app = QApplication.instance()
    for _ in range(8):
        app.processEvents()
    # Not the scrollbar's maximum: the canvas keeps a stretch below the cards, so
    # the bottom of the range is empty space past the last one.
    window.body_scroll.ensureWidgetVisible(window.automations_journal_card, 0, 24)


def _apply_rule_new_demo(window) -> None:
    """The editor as it opens for a rule that does not exist yet."""
    _apply_automations_demo(window)
    window.automations_add_button.click()


def _apply_rule_edit_demo(window) -> None:
    """The editor on an existing rule: named, with a scene, and deletable."""
    from PySide6.QtTest import QTest

    _apply_automations_demo(window)
    window._automation_ui._edit_rule("coding")
    editor = window._automation_ui._editor
    if editor is not None:
        editor.advanced_button.setChecked(True)
        editor._toggle_advanced()
        QTest.qWait(240)


def _apply_license_demo(window) -> None:
    """Open the Free purchase view without touching a real licence."""
    window._show_license_overlay()


def _apply_license_key_demo(window) -> None:
    """Open the purchase view with the existing-key form revealed."""
    window._show_license_overlay()
    overlay = window._overlay_controller._license_overlay
    if overlay is not None:
        overlay._reveal_key()


def _apply_confirm_demo(window) -> None:
    """Open the compact destructive confirmation used by scene deletion."""
    from app.widgets.profile_action_overlay import ProfileConfirmOverlay

    overlay = ProfileConfirmOverlay(
        {
            "title": "Удалить сцену",
            "message": "Сцена «hhh» будет удалена.",
            "cancel": "Отмена",
            "confirm": "Удалить",
        },
        window,
        confirm_role="danger",
    )
    window._screenshot_overlay = overlay
    overlay.open()


DEMOS = {
    "automations": _apply_automations_demo,
    "journal": _apply_journal_demo,
    "license": _apply_license_demo,
    "license-key": _apply_license_key_demo,
    "confirm": _apply_confirm_demo,
    "rule-new": _apply_rule_new_demo,
    "rule-edit": _apply_rule_edit_demo,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("section", help="nav section key, e.g. color / scenes / automations")
    parser.add_argument("--size", default="1280x860", help="WIDTHxHEIGHT, default 1280x860")
    parser.add_argument("--theme", default="dark", choices=("dark", "light"))
    parser.add_argument("--language", default="en")
    parser.add_argument("--demo", default="", help="fill a section with review content")
    parser.add_argument("--out", default="", help="output PNG (default docs/screenshots/…)")
    args = parser.parse_args(argv)

    width, _, height = args.size.partition("x")
    _isolated_data_dir(args.theme, args.language)

    from PySide6.QtWidgets import QApplication

    from app.main_layout import select_section
    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        # Transparent before it is ever mapped: a grab renders the widget tree
        # directly, so nothing is lost by never letting the window be seen.
        window.setWindowOpacity(0.0)
        window.resize(int(width), int(height))
        window.show()
        select_section(window, args.section)
        demo = DEMOS.get(args.demo)
        if demo is not None:
            demo(window)
        for _ in range(8):
            app.processEvents()

        # Named after the demo when there is one, so an overlay's snapshot does not
        # overwrite the screen's underneath it.
        stem = args.demo or args.section
        out = Path(args.out) if args.out else ROOT / "docs" / "screenshots" / (
            f"{stem}-{args.theme}-{width}x{height}.png"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(out))
        print(out)
    finally:
        window._ble.shutdown()
        window.close()
        for _ in range(8):
            app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
