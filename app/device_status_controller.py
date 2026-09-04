from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPropertyAnimation, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect

from app.device_view_state import DeviceViewState, describe_device
from app.motion_policy import motion_policy

if TYPE_CHECKING:
    from app.main_window import MainWindow


class DeviceStatusController:
    """Render connection state without owning any BLE operations."""

    def __init__(self, window: MainWindow) -> None:
        self._window = window
        self._text_phase = 0
        self._wants_pulse = False
        self._dot_effect: QGraphicsOpacityEffect | None = None
        self._pulse: QPropertyAnimation | None = None
        self._text_timer = QTimer(window)
        self._text_timer.setInterval(450)
        self._text_timer.timeout.connect(self.tick_status_text)
        motion_policy.changed.connect(self.sync_pulse)

    def view(self) -> DeviceViewState:
        host = self._window
        snapshot = host._ble.diagnostics_snapshot() if host._is_connected else {}
        return describe_device(
            connected=bool(host._is_connected),
            scanning=bool(host._scan_in_progress),
            connecting=bool(host._connect_in_progress),
            checking=bool(host._inspect_in_progress),
            error=getattr(host, "_device_problem", ""),
            selected=host._selected_device(),
            connected_name=str(
                host._settings.get("last_device_name")
                or host._settings.get("last_device_address")
                or ""
            ),
            driver_name=str((snapshot.get("driver") or {}).get("name", "")),
            connected_rssi=(snapshot.get("device") or {}).get("rssi"),
            capabilities=snapshot.get("commands") or None,
        )

    def sync(self) -> None:
        host = self._window
        report_button = getattr(host, "save_report_button", None)
        if report_button is not None:
            report_button.setVisible(bool(host._offer_report) and not host._is_connected)
        connected = bool(host._is_connected)
        connecting = bool(host._connect_in_progress)
        has_devices = bool(host._devices)
        active = (connecting or host._scan_in_progress) and not connected
        if active:
            if not self._text_timer.isActive():
                self._text_phase = 0
                self._text_timer.start()
            host.device_status.setText(self._status_text())
        elif self._text_timer.isActive():
            self._text_timer.stop()

        self.update_dot()
        self._render_meta(self.view())
        inspecting = bool(host._inspect_in_progress)
        busy = connecting or host._scan_in_progress or inspecting
        host.scan_button.setEnabled(not connected and not busy)
        host.connect_button.setVisible(not connected)
        host.connect_button.setEnabled(not connected and not busy and has_devices)
        if inspecting:
            host.connect_button.setText(host._tr("device.inspect_running"))
            self._describe_connect_button(host._tr("device.inspect_running"), "")
        elif host._selected_device_is_unknown():
            host.connect_button.setText(host._tr("device.inspect"))
            self._describe_connect_button(
                host._tr("device.inspect_full"), host._tr("device.inspect_hint")
            )
        else:
            host.connect_button.setText(host._tr("device.connect"))
            self._describe_connect_button(host._tr("device.connect"), "")
        host.disconnect_button.setVisible(connected)
        host.disconnect_button.setEnabled(connected)
        host.logs_toggle_button.setVisible(connected)
        host.logs_toggle_button.setEnabled(connected)
        host.logs_toggle_button.setText(host._tr("device.show_logs"))
        host.rename_device_button.setVisible(connected)

    def _render_meta(self, view: DeviceViewState) -> None:
        host = self._window
        meta = getattr(host, "device_primary_meta", None)
        if meta is None:
            return
        parts: list[str] = []
        if view.detail and view.state in ("error", "unknown", "checking"):
            parts.append(view.detail)
        if view.driver_name:
            parts.append(host._tr("device.meta.driver", driver=view.driver_name))
        elif view.is_unknown:
            parts.append(host._tr("device.meta.unknown_protocol"))
        parts.extend(
            f"{host._tr(label)}: "
            f"{host._tr(value) if value.startswith('device.fact.') else value}"
            for label, value in view.facts
        )
        meta.setText("  ·  ".join(parts) if parts else host._tr("device.primary_empty"))

    def _describe_connect_button(self, name: str, hint: str) -> None:
        button = self._window.connect_button
        button.setAccessibleName(name)
        button.setToolTip(hint)

    def _status_text(self) -> str:
        host = self._window
        key = "device.status.connecting" if host._connect_in_progress else "device.status.scanning"
        return f"{host._tr(key).rstrip('.…')}{'.' * self._text_phase}"

    def tick_status_text(self) -> None:
        host = self._window
        active = (host._connect_in_progress or host._scan_in_progress) and not host._is_connected
        if not active:
            self._text_timer.stop()
            self.sync()
            return
        self._text_phase = (self._text_phase + 1) % 4
        host.device_status.setText(self._status_text())

    def _ensure_pulse(self) -> None:
        if self._dot_effect is not None:
            return
        dot = getattr(self._window, "device_status_dot", None)
        if dot is None:
            return
        self._dot_effect = QGraphicsOpacityEffect(dot)
        dot.setGraphicsEffect(self._dot_effect)
        self._dot_effect.setOpacity(1.0)
        self._pulse = QPropertyAnimation(self._dot_effect, b"opacity", self._window)
        self._pulse.setDuration(1100)
        self._pulse.setLoopCount(-1)
        self._pulse.setKeyValueAt(0.0, 1.0)
        self._pulse.setKeyValueAt(0.5, 0.4)
        self._pulse.setKeyValueAt(1.0, 1.0)
        self._pulse.setEasingCurve(QEasingCurve.InOutSine)

    def update_dot(self) -> None:
        host = self._window
        dot = getattr(host, "device_status_dot", None)
        if dot is None:
            return
        self._ensure_pulse()
        if host._is_connected:
            color = "#46d39a"
        elif host._connect_in_progress:
            color = "#6fa8ff"
        elif host._scan_in_progress:
            color = "#f5b94a"
        elif host._reconnecting:
            color = "#ff9a5b"
        else:
            color = host._theme_tokens["muted"]
        dot.setStyleSheet(
            f"background: {color}; border-radius: {max(2, dot.width() // 2)}px;"
        )
        self._wants_pulse = (
            host._connect_in_progress or host._scan_in_progress or host._reconnecting
        ) and not host._is_connected
        self.sync_pulse()

    def sync_pulse(self, _reduced: bool | None = None) -> None:
        if self._pulse is None or self._dot_effect is None:
            return
        if self._wants_pulse and not motion_policy.reduced:
            if self._pulse.state() != QAbstractAnimation.Running:
                self._pulse.start()
            return
        self._pulse.stop()
        self._dot_effect.setOpacity(1.0)
