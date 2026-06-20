from __future__ import annotations

from PySide6.QtCore import QSize

from app.ble import EFFECTS
from app.constants import EFFECTS_CONTENT_TOP_MARGIN
from app.localization import localization_manager
from app.panels.types import PanelHost
from app.widgets import EffectPreviewStrip, GlassCard, StaticPopupComboBox


def build_effects_section(host: PanelHost) -> GlassCard:
    host.effects_card = host._card(host._tr("effects.title"), host._tr("effects.subtitle"), icon="effects")
    host.effects_card.setMinimumHeight(host._sz(260))
    host.effects_card.content_layout.setContentsMargins(0, EFFECTS_CONTENT_TOP_MARGIN, 0, 0)
    host.effect_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.effect_combo.setMinimumHeight(host._control_height)
    host.effect_combo.setMaxVisibleItems(5)
    host.effect_combo.setIconSize(QSize(34, 18))
    host._effect_key_by_code = {effect.code: effect.key for effect in EFFECTS}
    for effect in EFFECTS:
        host.effect_combo.addItem(localization_manager.effect_name(effect.key), effect.code)
    host.effect_preview = EffectPreviewStrip()
    host.speed_slider = host._slider("purple")
    host.speed_slider.setRange(0, 100)
    host.speed_value = host._pill("60%")
    host.effects_card.content_layout.addWidget(host.effect_combo)
    host.effects_card.content_layout.addWidget(host.effect_preview)
    host.effects_card.content_layout.addLayout(
        host._slider_row(host._tr("effects.speed"), host.speed_slider, host.speed_value, "effects.speed")
    )
    return host.effects_card
