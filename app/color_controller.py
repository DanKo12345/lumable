from __future__ import annotations

from typing import Any

from PySide6.QtGui import QColor

from app.feature_gate import (
    FREE_COLOR_HISTORY_COUNT,
    PRO_COLOR_HISTORY_COUNT,
    can_use,
    free_effect_limit,
)
from app.localization import localization_manager
from app.storage import save_settings
from app.widgets.effect_swatch import effect_swatch_icon


class ColorController:
    """Owns the colour-related logic split out of MainWindow.

    Currently holds the recent-colour history; the broader colour/effect/power
    logic will migrate here in later steps. Operates on the host window's
    widgets and settings, matching the existing controller pattern.
    """

    def __init__(self, host: Any) -> None:
        self._host = host

    def _limit(self) -> int:
        return PRO_COLOR_HISTORY_COUNT if can_use("color_history_full") else FREE_COLOR_HISTORY_COUNT

    def color_history(self) -> list[dict[str, int]]:
        history = self._host._settings.get("color_history", [])
        return history if isinstance(history, list) else []

    def refresh_history(self) -> None:
        host = self._host
        history = self.color_history()[: self._limit()]
        # Hide the "Recent" label when there's nothing yet (no empty row on top).
        host.color_history_label.setVisible(len(history) > 0)
        for index, button in enumerate(host.color_history_buttons):
            if index >= len(history):
                button.hide()
                continue
            item = history[index]
            button.set_color(QColor(int(item.get("r", 0)), int(item.get("g", 0)), int(item.get("b", 0))))
            button.show()

    def remember_current(self) -> None:
        host = self._host
        color = host._current_color()
        rgb = {"r": color.red(), "g": color.green(), "b": color.blue()}
        history = [
            item
            for item in self.color_history()
            if not (
                int(item.get("r", -1)) == rgb["r"]
                and int(item.get("g", -1)) == rgb["g"]
                and int(item.get("b", -1)) == rgb["b"]
            )
        ]
        host._settings["color_history"] = [rgb, *history][: self._limit()]
        save_settings(host._settings)
        self.refresh_history()

    def apply_history_item(self, index: int) -> None:
        host = self._host
        history = self.color_history()
        if index < 0 or index >= len(history):
            return
        item = history[index]
        with host._suppress_signals():
            host.red_slider.setValue(int(item.get("r", 0)))
            host.green_slider.setValue(int(item.get("g", 0)))
            host.blue_slider.setValue(int(item.get("b", 0)))
            host._update_preview()
        host._apply_current_color()

    # ── Effects ────────────────────────────────────────────────────────

    def refresh_effect_names(self) -> None:
        host = self._host
        current_code = host.effect_combo.currentData()
        effects = list(host._ble.effect_presets())
        unlocked_count = len(effects) if can_use("all_effects") else free_effect_limit()
        host.effect_combo.blockSignals(True)
        host.effect_combo.clear()
        host._effect_key_by_code = {effect.code: effect.key for effect in effects[:unlocked_count]}
        for index, effect in enumerate(effects):
            name = localization_manager.effect_name(effect.key)
            locked = index >= unlocked_count
            icon = effect_swatch_icon(effect.key, effect.code, is_dark=host._is_dark, locked=locked)
            host.effect_combo.addItem(icon, name, None if locked else effect.code)
        idx = host.effect_combo.findData(current_code)
        host.effect_combo.setCurrentIndex(idx if idx >= 0 else 0)
        host.effect_combo.blockSignals(False)
        host._sync_speed_controls()

    def sync_effect_preview(self, *, reset_phase: bool = False) -> None:
        host = self._host
        data = host.effect_combo.currentData()
        code = int(data or 0)
        host._sync_speed_controls()
        host.effect_preview.set_effect(host._effect_key_by_code.get(code, "static_color"), code, reset_phase=reset_phase)
        host.effect_preview.set_speed(host.speed_slider.value())

    def sync_speed_controls(self) -> None:
        host = self._host
        is_static = int(host.effect_combo.currentData() or 0) == 0
        supports_speed = host._ble.supports_effect_speed()
        visible = not is_static
        enabled = visible and supports_speed
        speed_label = host._slider_labels.get("effects.speed")
        if speed_label is not None:
            speed_label.setVisible(visible)
        host.speed_slider.setVisible(visible)
        host.speed_slider.setEnabled(enabled)
        host.speed_value.setVisible(visible)
        host.speed_value.setEnabled(enabled)

    def apply_speed(self) -> None:
        host = self._host
        if host._initializing:
            return
        host._ble.set_effect_speed(host.speed_slider.value())
        host._sync_quick_mode_from_state()

    def queue_selected_effect(self) -> None:
        host = self._host
        if host._initializing:
            return
        if host.effect_combo.currentData() is None:
            host._effect_debounce.stop()
            host._show_license_overlay()
            with host._suppress_signals():
                host.effect_combo.setCurrentIndex(host.effect_combo.findData(0))
            host._sync_effect_preview(reset_phase=True)
            return
        host._sync_effect_preview(reset_phase=True)
        host._sync_quick_mode_from_state()
        host._effect_debounce.start()

    def apply_selected_effect(self) -> None:
        host = self._host
        if host._initializing:
            return
        data = host.effect_combo.currentData()
        if data is None:
            host._show_license_overlay()
            with host._suppress_signals():
                host.effect_combo.setCurrentIndex(host.effect_combo.findData(0))
            host._sync_effect_preview(reset_phase=True)
            return
        code = int(data)
        if code == 0:
            host._ble.set_static_color(
                host.red_slider.value(),
                host.green_slider.value(),
                host.blue_slider.value(),
                host.brightness_slider.value(),
            )
            host._remember_current_color()
            host._log(host._tr("status.static_color_mode"))
            host._sync_effect_preview(reset_phase=True)
            host._sync_quick_mode_from_state()
            return
        host._ble.set_effect_with_speed(code, host.speed_slider.value())
        host._sync_effect_preview(reset_phase=True)
        host._sync_quick_mode_from_state()
