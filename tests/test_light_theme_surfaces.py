from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame

from app.main_window import MainWindow
from app.styles import build_theme_stylesheet
from app.theme import DARK, LIGHT


def _rule(stylesheet: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", stylesheet)
    assert match is not None, f"missing theme rule for {selector}"
    return match.group(1)


@pytest.mark.parametrize("tokens", (DARK, LIGHT))
def test_shell_surfaces_take_their_colours_from_the_theme(tokens) -> None:
    stylesheet = build_theme_stylesheet(tokens)

    assert tokens["surface_line"] in _rule(stylesheet, "#navSeparator")
    assert tokens["list_hover"] in _rule(stylesheet, "QPushButton#statusCard:hover")
    assert tokens["text"] in _rule(stylesheet, "QLabel#statusText")


def _check_live_light_theme_surfaces() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        surfaces = window.findChildren(QFrame, "settingsList")
        assert len(surfaces) >= 2, "the app-trigger rules surface is no longer a grouped list"
        assert all(surface.testAttribute(Qt.WA_StyledBackground) for surface in surfaces)

        window._is_connected = False
        window._connect_in_progress = False
        window._scan_in_progress = False
        window._reconnecting = False

        window._is_dark = False
        window._theme_controller.apply_theme()
        assert window._theme_tokens["muted"] in window.device_status_dot.styleSheet()

        window._is_dark = True
        window._theme_controller.apply_theme()
        assert window._theme_tokens["muted"] in window.device_status_dot.styleSheet()
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_live_light_theme_surfaces_are_paintable_and_refresh_the_idle_dot() -> None:
    """Run the full-window smoke check without inherited Qt global state."""
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("PYTEST_XDIST_WORKER", None)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(root), env.get("PYTHONPATH", "")) if part
    )
    with tempfile.TemporaryDirectory(prefix="lumable-theme-smoke-") as data_dir:
        env["LUMABLE_DATA_DIR"] = data_dir
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--live-check"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__" and sys.argv[1:] == ["--live-check"]:
    _check_live_light_theme_surfaces()
