from __future__ import annotations

from PySide6.QtWidgets import QGraphicsOpacityEffect

from app.hotkeys import (
    ACTIONS,
    DEFAULT_HOTKEYS,
    SUGGESTED_HOTKEYS,
    parse_hotkey,
    resolve_binding,
)
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
            # A typing mistake should clear the moment it is corrected, without
            # waiting for a save that would not happen anyway.
            field.textChanged.connect(lambda _text: self.note_typing())
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
                field.setText(resolve_binding(bindings, action))
        self._sync_toggle_text()
        self._apply_enabled_state()
        self.refresh_errors()

    def _collect_bindings(self) -> tuple[dict[str, str], list[str]]:
        """What the fields say, plus the actions whose text will not parse.

        An unparseable field keeps whatever was last saved for that action —
        never the default. Substituting the default would hand back a global
        combination the user had deliberately changed or cleared, and it would
        do it as a side effect of a typo.
        """
        host = self._host
        saved = self._config().get("bindings", {})
        saved = saved if isinstance(saved, dict) else {}
        bindings: dict[str, str] = {}
        invalid: list[str] = []
        for action in ACTIONS:
            field = host.hotkey_inputs.get(action)
            spec = field.text().strip() if field is not None else ""
            if not spec:
                # Deliberately unassigned: saved as empty and unregistered.
                bindings[action] = ""
            elif parse_hotkey(spec) is not None:
                bindings[action] = spec
            else:
                invalid.append(action)
                bindings[action] = resolve_binding(saved, action)
        return bindings, invalid

    def _persist(self, *_args: object) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        bindings, invalid = self._collect_bindings()
        if invalid:
            # Nothing saved, nothing re-registered. Applying the rest would take
            # a working combination away from one action because of a typo in
            # another — the form is either right or it waits.
            self.refresh_errors()
            return
        host._settings["hotkeys"] = {
            "enabled": bool(host.hotkeys_toggle_button.isChecked()),
            "bindings": bindings,
        }
        for action, field in host.hotkey_inputs.items():
            if field.text().strip() != bindings[action]:
                field.setText(bindings[action])
        save_settings(host._settings)
        host._apply_hotkeys()
        self.refresh_errors()

    def refresh_errors(self) -> None:
        """Two failures that need different instructions, shown per field.

        A spec that will not parse is a typing problem: the user is told what a
        combination looks like. A spec that parses but that Windows refused is
        not the user's mistake at all — the combination is correct and something
        else already holds it, so the message names it and says so. Folding the
        two into one message would tell half the users to fix something that is
        not broken.
        """
        host = self._host
        refused = {}
        controller = getattr(host, "_hotkey_controller", None)
        if controller is not None and hasattr(controller, "failed_bindings"):
            refused = controller.failed_bindings()
        for action, field in host.hotkey_inputs.items():
            label = host.hotkey_error_labels.get(action) if hasattr(host, "hotkey_error_labels") else None
            if label is None:
                continue
            typed = field.text().strip()
            if typed and parse_hotkey(typed) is None:
                message = host._tr(
                    "hotkeys.error_invalid",
                    example=SUGGESTED_HOTKEYS.get(action) or "Ctrl+Alt+S",
                )
            elif action in refused:
                message = host._tr("hotkeys.error_taken", combo=refused[action])
            else:
                message = ""
            label.setText(message)
            label.setVisible(bool(message))
            field.setProperty("state", "error" if message else "")
            field.style().unpolish(field)
            field.style().polish(field)
            # The reader needs to know which action is complaining, not just
            # that something on the page is red.
            action_name = host._tr(f"hotkeys.action.{action}")
            field.setAccessibleDescription(f"{action_name}: {message}" if message else action_name)

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

    def note_typing(self) -> None:
        """Called as the field changes: a typing mistake clears as soon as it is
        corrected. A refused registration does not — that one only goes away
        when the system accepts the combination, and typing has not asked it
        anything yet."""
        self.refresh_errors()

    def relocalize(self) -> None:
        host = self._host
        self._sync_toggle_text()
        for action, label in getattr(host, "hotkey_action_labels", {}).items():
            label.setText(host._tr(f"hotkeys.action.{action}"))
        for action, field in getattr(host, "hotkey_inputs", {}).items():
            # A suggestion stays a suggestion in every language: it is shown the
            # way a placeholder is shown, and never becomes the saved value.
            field.setPlaceholderText(
                SUGGESTED_HOTKEYS.get(action) or host._tr("hotkeys.capture_hint")
            )
        if getattr(host, "hotkeys_reset_button", None) is not None:
            host.hotkeys_reset_button.setText(host._tr("hotkeys.reset"))
        self.refresh_lock()
