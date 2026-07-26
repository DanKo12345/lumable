from __future__ import annotations

from PySide6.QtCore import QRect

from app.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from app.storage import validate_settings
from app.window_state_controller import WindowStateController


class _FakeScreen:
    def __init__(self, available: QRect) -> None:
        self._available = available

    def availableGeometry(self) -> QRect:
        return self._available


class _FakeHost:
    """A window whose frame adds a fixed title bar + borders to the client area,
    so we can check that the whole frameGeometry — not just the client — fits."""

    FRAME_W = 16
    FRAME_H = 48

    def __init__(self, settings: dict, screen: _FakeScreen) -> None:
        self._settings = settings
        self._screen = screen
        self._w = 1320
        self._h = 860
        self._x = 0
        self._y = 0

    def width(self) -> int:
        return self._w

    def height(self) -> int:
        return self._h

    def resize(self, width: int, height: int) -> None:
        self._w, self._h = width, height

    def screen(self):
        return self._screen

    def frameGeometry(self) -> QRect:
        return QRect(self._x, self._y, self._w + self.FRAME_W, self._h + self.FRAME_H)

    def move(self, point) -> None:
        self._x, self._y = point.x(), point.y()


def test_startup_frame_fits_a_1366x768_at_150pct_work_area() -> None:
    # 1366×768 at 150% ≈ 911×480 logical, minus the taskbar already reflected in
    # availableGeometry. The whole frame must stay inside it.
    available = QRect(0, 0, 911, 480)
    host = _FakeHost({"window_width": 1320, "window_height": 860}, _FakeScreen(available))

    WindowStateController(host).restore_startup_size()

    frame = host.frameGeometry()
    assert frame.width() <= available.width()
    assert frame.height() <= available.height()
    assert available.contains(frame)


def test_startup_size_uses_requested_when_the_screen_is_large() -> None:
    host = _FakeHost({"window_width": 1320, "window_height": 860}, _FakeScreen(QRect(0, 0, 2560, 1400)))

    WindowStateController(host).restore_startup_size()

    assert host.width() == 1320
    assert host.height() == 860


class _FrameHost:
    """Reports a window frame whose decoration overhead we control."""

    def __init__(self, over_w: int, over_h: int) -> None:
        self._ow = over_w
        self._oh = over_h

    def width(self) -> int:
        return 800

    def height(self) -> int:
        return 600

    def frameGeometry(self) -> QRect:
        return QRect(0, 0, 800 + self._ow, 600 + self._oh)


def test_partial_frame_overhead_is_raised_to_the_safe_fallback() -> None:
    # Before the window is fully decorated Qt may report a smaller frame (8×31);
    # the reserve must not drop below the safe 16×48 fallback.
    controller = WindowStateController(_FrameHost(8, 31))
    assert controller._frame_overhead() == (16, 48)


def test_larger_measured_frame_overhead_is_kept() -> None:
    controller = WindowStateController(_FrameHost(24, 60))
    assert controller._frame_overhead() == (24, 60)


def test_small_saved_window_size_survives_validation() -> None:
    # Without the lowered floor a small window snapped back up to 800×600 on the
    # next launch — larger than a 1366×768@150% screen.
    out = validate_settings({"window_width": WINDOW_MIN_WIDTH, "window_height": WINDOW_MIN_HEIGHT})

    assert out["window_width"] == WINDOW_MIN_WIDTH
    assert out["window_height"] == WINDOW_MIN_HEIGHT
