from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.constants import (
    DEVICE_ACTION_MIN_WIDTH,
    DEVICE_CONTENT_TOP_MARGIN,
    ROW_SPACING,
    ROW_SPACING_TIGHT,
    ROW_TOP_MARGIN,
    SCAN_BUTTON_MIN_WIDTH,
)
from app.panels.types import PanelHost
from app.widgets import GlassCard, StaticPopupComboBox


def build_device_section(host: PanelHost) -> GlassCard:
    host.device_card = host._card(host._tr("device.title"), host._tr("device.subtitle"), icon="device")
    host.device_card.setMinimumHeight(host._sz(162))
    host.device_card.content_layout.setContentsMargins(0, DEVICE_CONTENT_TOP_MARGIN, 0, 0)

    row = QHBoxLayout()
    row.setSpacing(ROW_SPACING)
    row.setContentsMargins(0, ROW_TOP_MARGIN, 0, 0)
    host.device_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.device_combo.setMinimumHeight(host._control_height)
    host.scan_button = host._button(host._tr("device.find"), "accent_soft")
    host.scan_button.setMinimumWidth(SCAN_BUTTON_MIN_WIDTH)
    row.addWidget(host.device_combo, 1)
    row.addWidget(host.scan_button)
    host.device_card.content_layout.addLayout(row)

    host.last_device_label = QLabel("")
    host.last_device_label.setObjectName("lastDeviceHint")
    host.last_device_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.last_device_label.setMinimumHeight(22)
    host.last_device_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    host.device_card.content_layout.addWidget(host.last_device_label)

    host.device_onboarding_label = QLabel(host._tr("device.onboarding_hint"))
    host.device_onboarding_label.setObjectName("deviceOnboardingHint")
    host.device_onboarding_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.device_onboarding_label.setWordWrap(True)
    host.device_onboarding_label.setMinimumHeight(24)
    host.device_card.content_layout.addWidget(host.device_onboarding_label)

    row2 = QHBoxLayout()
    row2.setSpacing(ROW_SPACING_TIGHT)
    row2.setContentsMargins(0, ROW_TOP_MARGIN, 0, 0)
    # device_status now lives in the persistent top region.
    host.connect_button = host._button(host._tr("device.connect"), "ghost")
    host.disconnect_button = host._button(host._tr("device.disconnect"), "ghost")
    # Multi-device: add the controller selected in the list as a mirror of the
    # primary (all mirrored strips show the same thing). Enabled once connected.
    host.add_mirror_button = host._button(host._tr("device.add_mirror"), "ghost")
    host.add_mirror_button.setEnabled(False)
    host.logs_toggle_button = host._button(host._tr("device.show_logs"), "ghost")
    for button in (host.connect_button, host.disconnect_button, host.add_mirror_button, host.logs_toggle_button):
        button.setMinimumWidth(DEVICE_ACTION_MIN_WIDTH)
    row2.addStretch(1)
    row2.addWidget(host.connect_button)
    row2.addWidget(host.disconnect_button)
    row2.addWidget(host.add_mirror_button)
    row2.addWidget(host.logs_toggle_button)
    host.device_card.content_layout.addLayout(row2)

    # List of mirror controllers (each row: name + Remove). Built on demand by
    # the event handler from BleController.mirrors_changed; hidden when empty.
    host.mirror_list_container = QWidget()
    host.mirror_list_layout = QVBoxLayout(host.mirror_list_container)
    host.mirror_list_layout.setContentsMargins(0, host._sz(6), 0, 0)
    host.mirror_list_layout.setSpacing(host._sz(4))
    host.mirror_list_container.setVisible(False)
    host.device_card.content_layout.addWidget(host.mirror_list_container)
    return host.device_card
