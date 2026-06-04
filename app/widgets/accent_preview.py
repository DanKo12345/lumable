from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout

from app.localization import localization_manager
from app.theme import theme_manager


class AccentPreview(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("previewFrame")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._color = QColor(88, 182, 255)
        self._brightness = 100
        self.setMinimumHeight(128)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        self.swatch = QFrame()
        self.swatch.setObjectName("previewSwatch")
        self.swatch.setMinimumHeight(72)
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
        factor = self._brightness / 100
        display = QColor(
            round(self._color.red() * factor),
            round(self._color.green() * factor),
            round(self._color.blue() * factor),
        )
        if self._brightness >= 99:
            top = display.lighter(108)
            bottom = display
        else:
            top = display.lighter(112)
            bottom = display.darker(102)
        border = "rgba(255,255,255,0.22)" if theme_manager.is_dark else "rgba(80,110,180,0.35)"
        self.swatch.setStyleSheet(
            f"QFrame#previewSwatch {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {top.name()}, stop:1 {bottom.name()}); border: 1px solid {border}; border-radius: 20px; }}"
        )
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
