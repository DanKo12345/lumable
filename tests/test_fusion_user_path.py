"""The path a person actually takes, from the card to the strip and back.

Choose *Экран + музыка* on the screen card, press start, and the colour that
reaches the BLE layer should be the picture's, dimmed by what the music is
doing. Then press stop and everything lets go.

Driven by clicks rather than by calling the controllers: the point is that the
widgets are wired to the thing that was built, and every previous mistake in
this work was found below the level the user actually touches.
"""

from __future__ import annotations

import sys
import threading
import time
import types

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

SCREEN_COLOUR = (210, 70, 30)


class _FakeShot:
    def __init__(self) -> None:
        self.width = 4
        self.height = 4
        red, green, blue = SCREEN_COLOUR
        self.bgra = bytes([blue, green, red, 255] * 16)


class _FakeSct:
    monitors = [
        {"left": 0, "top": 0, "width": 8, "height": 8},
        {"left": 0, "top": 0, "width": 8, "height": 8},
    ]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def grab(self, _region):
        return _FakeShot()


def _music_reader(_options):
    """A steady piece of music: loud enough to open the gate, not silent."""
    step = [0]

    def read(_size):
        step[0] += 1
        # A slow swell so the level moves rather than sitting on one number,
        # which is what a gate with hysteresis is built for.
        amplitude = 0.25 + 0.15 * ((step[0] % 8) / 8.0)
        time.sleep(0.005)
        return [[amplitude, -amplitude]] * 512

    return read, lambda: None, 48000


class _Strip:
    def __init__(self) -> None:
        self.writes: list[tuple[int, int, int]] = []
        self.lock = threading.Lock()

    def set_color_stream(self, red, green, blue, **_kwargs) -> bool:
        with self.lock:
            self.writes.append((red, green, blue))
        return True

    def count(self) -> int:
        with self.lock:
            return len(self.writes)


@pytest.fixture()
def window(monkeypatch):
    import app.ambient_ui_controller as ambient_module
    import app.fusion_ui_controller as fusion_module
    import app.music_ui_controller as music_module
    from app.main_window import MainWindow
    from app.music_controller import MusicController

    app = QApplication.instance() or QApplication([])
    monkeypatch.setitem(sys.modules, "mss", types.SimpleNamespace(mss=_FakeSct))
    for module in (ambient_module, fusion_module, music_module):
        monkeypatch.setattr(module, "can_use", lambda _feature: True)
    monkeypatch.setattr(
        MusicController, "_open_loopback_reader", staticmethod(_music_reader), raising=True
    )

    win = MainWindow()
    win._show_error = lambda *_a, **_k: None
    win._is_connected = True
    strip = _Strip()
    monkeypatch.setattr(win._ble, "set_color_stream", strip.set_color_stream, raising=False)
    win._strip = strip
    app.processEvents()
    try:
        yield win
    finally:
        win._fusion_ui.shutdown()
        win._ambient_ui.shutdown()
        win._music_ui.shutdown()
        win._ble.shutdown()
        win.close()


def _click_second_segment(segment) -> None:
    """Press the right-hand half of a two-option control, as a person would."""
    segment.resize(200, 40)
    QTest.mouseClick(segment, Qt.LeftButton, pos=QPoint(150, 20))


def _pump(app, seconds: float, until=None) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if until is not None and until():
            return
        time.sleep(0.01)
    app.processEvents()


def test_screen_plus_music_from_the_card_to_the_strip_and_back(window) -> None:
    app = QApplication.instance()
    strip = window._strip

    # ── choose the mode, by clicking it ───────────────────────────────
    _click_second_segment(window.fusion_mode_segment)
    assert window.fusion_mode_segment.current_key() == "screen_music"
    assert window._fusion_ui.mode() == "screen_music"
    assert window._settings["fusion"]["mode"] == "screen_music", "the choice was not saved"

    # The music card stops offering its own start: one mode, one stop button.
    assert window.music_toggle_button.isEnabled() is False
    assert window.music_status_label.text() == window._tr("fusion.music_shared")

    # ── start it, by pressing the card's button ───────────────────────
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    assert window._fusion_ui.is_running(), "the mode did not start"

    _pump(app, 5.0, until=lambda: strip.count() >= 4)
    assert strip.count() >= 2, "nothing reached the strip"

    # ── the colour is the screen's, the brightness is the music's ─────
    stats = window._fusion_ui.stats()
    assert stats["mode"] == "screen_music"
    assert stats["music_stale"] is False, "the music was never heard"
    assert stats["music_activity"] > 0.0
    assert stats["brightness_factor"] < 1.0, "the music moved nothing"

    written = strip.writes[-1]
    assert written[0] > written[1] > written[2], f"not the screen's colour: {written}"

    # Compared against the composed frame rather than the raw screen colour: the
    # capture pipeline shapes what it grabs — saturation, gamma and the chosen
    # profile all move it — so the base is legitimately not the pixel value the
    # fake screen returned. What has to hold is that the write is that base
    # scaled: the ratios between the channels survive, the level drops.
    base = window._fusion_ui.coordinator().last_frame().rgb
    assert max(written) < max(base), f"the music never dimmed anything: {written} of {base}"
    assert base[0] > base[1] > base[2], f"the base lost the screen's hue: {base}"
    ratio = max(written) / max(base)
    for index in range(3):
        assert abs(written[index] - base[index] * ratio) <= 12, (
            f"the hue moved: written {written}, base {base}"
        )

    # ── stop it, from the same button ─────────────────────────────────
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    app.processEvents()
    settled = strip.count()

    assert window._fusion_ui.is_running() is False
    assert window._ambient_ui.is_running() is False
    assert window._music_ui.is_running() is False

    _pump(app, 0.5)
    assert strip.count() == settled, "commands kept going out after the stop"


def test_going_back_to_screen_only_leaves_music_its_own_card(window) -> None:
    """The old standalone mode has to keep working exactly as it did."""
    _click_second_segment(window.fusion_mode_segment)
    assert window.music_toggle_button.isEnabled() is False

    segment = window.fusion_mode_segment
    segment.resize(200, 40)
    QTest.mouseClick(segment, Qt.LeftButton, pos=QPoint(50, 20))

    assert window._fusion_ui.mode() == "screen"
    assert window.music_toggle_button.isEnabled() is True
    assert window._settings["fusion"]["mode"] == "screen"


def test_the_saved_mode_comes_back_on_the_next_run(window) -> None:
    _click_second_segment(window.fusion_mode_segment)

    window._fusion_ui.set_mode("screen", persist=False)
    window._fusion_ui.load_settings()
    window._ambient_ui.sync_mode_segment()

    assert window._fusion_ui.mode() == "screen_music"
    assert window.fusion_mode_segment.current_key() == "screen_music"
