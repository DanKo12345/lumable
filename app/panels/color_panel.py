from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel

from app.constants import ACTION_SPACING, SLIDER_LABEL_WIDTH, SLIDER_ROW_MARGINS, SLIDER_ROW_SPACING
from app.panels.types import PanelHost
from app.widgets import AccentPreview, ColorSwatch, GlassCard


def build_color_section(host: PanelHost) -> GlassCard:
    host.color_card = host._card(host._tr("color.title"), host._tr("color.subtitle"), icon="color")
    host.color_card.setMinimumHeight(468)
    host.preview = AccentPreview()
    host.color_card.content_layout.addWidget(host.preview)

    host.red_slider = host._slider("red")
    host.green_slider = host._slider("green")
    host.blue_slider = host._slider("blue")
    host.red_slider.setRange(0, 255)
    host.green_slider.setRange(0, 255)
    host.blue_slider.setRange(0, 255)
    host.brightness_slider = host._slider("white")
    host.brightness_slider.setRange(0, 100)
    host.red_value = host._pill("0")
    host.green_value = host._pill("0")
    host.blue_value = host._pill("0")
    host.brightness_value = host._pill("100%")
    host.color_card.content_layout.addLayout(
        host._slider_row(host._tr("slider.red"), host.red_slider, host.red_value, "slider.red")
    )
    host.color_card.content_layout.addLayout(
        host._slider_row(host._tr("slider.green"), host.green_slider, host.green_value, "slider.green")
    )
    host.color_card.content_layout.addLayout(
        host._slider_row(host._tr("slider.blue"), host.blue_slider, host.blue_value, "slider.blue")
    )
    host.color_card.content_layout.addLayout(
        host._slider_row(host._tr("slider.brightness"), host.brightness_slider, host.brightness_value, "slider.brightness")
    )

    history_row = QHBoxLayout()
    history_row.setSpacing(SLIDER_ROW_SPACING)
    history_row.setContentsMargins(*SLIDER_ROW_MARGINS)
    host.color_history_label = QLabel(host._tr("color.recent"))
    host.color_history_label.setObjectName("sliderLabel")
    host.color_history_label.setFixedWidth(SLIDER_LABEL_WIDTH)
    host.color_history_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    history_row.addWidget(host.color_history_label)
    host.color_history_buttons = []
    for _index in range(12):
        swatch = ColorSwatch(lambda: host._theme_tokens)
        swatch.setFixedHeight(host._control_height - 4)
        swatch.hide()
        host.color_history_buttons.append(swatch)
        history_row.addWidget(swatch)
    history_row.addStretch(1)
    host.color_card.content_layout.addLayout(history_row)

    color_actions = QHBoxLayout()
    color_actions.setSpacing(ACTION_SPACING)
    host.pick_color_button = host._button(host._tr("color.pick"), "ghost")
    host.power_button = host._button(host._tr("color.power_on"), "ghost")
    host.power_button.setCheckable(True)
    color_actions.addWidget(host.pick_color_button, 1)
    color_actions.addWidget(host.power_button, 1)
    host.color_card.content_layout.addLayout(color_actions)
    return host.color_card
