from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QTimer


class ReconnectController:
    """Turns the BLE layer's silent auto-reconnect into a clear on-screen state.

    While the strip is being re-reached it shows a live countdown to the next
    attempt in the device status line ("Reconnecting… (2/12), next try in 5s").
    The existing Connect button already retries immediately, so no extra control
    is needed. After the final attempt it explains that the strip is off or out
    of range. Purely presentational — it never drives the connection itself.
    """

    def __init__(self, host: Any) -> None:
        self._host = host
        self._active = False
        self._attempt = 0
        self._total = 0
        self._deadline = 0.0
        self._timer = QTimer(host)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)

    def wire(self) -> None:
        ble = self._host._ble
        ble.reconnect_scheduled.connect(self._on_scheduled)
        ble.reconnect_gave_up.connect(self._on_gave_up)
        ble.connected_changed.connect(self._on_connected)

    # ── state from the BLE layer ──────────────────────────────────────
    def _on_scheduled(self, address: str, attempt: int, total: int, delay: float) -> None:
        # A manual connect/scan takes precedence — don't fight it.
        if self._busy_elsewhere():
            return
        self._active = True
        self._attempt = int(attempt)
        self._total = int(total)
        self._deadline = time.monotonic() + float(delay)
        self._set_reconnecting(True)
        self._render()
        if not self._timer.isActive():
            self._timer.start()

    def _on_gave_up(self, _address: str) -> None:
        self._active = False
        self._timer.stop()
        self._set_reconnecting(False)
        if not self._busy_elsewhere():
            self._host.device_status.setText(self._host._tr("reconnect.gave_up"))

    def _on_connected(self, connected: bool, _address: str) -> None:
        if connected:
            self._active = False
            self._timer.stop()
            self._set_reconnecting(False)

    # ── countdown ─────────────────────────────────────────────────────
    def _tick(self) -> None:
        if not self._active or self._busy_elsewhere():
            self._active = False
            self._timer.stop()
            self._set_reconnecting(False)
            return
        self._render()

    def _set_reconnecting(self, value: bool) -> None:
        """Drive the shared status dot into (or out of) its pulsing
        'reconnecting' state, matching scan/connect."""
        host = self._host
        host._reconnecting = bool(value)
        update = getattr(host, "_update_status_dot", None)
        if callable(update):
            update()

    def _render(self) -> None:
        host = self._host
        remaining = max(0, round(self._deadline - time.monotonic()))
        host.device_status.setText(
            host._tr("reconnect.status", attempt=self._attempt, total=self._total, secs=remaining)
        )

    def _busy_elsewhere(self) -> bool:
        host = self._host
        return bool(
            getattr(host, "_is_connected", False)
            or getattr(host, "_connect_in_progress", False)
            or getattr(host, "_scan_in_progress", False)
        )
