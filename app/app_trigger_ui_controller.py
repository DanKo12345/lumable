from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLineEdit, QWidget

from app.scene_presets import SCENE_PRESETS
from app.storage import save_settings
from app.widgets import StaticPopupComboBox
from app.widgets.themed_line_edit import ThemedLineEdit


class AppTriggerUiController:
    """Wires the 'auto-scenes by app' card: master toggle, a default scene, and a
    list of app -> scene rules. Pro-gated; the background watcher
    (AppTriggerController) reads the same persisted settings."""

    def __init__(self, host: Any) -> None:
        self._host = host
        self._rule_rows: list[tuple[QWidget, QLineEdit, StaticPopupComboBox]] = []
        self._controls_effect: QGraphicsOpacityEffect | None = None

    def wire(self) -> None:
        host = self._host
        host.app_triggers_toggle_button.clicked.connect(self._toggle)
        host.app_triggers_add_button.clicked.connect(self._add_rule)
        self._populate_default_combo()
        host.app_triggers_default_combo.currentIndexChanged.connect(self._on_default_changed)
        self.sync_controls()
        self.refresh_lock()

    # ── config helpers ────────────────────────────────────────────────
    def _config(self) -> dict:
        host = self._host
        config = host._settings.get("app_triggers", {}) if isinstance(host._settings, dict) else {}
        return config if isinstance(config, dict) else {}

    def _scene_options(self) -> list[tuple[str, str]]:
        host = self._host
        return [(preset.key, host._tr(f"scene.{preset.key}")) for preset in SCENE_PRESETS]

    def _populate_default_combo(self) -> None:
        host = self._host
        combo = host.app_triggers_default_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(host._tr("app_triggers.default_none"), "")
        for key, name in self._scene_options():
            combo.addItem(name, key)
        combo.blockSignals(False)

    def _new_scene_combo(self, selected: str) -> StaticPopupComboBox:
        host = self._host
        combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
        combo.setMinimumHeight(host._control_height)
        combo.setMinimumWidth(host._sz(140))
        for key, name in self._scene_options():
            combo.addItem(name, key)
        index = combo.findData(selected)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(self._persist)
        return combo

    # ── rows ──────────────────────────────────────────────────────────
    def _rebuild_rules(self, rules: list) -> None:
        host = self._host
        layout = host.app_triggers_rules_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rule_rows = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            self._append_row(str(rule.get("app", "")), str(rule.get("scene", "")))
        self._update_empty_hint()

    def _update_empty_hint(self) -> None:
        hint = getattr(self._host, "app_triggers_empty_hint", None)
        if hint is not None:
            hint.setVisible(not self._rule_rows)

    def _append_row(self, app: str, scene: str) -> None:
        host = self._host
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        app_input = ThemedLineEdit(app)
        app_input.setObjectName("licenseKeyInput")
        app_input.setPlaceholderText(host._tr("app_triggers.app_placeholder"))
        app_input.setMinimumHeight(host._control_height)
        app_input.editingFinished.connect(self._persist)
        combo = self._new_scene_combo(scene)
        remove = host._button(host._tr("app_triggers.remove_rule"), "ghost")
        remove.clicked.connect(lambda _checked=False, w=row: self._remove_row(w))
        row_layout.addWidget(app_input, 1)
        row_layout.addWidget(combo)
        row_layout.addWidget(remove)
        host.app_triggers_rules_layout.addWidget(row)
        self._rule_rows.append((row, app_input, combo))

    def _add_rule(self) -> None:
        default_scene = SCENE_PRESETS[0].key if SCENE_PRESETS else ""
        self._append_row("", default_scene)
        self._update_empty_hint()
        self._persist()

    def _remove_row(self, row: QWidget) -> None:
        self._rule_rows = [entry for entry in self._rule_rows if entry[0] is not row]
        row.deleteLater()
        self._update_empty_hint()
        self._persist()

    # ── persistence / state ───────────────────────────────────────────
    def _collect_rules(self) -> list[dict[str, str]]:
        rules: list[dict[str, str]] = []
        for _row, app_input, combo in self._rule_rows:
            app = app_input.text().strip()
            scene = str(combo.currentData() or "")
            if app and scene:
                rules.append({"app": app, "scene": scene})
        return rules

    def _persist(self, *_args: object) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        host._settings["app_triggers"] = {
            "enabled": bool(host.app_triggers_toggle_button.isChecked()),
            "default": str(host.app_triggers_default_combo.currentData() or ""),
            "rules": self._collect_rules(),
        }
        save_settings(host._settings)

    def _on_default_changed(self) -> None:
        self._persist()

    def _toggle(self) -> None:
        self._sync_toggle_text()
        self._persist()
        self._apply_enabled_state()

    def _sync_toggle_text(self) -> None:
        host = self._host
        on = host.app_triggers_toggle_button.isChecked()
        host.app_triggers_toggle_button.setText(
            host._tr("app_triggers.toggle_on") if on else host._tr("app_triggers.toggle_off")
        )
        host.app_triggers_toggle_button.set_role("accent_soft" if on else "ghost")

    def sync_controls(self) -> None:
        host = self._host
        config = self._config()
        with host._suppress_signals():
            host.app_triggers_toggle_button.setChecked(bool(config.get("enabled", False)))
            combo = host.app_triggers_default_combo
            index = combo.findData(str(config.get("default", "")))
            combo.setCurrentIndex(index if index >= 0 else 0)
        self._sync_toggle_text()
        rules = config.get("rules", [])
        self._rebuild_rules(rules if isinstance(rules, list) else [])
        self._apply_enabled_state()

    def relocalize(self) -> None:
        # Re-fill the default combo and rebuild rows so scene names follow the
        # new language, then restore selections + toggle text.
        self._populate_default_combo()
        hint = getattr(self._host, "app_triggers_empty_hint", None)
        if hint is not None:
            hint.setText(self._host._tr("app_triggers.empty_hint"))
        self.sync_controls()
        self.refresh_lock()

    def refresh_lock(self) -> None:
        # Feature is free now — nothing to lock. Kept so existing callers
        # (wire / relocalize / license changes) still drive the enabled state.
        self._apply_enabled_state()

    def _apply_enabled_state(self) -> None:
        host = self._host
        active = host.app_triggers_toggle_button.isChecked()
        controls = getattr(host, "app_triggers_controls", None)
        if controls is None:
            return
        controls.setEnabled(active)
        if self._controls_effect is None:
            self._controls_effect = QGraphicsOpacityEffect(controls)
            controls.setGraphicsEffect(self._controls_effect)
        self._controls_effect.setOpacity(1.0 if active else 0.4)
