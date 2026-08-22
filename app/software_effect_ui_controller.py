from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect

from app.software_effect_controller import SoftwareEffectController
from app.storage import save_settings
from app.widgets.animation_helpers import play_or_complete

_DEFAULTS = {"effect": "breathing", "speed": 30}


class SoftwareEffectUiController:
    """Wires the "App animations" card to the software-effect streaming backend.

    Free feature. While an animation runs it owns the strip colour, so the manual
    colour and firmware-effect controls are disabled and the other streaming modes
    (screen sync, music) are stopped first.
    """

    def __init__(self, host: Any) -> None:
        self._host = host
        self._fx = SoftwareEffectController(host)

    def wire(self) -> None:
        host = self._host
        host.software_fx_toggle.clicked.connect(self._toggle)
        host.software_fx_combo.currentIndexChanged.connect(self._on_options_changed)
        host.software_fx_speed_slider.valueChanged.connect(self._on_options_changed)
        self._fx.color_changed.connect(self._update_preview)
        self._setup_preview_reveal()
        self.sync_controls()

    def _setup_preview_reveal(self) -> None:
        host = self._host
        preview = getattr(host, "software_fx_preview", None)
        slot = getattr(host, "software_fx_preview_slot", None)
        if preview is None or slot is None:
            return
        self._preview_height = max(preview.minimumHeight(), host._sz(40)) + host._sz(12)
        self._preview_effect = QGraphicsOpacityEffect(preview)
        self._preview_effect.setOpacity(0.0)
        preview.setGraphicsEffect(self._preview_effect)
        self._preview_anim = QParallelAnimationGroup(host)
        self._preview_opacity = QPropertyAnimation(self._preview_effect, b"opacity")
        self._preview_min = QPropertyAnimation(slot, b"minimumHeight")
        self._preview_max = QPropertyAnimation(slot, b"maximumHeight")
        for animation in (self._preview_opacity, self._preview_min, self._preview_max):
            animation.setDuration(240)
            animation.setEasingCurve(QEasingCurve.InOutCubic)
            self._preview_anim.addAnimation(animation)
        self._preview_hiding = False
        self._preview_anim.finished.connect(self._finish_preview_reveal)

    def _animate_preview(self, *, opening: bool) -> None:
        preview = getattr(self._host, "software_fx_preview", None)
        slot = getattr(self._host, "software_fx_preview_slot", None)
        if preview is None or slot is None or getattr(self, "_preview_anim", None) is None:
            return
        self._preview_anim.stop()
        self._preview_hiding = not opening
        if opening:
            preview.setVisible(True)
        target = self._preview_height if opening else 0
        self._preview_opacity.setStartValue(self._preview_effect.opacity())
        self._preview_opacity.setEndValue(1.0 if opening else 0.0)
        self._preview_min.setStartValue(slot.minimumHeight())
        self._preview_min.setEndValue(target)
        self._preview_max.setStartValue(slot.maximumHeight())
        self._preview_max.setEndValue(target)
        play_or_complete(self._preview_anim)

    def _finish_preview_reveal(self) -> None:
        if not self._preview_hiding:
            return
        preview = getattr(self._host, "software_fx_preview", None)
        if preview is not None:
            preview.setVisible(False)
            preview.clear()
        self._preview_hiding = False

    def _update_preview(self, red: int, green: int, blue: int) -> None:
        preview = getattr(self._host, "software_fx_preview", None)
        if preview is not None:
            preview.set_color(red, green, blue)

    def sync_controls(self) -> None:
        host = self._host
        saved = host._settings.get("software_fx", {}) if isinstance(host._settings, dict) else {}
        effect = str(saved.get("effect", _DEFAULTS["effect"]))
        speed = int(saved.get("speed", _DEFAULTS["speed"]))
        index = host.software_fx_combo.findData(effect)
        host.software_fx_combo.blockSignals(True)
        host.software_fx_combo.setCurrentIndex(index if index >= 0 else 0)
        host.software_fx_combo.blockSignals(False)
        host.software_fx_speed_slider.jump_to(speed)
        self._refresh_value_labels()

    def is_running(self) -> bool:
        return self._fx.is_running()

    def stop_if_running(self) -> None:
        if self._fx.is_running():
            self._stop()

    def activate(self) -> bool:
        """Start the software effect as if its toggle was pressed. Returns
        whether it actually started (a gate may have blocked it)."""
        self._host.software_fx_toggle.setChecked(True)
        self._toggle()
        return self.is_running()

    def shutdown(self) -> None:
        self._fx.stop()

    def _toggle(self) -> None:
        host = self._host
        if not host.software_fx_toggle.isChecked():
            self._stop()
            return
        if not host._is_connected:
            host.software_fx_toggle.setChecked(False)
            host._show_error(host._tr("software_fx.not_connected"))
            return
        self._start()

    def _start(self) -> None:
        host = self._host
        # Only one owner drives the strip at a time — stop the others (screen
        # sync, music, DIY, sleep/sunrise timers).
        host.stop_streams(exclude=self)
        # If the strip is off the colour stream wouldn't show — turn it on first.
        if not host.power_button.isChecked():
            host.power_button.setChecked(True)
            host._toggle_power()
        self._apply_options()

        def sink(red: int, green: int, blue: int) -> None:
            host._ble.set_color_stream(red, green, blue)

        def base_provider() -> tuple[int, int, int]:
            color = host._current_color()
            return (color.red(), color.green(), color.blue())

        self._fx.start(sink, base_provider)
        self._set_manual_controls_enabled(False)
        preview = getattr(host, "software_fx_preview", None)
        if preview is not None:
            preview.clear()
            self._animate_preview(opening=True)
        host.software_fx_toggle.setText(host._tr("software_fx.toggle_on"))
        host._log(host._tr("software_fx.started_log"))

    def _stop(self) -> None:
        host = self._host
        was_running = self._fx.is_running()
        self._fx.stop()
        self._set_manual_controls_enabled(True)
        preview = getattr(host, "software_fx_preview", None)
        if preview is not None:
            self._animate_preview(opening=False)
        host.software_fx_toggle.setChecked(False)
        host.software_fx_toggle.setText(host._tr("software_fx.toggle_off"))
        if was_running:
            host._log(host._tr("software_fx.stopped_log"))

    def _apply_options(self) -> None:
        host = self._host
        effect = str(host.software_fx_combo.currentData() or "breathing")
        # Speed slider -> animation cycles per second (0.05 .. 0.7).
        speed = 0.05 + (host.software_fx_speed_slider.value() / 100.0) * 0.65
        self._fx.configure(effect=effect, speed=speed)

    def _on_options_changed(self) -> None:
        self._refresh_value_labels()
        self._persist()
        if self._fx.is_running():
            self._apply_options()

    def _refresh_value_labels(self) -> None:
        host = self._host
        host.software_fx_speed_value.setText(f"{host.software_fx_speed_slider.value()}%")

    def _persist(self) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        host._settings["software_fx"] = {
            "effect": str(host.software_fx_combo.currentData() or "breathing"),
            "speed": int(host.software_fx_speed_slider.value()),
        }
        save_settings(host._settings)

    def _set_manual_controls_enabled(self, enabled: bool) -> None:
        host = self._host
        # Power stays enabled so the strip can always be switched off.
        for widget in (
            host.red_slider,
            host.green_slider,
            host.blue_slider,
            host.brightness_slider,
            host.pick_color_button,
            host.effect_combo,
            host.speed_slider,
        ):
            widget.setEnabled(enabled)
