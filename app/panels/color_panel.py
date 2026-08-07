from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.panels.list_rows import Hairline
from app.panels.types import PanelHost
from app.widgets import ColorSwatch, GlassCard


def build_color_section(host: PanelHost) -> GlassCard:
    host.color_card = host._card(host._tr("color.title"), host._tr("color.subtitle"), icon="color")
    host.color_card.setMinimumHeight(host._sz(360))
    host.color_card.subtitle_label.setMinimumHeight(0)
    host.color_card.subtitle_label.setContentsMargins(0, 0, 0, 0)
    host.color_card.content_layout.setContentsMargins(0, host._sz(8), 0, 0)
    host.color_card.content_layout.setSpacing(host._sz(12))
    # The live-light preview now lives in the persistent top region.

    # Create the colour sliders + value chips (added below the recent row).
    host.red_slider = host._slider("red")
    host.green_slider = host._slider("green")
    host.blue_slider = host._slider("blue")
    host.red_slider.setRange(0, 255)
    host.green_slider.setRange(0, 255)
    host.blue_slider.setRange(0, 255)
    host.brightness_slider = host._slider("white")
    host.brightness_slider.setRange(0, 100)
    # Colour temperature: warm↔cool white emulated via RGB (no white channel on
    # cheap controllers). Range 2000K (warm) → 6500K (cool daylight).
    host.temperature_slider = host._slider("white")
    host.temperature_slider.setRange(2000, 6500)
    host.temperature_slider.setValue(4500)
    host.temperature_slider.set_track_gradient(
        [(0.0, (255, 176, 102)), (0.5, (251, 239, 224)), (1.0, (159, 196, 255))]
    )
    host.red_value = host._pill("0")
    host.green_value = host._pill("0")
    host.blue_value = host._pill("0")
    host.brightness_value = host._pill("100%")
    host.temperature_value = host._pill("4500K")

    # Recent colours first — quick one-tap re-pick (fast on top, fine-tune below).
    quick_section, quick_layout, _quick_heading = _section(host)
    quick_section.setObjectName("colorQuickSection")
    history_header = QHBoxLayout()
    history_header.setContentsMargins(0, 0, 0, 0)
    history_header.setSpacing(host._sz(8))
    host.color_history_label = QLabel(host._tr("color.recent"))
    host.color_history_label.setObjectName("sceneFormHeading")
    host.color_history_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    history_header.addWidget(host.color_history_label)
    history_header.addStretch(1)
    host.pick_color_button = host._button(host._tr("color.pick"), "accent_soft")
    host.pick_color_button.set_icon_kind("color")
    host.pick_color_button.setMinimumWidth(host._sz(156))
    history_header.addWidget(host.pick_color_button, 0, Qt.AlignVCenter)
    quick_layout.addLayout(history_header)

    history_row = QHBoxLayout()
    history_row.setSpacing(host._sz(8))
    history_row.setContentsMargins(0, 0, 0, 0)
    host.color_history_buttons = []
    for _index in range(12):
        swatch = ColorSwatch(lambda: host._theme_tokens)
        swatch_size = host._control_height - 8
        swatch.setFixedSize(swatch_size, swatch_size)  # square → perfectly round
        swatch.hide()
        host.color_history_buttons.append(swatch)
        history_row.addWidget(swatch)
    history_row.addStretch(1)
    quick_layout.addLayout(history_row)
    host.color_card.content_layout.addWidget(quick_section)
    host.color_card.content_layout.addWidget(Hairline())

    # Sliders below — precise manual control.
    channels, channels_layout, host.color_channels_label = _section(host, host._tr("color.channels"))
    channels.setObjectName("colorChannelsSection")
    channels_layout.addLayout(
        host._slider_row(host._tr("slider.red"), host.red_slider, host.red_value, "slider.red")
    )
    channels_layout.addLayout(
        host._slider_row(host._tr("slider.green"), host.green_slider, host.green_value, "slider.green")
    )
    channels_layout.addLayout(
        host._slider_row(host._tr("slider.blue"), host.blue_slider, host.blue_value, "slider.blue")
    )
    host.color_card.content_layout.addWidget(channels)
    host.color_card.content_layout.addWidget(Hairline())

    light, light_layout, host.color_light_label = _section(host, host._tr("color.light"))
    light.setObjectName("colorLightSection")
    light_layout.addLayout(
        host._slider_row(host._tr("slider.brightness"), host.brightness_slider, host.brightness_value, "slider.brightness")
    )
    light_layout.addLayout(
        host._slider_row(host._tr("slider.temperature"), host.temperature_slider, host.temperature_value, "slider.temperature")
    )
    host.color_card.content_layout.addWidget(light)
    return host.color_card


def _section(host: PanelHost, title: str | None = None) -> tuple[QWidget, QVBoxLayout, QLabel | None]:
    section = QWidget()
    section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    layout = QVBoxLayout(section)
    layout.setContentsMargins(host._sz(2), host._sz(2), host._sz(2), host._sz(2))
    layout.setSpacing(host._sz(8))
    heading = None
    if title is not None:
        heading = QLabel(title)
        heading.setObjectName("sceneFormHeading")
        layout.addWidget(heading)
    return section, layout, heading
