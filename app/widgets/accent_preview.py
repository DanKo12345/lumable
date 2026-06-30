from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QLabel, QSizePolicy, QVBoxLayout

from app.localization import localization_manager
from app.theme import theme_manager


class AccentPreview(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("previewFrame")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._color = QColor(88, 182, 255)
        self._brightness = 100
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        # Generous side/top margins so the coloured glow has room to render —
        # the effect is clipped to this widget's bounds, so margins must be at
        # least the glow's blur radius or the aura gets cut off.
        layout.setContentsMargins(38, 36, 38, 38)
        layout.setSpacing(10)
        self.swatch = QFrame()
        self.swatch.setObjectName("previewSwatch")
        self.swatch.setMinimumHeight(82)
        # Coloured glow beneath the swatch — makes it read as real light. Its
        # strength tracks brightness, so a dim strip glows softly without the
        # colour itself going dark (the colour stays recognisable at any %).
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 2)
        self.swatch.setGraphicsEffect(self._glow)
        layout.addWidget(self.swatch)
        self.info_label = QLabel()
        self.info_label.setObjectName("previewInfo")
        layout.addWidget(self.info_label)
        self._refresh()

    def set_color(self, color: QColor):
        self._color = color
        self._refresh()

    def set_brightness(self, value: int):
        self._brightness = max(0, min(100, int(value)))
        self._refresh()

    def set_theme(self, theme: str):
        self._refresh()

    def refresh_text(self):
        self._refresh()

    def _refresh(self):
        # Show the pure colour (NOT multiplied by brightness) so it's always
        # recognisable; brightness is conveyed by the glow + the readout text.
        color = QColor(self._color)
        top = color.lighter(116)
        bottom = color.darker(106)
        border = "rgba(255,255,255,0.22)" if theme_manager.is_dark else "rgba(80,110,180,0.35)"
        self.swatch.setStyleSheet(
            "QFrame#previewSwatch { "
            f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {top.name()}, stop:0.5 {color.name()}, stop:1 {bottom.name()}); "
            f"border: 1px solid {border}; border-radius: 20px; }}"
        )
        glow = QColor(color)
        glow.setAlpha(int(75 + self._brightness * 1.6))  # brighter strip → stronger glow
        self._glow.setColor(glow)
        # Cap the blur so the aura stays inside the widget margins (no clipping).
        self._glow.setBlurRadius(16 + self._brightness * 0.16)

        self.info_label.setText(
            localization_manager.t(
                "preview.rgb",
                r=self._color.red(),
                g=self._color.green(),
                b=self._color.blue(),
                brightness_label=localization_manager.t("slider.brightness"),
                brightness=self._brightness,
            )
        )
