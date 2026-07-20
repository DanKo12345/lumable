from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.panels.list_rows import BTN_H, BTN_W, divider, list_container, list_row, plain_row
from app.panels.types import PanelHost
from app.widgets import GlassCard, StaticPopupComboBox


def build_app_triggers_section(host: PanelHost) -> GlassCard:
    host.app_triggers_card = host._card(
        host._tr("app_triggers.title"), host._tr("app_triggers.subtitle"), icon="app-window"
    )

    settings_list, settings_layout = list_container(host)
    master_row, master_controls, _, _, _ = list_row(
        host, "app-window", "#78a7ff", host._tr("app_triggers.title"), with_status=False
    )
    host.app_triggers_toggle_button = host._button(host._tr("app_triggers.toggle_off"), "ghost")
    host.app_triggers_toggle_button.setCheckable(True)
    host.app_triggers_toggle_button.setFixedSize(host._sz(BTN_W), host._sz(BTN_H))
    master_controls.addWidget(host.app_triggers_toggle_button, 0, Qt.AlignVCenter)
    settings_layout.addWidget(master_row)
    settings_layout.addWidget(divider(host))

    default_row, default_controls, host.app_triggers_default_label = plain_row(
        host, host._tr("app_triggers.default_label")
    )
    host.app_triggers_default_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.app_triggers_default_combo.setFixedHeight(host._control_height)
    host.app_triggers_default_combo.setFixedWidth(host._sz(220))
    default_controls.addWidget(host.app_triggers_default_combo, 0, Qt.AlignVCenter)
    settings_layout.addWidget(default_row)
    host.app_triggers_card.content_layout.addWidget(settings_list)

    # Everything below the toggle dims/disables while the feature is off.
    host.app_triggers_controls = QWidget()
    controls = QVBoxLayout(host.app_triggers_controls)
    controls.setContentsMargins(0, host._sz(12), 0, 0)
    controls.setSpacing(host._sz(10))

    # Onboarding hint shown while there are no rules yet (keeps the card from
    # looking empty and explains the feature with an example).
    host.app_triggers_empty_hint = QLabel(host._tr("app_triggers.empty_hint"))
    host.app_triggers_empty_hint.setObjectName("cardSubtitle")
    host.app_triggers_empty_hint.setWordWrap(True)

    rules_surface = QWidget()
    rules_surface.setObjectName("settingsList")
    rules_layout = QVBoxLayout(rules_surface)
    rules_layout.setContentsMargins(host._sz(16), host._sz(14), host._sz(16), host._sz(14))
    rules_layout.setSpacing(host._sz(10))
    rules_layout.addWidget(host.app_triggers_empty_hint)

    host.app_triggers_rules_container = QWidget()
    host.app_triggers_rules_layout = QVBoxLayout(host.app_triggers_rules_container)
    host.app_triggers_rules_layout.setContentsMargins(0, 0, 0, 0)
    host.app_triggers_rules_layout.setSpacing(host._sz(6))
    rules_layout.addWidget(host.app_triggers_rules_container)
    host.app_triggers_add_button = host._button(host._tr("app_triggers.add_rule"), "accent_soft")
    add_row = QHBoxLayout()
    add_row.addStretch(1)
    add_row.addWidget(host.app_triggers_add_button)
    rules_layout.addLayout(add_row)
    controls.addWidget(rules_surface)
    host.app_triggers_card.content_layout.addWidget(host.app_triggers_controls)
    return host.app_triggers_card
