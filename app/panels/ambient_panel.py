from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel

from app.panels.types import PanelHost
from app.widgets import GlassCard, StaticPopupComboBox
from app.widgets.ambient_preview import AmbientPreview

_REGIONS = ("full", "center", "bottom", "top")


def build_ambient_section(host: PanelHost) -> GlassCard:
    host.ambient_card = host._card(host._tr("ambient.title"), host._tr("ambient.subtitle"), icon="color")
    host.ambient_card.setMinimumHeight(host._sz(196))

    # Pro badge shown when screen sync isn't unlocked (toggled by the controller).
    host.ambient_lock_label = QLabel(host._tr("ambient.pro_locked"))
    host.ambient_lock_label.setObjectName("proBadge")
    host.ambient_lock_label.setStyleSheet(
        "QLabel#proBadge { background: rgba(143, 191, 255, 0.16); color: #9fc0ff;"
        " padding: 5px 12px; border-radius: 11px; }"
    )
    host.ambient_lock_label.hide()
    host.ambient_card.content_layout.addWidget(host.ambient_lock_label, 0, Qt.AlignLeft)

    row = QHBoxLayout()
    row.setSpacing(10)
    row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    host.ambient_toggle_button = host._button(host._tr("ambient.toggle_off"), "ghost")
    host.ambient_toggle_button.setCheckable(True)
    host.ambient_toggle_button.setFixedSize(host._sz(104), host._sz(42))

    host.ambient_region_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.ambient_region_combo.setMinimumHeight(host._control_height)
    host.ambient_region_combo.setMinimumWidth(150)
    for region in _REGIONS:
        host.ambient_region_combo.addItem(host._tr(f"ambient.region.{region}"), region)

    # Monitor picker — only shown when there is more than one screen to choose from.
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

    row.addWidget(host.ambient_toggle_button)
    row.addWidget(host.ambient_region_combo)
    if host.ambient_monitor_combo is not None:
        row.addWidget(host.ambient_monitor_combo)
    row.addStretch(1)
    host.ambient_card.content_layout.addLayout(row)

    # Live capture status ("Захват активен · N к/с"), shown only while running.
    host.ambient_status_label = QLabel("")
    host.ambient_status_label.setObjectName("cardSubtitle")
    host.ambient_status_label.setVisible(False)
    host.ambient_card.content_layout.addWidget(host.ambient_status_label)

    host.ambient_preview = AmbientPreview()
    host.ambient_card.content_layout.addWidget(host.ambient_preview)

    host.ambient_saturation_slider = host._slider("purple")
    host.ambient_saturation_slider.setRange(0, 100)
    host.ambient_saturation_value = host._pill("55%")
    host.ambient_card.content_layout.addLayout(
        host._slider_row(
            host._tr("ambient.saturation"),
            host.ambient_saturation_slider,
            host.ambient_saturation_value,
            "ambient.saturation",
        )
    )

    host.ambient_smoothing_slider = host._slider("blue")
    host.ambient_smoothing_slider.setRange(0, 100)
    host.ambient_smoothing_value = host._pill("65%")
    host.ambient_card.content_layout.addLayout(
        host._slider_row(
            host._tr("ambient.smoothing"),
            host.ambient_smoothing_slider,
            host.ambient_smoothing_value,
            "ambient.smoothing",
        )
    )
    return host.ambient_card
