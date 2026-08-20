from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

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


def _build_fusion_tune_row(host: PanelHost):
    """The combined mode's settings, unadorned and hidden until asked for.

    Deliberately not a card and not a permanent row: these are set once and then
    left alone. The controls here are *views* of the music card's values, not a
    second set — one slider, one saved number, one handler. A copy would drift,
    and the first person to notice would be someone whose beat behaved
    differently depending on which screen they had set it from.
    """
    host.fusion_tune_row = QWidget()
    host.fusion_tune_row.setObjectName("fusionTuneRow")
    layout = QHBoxLayout(host.fusion_tune_row)
    layout.setContentsMargins(host._sz(52), host._sz(2), host._sz(14), host._sz(8))
    layout.setSpacing(host._sz(10))

    host.fusion_source_segment = SegmentedControl([
        ("system", host._tr("music.source_system")),
        ("mic", host._tr("music.source_mic")),
    ])
    host.fusion_source_segment.set_metrics(pad=host._sz(10))
    host.fusion_source_segment.setAccessibleName(host._tr("music.source_title"))

    host.fusion_beat_label = QLabel(host._tr("music.beat"))
    host.fusion_beat_label.setObjectName("sliderLabel")
    host.fusion_beat_slider = host._slider("green")
    host.fusion_beat_slider.setRange(0, 100)
    host.fusion_beat_slider.setAccessibleName(host._tr("music.beat"))
    host.fusion_beat_value = host._pill("40%")

    layout.addWidget(host.fusion_source_segment, 0, Qt.AlignVCenter)
    layout.addSpacing(host._sz(6))
    layout.addWidget(host.fusion_beat_label, 0, Qt.AlignVCenter)
    layout.addWidget(host.fusion_beat_slider, 1)
    layout.addWidget(host.fusion_beat_value, 0, Qt.AlignVCenter)

    host.fusion_tune_row.setVisible(False)
    return host.fusion_tune_row


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
    # One row for the whole decision, and three separate things inside it: what
    # the strip follows, and whether the capture is running. Kept apart on
    # purpose — a single `Off | Screen | Screen + music` control would look
    # tidier and would destroy the distinction the release is built on, where a
    # mode stays chosen while the output is switched off.
    host.fusion_mode_segment = SegmentedControl(
        [(key, host._tr(f"fusion.mode.{key}")) for key in ("screen", "screen_music")]
    )
    # Tighter than the default: this row also carries a title, a status line and
    # the power button, and "Captura de pantalla · Pantalla + música" is a good
    # deal wider than the English it was laid out against. Measured at 860 wide
    # in all four languages — see tools/measure_mode_row.py.
    host.fusion_mode_segment.set_metrics(pad=9)
    mode_row, mode_layout, host.ambient_mode_title_label, host.ambient_status_label, _ = list_row(
        host, "monitor", _SYNC_TINT, host._tr("ambient.mode_title")
    )
    assert host.ambient_status_label is not None
    host.ambient_status_label.setText(host._tr("ambient.status_off"))
    # The combined mode's own settings, one press away instead of one tab away.
    # A mode chosen here whose main dial lives on another card asks the user to
    # know how the app is built; a whole extra row on the card costs height
    # every day for something set once. Collapsed by default, so neither the
    # card nor the guided tour changes size until it is asked for.
    host.fusion_tune_button = host._button("", "ghost")
    host.fusion_tune_button.set_icon_kind("sliders-horizontal")
    host.fusion_tune_button.setIconSize(QSize(host._sz(16), host._sz(16)))
    host.fusion_tune_button.setCheckable(True)
    host.fusion_tune_button.setFixedSize(host._sz(32), host._sz(34))
    host.fusion_tune_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    host.fusion_tune_button.setAccessibleName(host._tr("fusion.tune"))
    host.fusion_tune_button.setToolTip(host._tr("fusion.tune"))

    # Mode first, then power: the choice describes what would run, the button
    # says whether it is running.
    mode_layout.addWidget(host.fusion_mode_segment, 0, Qt.AlignVCenter)
    mode_layout.addWidget(host.fusion_tune_button, 0, Qt.AlignVCenter)
    mode_layout.addWidget(host.ambient_toggle_button, 0, Qt.AlignVCenter)
    settings_layout.addWidget(mode_row)
    settings_layout.addWidget(_build_fusion_tune_row(host))
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
