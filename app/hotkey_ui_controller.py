from __future__ import annotations

from PySide6.QtWidgets import QGraphicsOpacityEffect

from app.hotkeys import ACTIONS, DEFAULT_HOTKEYS, parse_hotkey
from app.storage import save_settings


class HotkeyUiController:
    """Wires the 'global hotkeys' settings card: a master toggle plus an editable
    spec field per action. Pro-gated; the registration engine (HotkeyController)
    reads the same persisted settings via host._apply_hotkeys()."""

    def __init__(self, host) -> None:
        self._host = host
        self._controls_effect: QGraphicsOpacityEffect | None = None

    def wire(self) -> None:
        host = self._host
        host.hotkeys_toggle_button.clicked.connect(self._toggle)
        host.hotkeys_reset_button.clicked.connect(self._reset_defaults)
        for field in host.hotkey_inputs.values():
            field.captured.connect(self._persist)
        self.sync_controls()
        self.refresh_lock()

    def _reset_defaults(self) -> None:
        host = self._host
        with host._suppress_signals():
            for action, field in host.hotkey_inputs.items():
                field.setText(DEFAULT_HOTKEYS[action])
        self._persist()

    def _config(self) -> dict:
        host = self._host
        config = host._settings.get("hotkeys", {}) if isinstance(host._settings, dict) else {}
        return config if isinstance(config, dict) else {}

    def sync_controls(self) -> None:
        host = self._host
        config = self._config()
        bindings = config.get("bindings", {})
        bindings = bindings if isinstance(bindings, dict) else {}
        with host._suppress_signals():
            host.hotkeys_toggle_button.setChecked(bool(config.get("enabled", False)))
            for action, field in host.hotkey_inputs.items():
                field.setText(str(bindings.get(action, DEFAULT_HOTKEYS[action])))
        self._sync_toggle_text()
        self._apply_enabled_state()

    def _collect_bindings(self) -> dict[str, str]:
        host = self._host
        bindings: dict[str, str] = {}
        for action in ACTIONS:
            field = host.hotkey_inputs.get(action)
            spec = field.text().strip() if field is not None else ""
            # Keep a working combo: revert to the default if the typed spec is invalid.
            bindings[action] = spec if parse_hotkey(spec) is not None else DEFAULT_HOTKEYS[action]
        return bindings

    def _persist(self, *_args: object) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        bindings = self._collect_bindings()
        host._settings["hotkeys"] = {
            "enabled": bool(host.hotkeys_toggle_button.isChecked()),
            "bindings": bindings,
        }
        # Reflect any normalization (invalid → default) back into the fields.
        for action, field in host.hotkey_inputs.items():
            if field.text().strip() != bindings[action]:
                field.setText(bindings[action])
        save_settings(host._settings)
        host._apply_hotkeys()

    def _toggle(self) -> None:
        # Global hotkeys are free — just toggle on/off.
        self._sync_toggle_text()
        self._persist()
        self._apply_enabled_state()

    def _sync_toggle_text(self) -> None:
        host = self._host
        on = host.hotkeys_toggle_button.isChecked()
        host.hotkeys_toggle_button.setText(
            host._tr("hotkeys.toggle_on") if on else host._tr("hotkeys.toggle_off")
        )
        host.hotkeys_toggle_button.set_role("accent_soft" if on else "ghost")

    def refresh_lock(self) -> None:
        # Kept for the controller interface; hotkeys are free, nothing to lock.
        self._apply_enabled_state()

    def _apply_enabled_state(self) -> None:
        host = self._host
        active = host.hotkeys_toggle_button.isChecked()
        controls = getattr(host, "hotkeys_controls", None)
        if controls is None:
            return
        controls.setEnabled(active)
        if self._controls_effect is None:
            self._controls_effect = QGraphicsOpacityEffect(controls)
            controls.setGraphicsEffect(self._controls_effect)
        self._controls_effect.setOpacity(1.0 if active else 0.4)

    def relocalize(self) -> None:
        host = self._host
        self._sync_toggle_text()
        for action, label in getattr(host, "hotkey_action_labels", {}).items():
            label.setText(host._tr(f"hotkeys.action.{action}"))
        for field in getattr(host, "hotkey_inputs", {}).values():
            field.setPlaceholderText(host._tr("hotkeys.capture_hint"))
        if getattr(host, "hotkeys_reset_button", None) is not None:
            host.hotkeys_reset_button.setText(host._tr("hotkeys.reset"))
        self.refresh_lock()
