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
    window._automation_ui.sync_controls()


DEMOS = {"automations": _apply_automations_demo}


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

        out = Path(args.out) if args.out else ROOT / "docs" / "screenshots" / (
            f"{args.section}-{args.theme}-{width}x{height}.png"
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
