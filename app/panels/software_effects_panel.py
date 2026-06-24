from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout

from app.panels.types import PanelHost
from app.software_effects import EFFECT_KEYS
from app.widgets import GlassCard, StaticPopupComboBox
from app.widgets.ambient_preview import AmbientPreview


def build_software_effects_section(host: PanelHost) -> GlassCard:
    host.software_fx_card = host._card(
        host._tr("software_fx.title"), host._tr("software_fx.subtitle"), icon="effects"
    )
    host.software_fx_card.setMinimumHeight(host._sz(190))

    row = QHBoxLayout()
    row.setSpacing(10)
    row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.software_fx_toggle = host._button(host._tr("software_fx.toggle_off"), "ghost")
    host.software_fx_toggle.setCheckable(True)
    host.software_fx_toggle.setFixedSize(host._sz(104), host._sz(42))

    host.software_fx_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.software_fx_combo.setMinimumHeight(host._control_height)
    host.software_fx_combo.setMinimumWidth(host._sz(170))
    for key in EFFECT_KEYS:
        host.software_fx_combo.addItem(host._tr(f"software_fx.effect_{key}"), key)

    row.addWidget(host.software_fx_toggle)
    row.addWidget(host.software_fx_combo)
    row.addStretch(1)
    host.software_fx_card.content_layout.addLayout(row)

    # Live swatch of the colour currently streamed; only shown while running.
    host.software_fx_preview = AmbientPreview()
    host.software_fx_preview.setVisible(False)
    host.software_fx_card.content_layout.addWidget(host.software_fx_preview)

    host.software_fx_speed_slider = host._slider("red")
    host.software_fx_speed_slider.setRange(0, 100)
    host.software_fx_speed_value = host._pill("30%")
    host.software_fx_card.content_layout.addLayout(
        host._slider_row(
            host._tr("software_fx.speed"),
            host.software_fx_speed_slider,
            host.software_fx_speed_value,
            "software_fx.speed",
        )
    )
    return host.software_fx_card
