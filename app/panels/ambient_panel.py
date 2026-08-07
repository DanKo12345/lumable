from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel

from app.capture_regions import REGION_IDS
from app.panels.card_header import add_pro_badge
from app.panels.list_rows import divider, list_container, list_row
from app.panels.types import PanelHost
from app.screen_profiles import PROFILE_IDS
from app.widgets import GlassCard, StaticPopupComboBox
from app.widgets.ambient_preview import AmbientPreview
from app.widgets.capture_area_selector import CaptureAreaSelector
from app.widgets.segmented_control import SegmentedControl

_SYNC_TINT = "#8fbfff"
_PROFILE_TINT = "#b6a3ff"


def build_ambient_section(host: PanelHost) -> GlassCard:
    host.ambient_card = host._card(host._tr("ambient.title"), host._tr("ambient.subtitle"), icon="monitor")
    host.ambient_card.setMinimumHeight(host._sz(196))

    # Pro badge shown when screen sync isn't unlocked (toggled by the controller).
    host.ambient_lock_label = add_pro_badge(host, host.ambient_card, "ambient.pro_locked")
    host.ambient_toggle_button = host._button(host._tr("ambient.toggle_off"), "ghost")
    host.ambient_toggle_button.setCheckable(True)
    host.ambient_toggle_button.setFixedSize(host._sz(104), host._sz(42))

    # The one choice that matters: which profile. Everything else is a nudge.
    host.ambient_profile_segment = SegmentedControl(
        [(pid, host._tr(f"ambient.profile.{pid}")) for pid in PROFILE_IDS]
    )

    # Match the newer cards: one grouped row owns the mode, another explains
    # how the selected profile changes the response. This avoids making "Game"
    # look like an app trigger that only works while a game is open.
    settings, settings_layout = list_container(host)
    mode_row, mode_layout, host.ambient_mode_title_label, host.ambient_status_label, _ = list_row(
        host, "power", _SYNC_TINT, host._tr("ambient.mode_title")
    )
    assert host.ambient_status_label is not None
    host.ambient_status_label.setText(host._tr("ambient.status_off"))
    mode_layout.addWidget(host.ambient_toggle_button, 0, Qt.AlignVCenter)
    settings_layout.addWidget(mode_row)
    settings_layout.addWidget(divider(host))

    profile_row, profile_layout, host.ambient_profile_title_label, host.ambient_profile_description, _ = list_row(
        host, "gauge", _PROFILE_TINT, host._tr("ambient.profile_title")
    )
    assert host.ambient_profile_description is not None
    host.ambient_profile_description.setText(host._tr("ambient.profile.desktop_desc"))
    profile_layout.addWidget(host.ambient_profile_segment, 0, Qt.AlignVCenter)
    settings_layout.addWidget(profile_row)
    host.ambient_card.content_layout.addWidget(settings)

    host.ambient_preview_label = QLabel(host._tr("ambient.preview_hint"))
    host.ambient_preview_label.setObjectName("sliderLabel")
    host.ambient_card.content_layout.addWidget(host.ambient_preview_label)
    host.ambient_preview = AmbientPreview()
    host.ambient_card.content_layout.addWidget(host.ambient_preview)

    # Two nudges on top of the profile — not a wall of filters.
    host.ambient_saturation_slider = host._slider("purple")
    host.ambient_saturation_slider.setRange(0, 100)
    host.ambient_saturation_value = host._pill("55%")
    host.ambient_card.content_layout.addLayout(
        host._slider_row(
            host._tr("ambient.intensity"),
            host.ambient_saturation_slider,
            host.ambient_saturation_value,
            "ambient.intensity",
        )
    )

    host.ambient_smoothing_slider = host._slider("blue")
    host.ambient_smoothing_slider.setRange(0, 100)
    host.ambient_smoothing_value = host._pill("65%")
    host.ambient_card.content_layout.addLayout(
        host._slider_row(
            host._tr("ambient.smoothness"),
            host.ambient_smoothing_slider,
            host.ambient_smoothing_value,
            "ambient.smoothness",
        )
    )

    # A dropdown reading "Full screen" explains nothing; the picture does. Kept
    # deliberately compact so the profile above stays the card's main choice.
    host.ambient_area_selector = CaptureAreaSelector(
        {region: host._tr(f"ambient.region.{region}") for region in REGION_IDS}
    )
    host.ambient_area_selector.set_texts(
        title=host._tr("ambient.area_title"),
        help_text=host._tr("ambient.area_help"),
        labels={region: host._tr(f"ambient.region.{region}") for region in REGION_IDS},
        tooltips={region: host._tr(f"ambient.region_tip.{region}") for region in REGION_IDS},
    )
    host.ambient_card.content_layout.addWidget(host.ambient_area_selector)

    # Secondary capture params kept below: the monitor, if there is a choice.
    extra = QHBoxLayout()
    extra.setSpacing(10)
    extra.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.ambient_monitor_combo = None
    screens = QGuiApplication.screens()
    if len(screens) > 1:
        monitor_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
        monitor_combo.setMinimumHeight(host._control_height)
        monitor_combo.setMinimumWidth(host._sz(168))
        for index, screen in enumerate(screens):
            geometry = screen.geometry()
            monitor_combo.addItem(f"{host._tr('ambient.monitor')} {index + 1} ({geometry.width()}×{geometry.height()})", index)
        host.ambient_monitor_combo = monitor_combo
        extra.addWidget(monitor_combo)
    extra.addStretch(1)
    host.ambient_card.content_layout.addLayout(extra)
    return host.ambient_card
