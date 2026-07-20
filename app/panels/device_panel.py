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
    host.scan_button = host._button(host._tr("device.find"), "accent")
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

    # ── Main strip ────────────────────────────────────────────────────
    # Discovery stays above. The actual controller gets a compact, self-contained
    # row so its name and actions read as one unit instead of floating apart.
    host.primary_strip_row = QWidget()
    host.primary_strip_row.setObjectName("deviceStripRow")
    primary_layout = QHBoxLayout(host.primary_strip_row)
    primary_layout.setContentsMargins(host._sz(14), host._sz(10), host._sz(12), host._sz(10))
    primary_layout.setSpacing(ROW_SPACING_TIGHT)

    primary_info = QVBoxLayout()
    primary_info.setSpacing(host._sz(2))
    host.device_primary_heading = QLabel(host._tr("device.primary_section"))
    host.device_primary_heading.setObjectName("deviceStripTitle")
    host.device_primary_meta = QLabel(host._tr("device.primary_empty"))
    host.device_primary_meta.setObjectName("deviceStripMeta")
    primary_info.addWidget(host.device_primary_heading)
    primary_info.addWidget(host.device_primary_meta)

    # device_status now lives in the persistent top region.
    host.connect_button = host._button(host._tr("device.connect"), "accent_soft")
    host.disconnect_button = host._button(host._tr("device.disconnect"), "ghost")
    # Naming the main strip belongs with the main strip's actions — keeping it
    # next to the mirror list made two identical "Rename" buttons ambiguous.
    host.rename_device_button = host._button(host._tr("device.rename_primary"), "ghost")
    host.rename_device_button.setVisible(False)
    host.logs_toggle_button = host._button(host._tr("device.show_logs"), "ghost")
    for button in (
        host.connect_button,
        host.disconnect_button,
        host.rename_device_button,
        host.logs_toggle_button,
    ):
        button.setMinimumWidth(DEVICE_ACTION_MIN_WIDTH)
    primary_layout.addLayout(primary_info, 1)
    primary_layout.addWidget(host.connect_button)
    primary_layout.addWidget(host.disconnect_button)
    primary_layout.addWidget(host.rename_device_button)
    primary_layout.addWidget(host.logs_toggle_button)
    host.device_card.content_layout.addWidget(host.primary_strip_row)

    # ── Extra strips ──────────────────────────────────────────────────
    # "Add strip" now sits with the list it adds to, so it reads as one idea.
    mirrors_row = QHBoxLayout()
    mirrors_row.setSpacing(ROW_SPACING_TIGHT)
    mirrors_row.setContentsMargins(0, host._sz(10), 0, 0)
    host.device_mirrors_heading = QLabel(host._tr("device.mirrors_section"))
    host.device_mirrors_heading.setObjectName("deviceSectionLabel")
    host.add_mirror_button = host._button(host._tr("device.add_mirror"), "ghost")
    host.add_mirror_button.setMinimumWidth(DEVICE_ACTION_MIN_WIDTH)
    host.add_mirror_button.setEnabled(False)
    mirrors_row.addWidget(host.device_mirrors_heading, 0, Qt.AlignVCenter)
    mirrors_row.addStretch(1)
    mirrors_row.addWidget(host.add_mirror_button)
    host.device_card.content_layout.addLayout(mirrors_row)

    # Says what the empty list means and how to fill it, instead of nothing.
    host.mirror_empty_label = QLabel(host._tr("device.mirrors_empty"))
    host.mirror_empty_label.setObjectName("lastDeviceHint")
    host.mirror_empty_label.setWordWrap(True)
    host.device_card.content_layout.addWidget(host.mirror_empty_label)

    # List of mirror controllers (each row: name + Rename + Remove). Built on
    # demand by the event handler from BleController.mirrors_changed.
    host.mirror_list_container = QWidget()
    host.mirror_list_layout = QVBoxLayout(host.mirror_list_container)
    host.mirror_list_layout.setContentsMargins(0, host._sz(6), 0, 0)
    host.mirror_list_layout.setSpacing(host._sz(4))
    host.mirror_list_container.setVisible(False)
    host.device_card.content_layout.addWidget(host.mirror_list_container)

    # A quiet, always-available link to the in-app catalog of supported
    # controller families (opens About). Last, so it never crowds the actions.
    catalog_row = QHBoxLayout()
    catalog_row.setContentsMargins(0, host._sz(10), 0, 0)
    catalog_row.setSpacing(ROW_SPACING_TIGHT)
    host.supported_controllers_button = host._button(host._tr("device.supported"), "ghost")
    host.supported_controllers_button.setMinimumWidth(DEVICE_ACTION_MIN_WIDTH)
    catalog_row.addWidget(host.supported_controllers_button)
    catalog_row.addStretch(1)
    host.device_card.content_layout.addLayout(catalog_row)
    return host.device_card
