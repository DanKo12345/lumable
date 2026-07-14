"""ReconnectController turns BLE auto-reconnect into a visible status with a
countdown and a final give-up message. Driven by calling its handlers directly
(the real ones are wired to BLE signals)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject

from app.reconnect_controller import ReconnectController


class _Label:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


class _Host(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.device_status = _Label()
        self._is_connected = False
        self._connect_in_progress = False
        self._scan_in_progress = False

    def _tr(self, key: str, **kwargs: object) -> str:
        if kwargs:
            return key + " " + " ".join(f"{name}={value}" for name, value in kwargs.items())
        return key


def test_scheduled_shows_countdown_status() -> None:
    ctrl = ReconnectController(_Host())
    ctrl._on_scheduled("AA:BB", 2, 12, 5.0)
    text = ctrl._host.device_status.text
    assert "reconnect.status" in text
    assert "attempt=2" in text
    assert "total=12" in text


def test_gave_up_shows_final_message() -> None:
    ctrl = ReconnectController(_Host())
    ctrl._on_scheduled("AA:BB", 12, 12, 20.0)
    ctrl._on_gave_up("AA:BB")
    assert ctrl._host.device_status.text == "reconnect.gave_up"
    assert ctrl._active is False


def test_connected_clears_reconnect_state() -> None:
    ctrl = ReconnectController(_Host())
    ctrl._on_scheduled("AA:BB", 1, 12, 2.0)
    assert ctrl._active is True
    ctrl._on_connected(True, "AA:BB")
    assert ctrl._active is False


def test_scheduled_ignored_while_busy_elsewhere() -> None:
    host = _Host()
    host._connect_in_progress = True  # a manual connect is underway
    ctrl = ReconnectController(host)
    ctrl._on_scheduled("AA:BB", 1, 12, 2.0)
    assert ctrl._active is False
    assert host.device_status.text == ""
