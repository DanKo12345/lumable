from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.panels.types import PanelHost
from app.widgets import GlassCard, StaticPopupComboBox


def build_app_triggers_section(host: PanelHost) -> GlassCard:
    host.app_triggers_card = host._card(
        host._tr("app_triggers.title"), host._tr("app_triggers.subtitle"), icon="schedule"
    )
    host.app_triggers_card.setMinimumHeight(host._sz(180))

    # Top row: master toggle on the left, the default scene to its right.
    top = QHBoxLayout()
    top.setSpacing(12)
    top.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.app_triggers_toggle_button = host._button(host._tr("app_triggers.toggle_off"), "ghost")
    host.app_triggers_toggle_button.setCheckable(True)
    host.app_triggers_toggle_button.setFixedSize(host._sz(86), host._sz(42))
    top.addWidget(host.app_triggers_toggle_button, 0, Qt.AlignVCenter)
    top.addSpacing(host._sz(12))
    host.app_triggers_default_label = QLabel(host._tr("app_triggers.default_label"))
    host.app_triggers_default_label.setObjectName("cardSubtitle")
    top.addWidget(host.app_triggers_default_label, 0, Qt.AlignVCenter)
    host.app_triggers_default_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.app_triggers_default_combo.setFixedHeight(host._control_height)
    host.app_triggers_default_combo.setMinimumWidth(host._sz(160))
    top.addWidget(host.app_triggers_default_combo, 0, Qt.AlignVCenter)
    top.addStretch(1)
    host.app_triggers_card.content_layout.addLayout(top)

    # Everything below the toggle dims/disables while the feature is off.
    host.app_triggers_controls = QWidget()
    controls = QVBoxLayout(host.app_triggers_controls)
    controls.setContentsMargins(0, host._sz(8), 0, 0)
    controls.setSpacing(host._sz(8))

    # Onboarding hint shown while there are no rules yet (keeps the card from
    # looking empty and explains the feature with an example).
    host.app_triggers_empty_hint = QLabel(host._tr("app_triggers.empty_hint"))
    host.app_triggers_empty_hint.setObjectName("cardSubtitle")
    host.app_triggers_empty_hint.setWordWrap(True)
    controls.addWidget(host.app_triggers_empty_hint)

    host.app_triggers_rules_container = QWidget()
    host.app_triggers_rules_layout = QVBoxLayout(host.app_triggers_rules_container)
    host.app_triggers_rules_layout.setContentsMargins(0, 0, 0, 0)
    host.app_triggers_rules_layout.setSpacing(host._sz(6))
    controls.addWidget(host.app_triggers_rules_container)
    host.app_triggers_add_button = host._button(host._tr("app_triggers.add_rule"), "ghost")
    add_row = QHBoxLayout()
    add_row.addWidget(host.app_triggers_add_button)
    add_row.addStretch(1)
    controls.addLayout(add_row)
    host.app_triggers_card.content_layout.addWidget(host.app_triggers_controls)
    return host.app_triggers_card
