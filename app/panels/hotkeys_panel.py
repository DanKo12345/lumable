from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.hotkeys import ACTIONS
from app.panels.types import PanelHost
from app.widgets import GlassCard
from app.widgets.hotkey_capture_edit import HotkeyCaptureEdit


def build_hotkeys_section(host: PanelHost) -> GlassCard:
    host.hotkeys_card = host._card(
        host._tr("hotkeys.title"), host._tr("hotkeys.subtitle"), icon="keyboard"
    )
    host.hotkeys_card.setMinimumHeight(host._sz(250))

    top = QHBoxLayout()
    top.setSpacing(10)
    top.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.hotkeys_toggle_button = host._button(host._tr("hotkeys.toggle_off"), "ghost")
    host.hotkeys_toggle_button.setCheckable(True)
    host.hotkeys_toggle_button.setFixedSize(host._sz(86), host._sz(42))
    top.addWidget(host.hotkeys_toggle_button)
    top.addStretch(1)
    host.hotkeys_card.content_layout.addLayout(top)

    # One editable spec field per action; dims/disables while the feature is off.
    host.hotkeys_controls = QWidget()
    controls = QVBoxLayout(host.hotkeys_controls)
    controls.setContentsMargins(0, host._sz(8), 0, 0)
    controls.setSpacing(host._sz(6))
    host.hotkey_inputs = {}
    host.hotkey_action_labels = {}
    for action in ACTIONS:
        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel(host._tr(f"hotkeys.action.{action}"))
        label.setObjectName("sliderLabel")
        label.setMinimumWidth(host._sz(160))
        field = HotkeyCaptureEdit()
        field.setObjectName("licenseKeyInput")
        field.setMinimumHeight(host._control_height)
        field.setPlaceholderText(host._tr("hotkeys.capture_hint"))
        host.hotkey_inputs[action] = field
        host.hotkey_action_labels[action] = label
        row.addWidget(label)
        row.addWidget(field, 1)
        controls.addLayout(row)

    reset_row = QHBoxLayout()
    host.hotkeys_reset_button = host._button(host._tr("hotkeys.reset"), "ghost")
    reset_row.addWidget(host.hotkeys_reset_button)
    reset_row.addStretch(1)
    controls.addLayout(reset_row)

    host.hotkeys_card.content_layout.addWidget(host.hotkeys_controls)
    return host.hotkeys_card
