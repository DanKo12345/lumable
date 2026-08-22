from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    Qt,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from app.localization import localization_manager
from app.theme import theme_manager
from app.widgets.animation_helpers import play_or_complete


class AccentPreview(QFrame):
    FULL_HEIGHT = 132
    COMPACT_HEIGHT = 64
    _FULL_MARGINS = (24, 20, 24, 22)
    _COMPACT_MARGINS = (12, 12, 12, 14)
    _FULL_SWATCH_HEIGHT = 62
    _COMPACT_SWATCH_HEIGHT = 38

    def __init__(self):
        super().__init__()
        self.setObjectName("previewFrame")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._color = QColor(88, 182, 255)
        self._brightness = 100
        self.setMinimumHeight(0)
        self.setMaximumHeight(self.FULL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        self._layout = layout
        # The graphics effect is clipped to this widget. These margins match the
        # maximum blur plus its downward offset in _refresh().
        layout.setContentsMargins(*self._FULL_MARGINS)
        layout.setSpacing(7)
        self.swatch = QFrame()
        self.swatch.setObjectName("previewSwatch")
        self.swatch.setMinimumHeight(self._FULL_SWATCH_HEIGHT)
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
        self._info_opacity = QGraphicsOpacityEffect(self.info_label)
        self._info_opacity.setOpacity(1.0)
        self.info_label.setGraphicsEffect(self._info_opacity)
        self._compact = False
        self._compact_progress = 0.0
        self._info_full_height = 1
        self._compact_animation = QPropertyAnimation(self, b"compactProgress", self)
        self._compact_animation.setDuration(240)
        self._compact_animation.setEasingCurve(QEasingCurve.InOutCubic)
        self._compact_animation.finished.connect(self._finish_compact_animation)
        self._refresh()

    def set_compact(self, compact: bool, *, animate: bool = True) -> None:
        """Switch between the live-light hero and the compact status strip."""
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self._compact_animation.stop()
        target_progress = 1.0 if compact else 0.0

        if not animate or not self.isVisible():
            self._set_compact_progress(target_progress)
            self._finish_compact_animation()
            return

        if not compact:
            self.info_label.show()
        start = self._compact_progress
        self._compact_animation.setStartValue(start)
        self._compact_animation.setEndValue(target_progress)
        self._compact_animation.setDuration(max(1, round(240 * abs(target_progress - start))))
        play_or_complete(self._compact_animation)

    def _get_compact_progress(self) -> float:
        return self._compact_progress

    def _set_compact_progress(self, value: float) -> None:
        progress = max(0.0, min(1.0, float(value)))
        self._compact_progress = progress

        def interpolate(full: int, compact: int) -> int:
            return round(full + (compact - full) * progress)

        self.setMaximumHeight(interpolate(self.FULL_HEIGHT, self.COMPACT_HEIGHT))
        margins = tuple(
            interpolate(full, compact)
            for full, compact in zip(self._FULL_MARGINS, self._COMPACT_MARGINS, strict=True)
        )
        self._layout.setContentsMargins(*margins)
        self._layout.setSpacing(interpolate(7, 0))
        swatch_height = interpolate(self._FULL_SWATCH_HEIGHT, self._COMPACT_SWATCH_HEIGHT)
        self.swatch.setFixedHeight(swatch_height)
        self.info_label.setMaximumHeight(max(0, round(self._info_full_height * (1.0 - progress))))
        self._info_opacity.setOpacity(1.0 - progress)
        if progress < 1.0:
            self.info_label.show()
        self._update_swatch()

    compactProgress = Property(float, _get_compact_progress, _set_compact_progress)

    def _finish_compact_animation(self) -> None:
        self._set_compact_progress(1.0 if self._compact else 0.0)
        self.info_label.setVisible(not self._compact)

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
        self._info_full_height = max(1, self.info_label.sizeHint().height())
        self._set_compact_progress(self._compact_progress)

    def _update_swatch(self) -> None:
        # Show the pure colour (NOT multiplied by brightness) so it's always
        # recognisable; brightness is conveyed by the glow + the readout text.
        color = QColor(self._color)
        top = color.lighter(116)
        bottom = color.darker(106)
        border = "rgba(255,255,255,0.22)" if theme_manager.is_dark else "rgba(80,110,180,0.35)"
        # Follow the geometry continuously; changing this only in the animation's
        # finished callback caused a visible final-frame snap.
        radius = round(20 - self._compact_progress)
        self.swatch.setStyleSheet(
            "QFrame#previewSwatch { "
            f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {top.name()}, stop:0.5 {color.name()}, stop:1 {bottom.name()}); "
            f"border: 1px solid {border}; border-radius: {radius}px; }}"
        )
        glow = QColor(color)
        glow.setAlpha(int(75 + self._brightness * 1.6))  # brighter strip → stronger glow
        self._glow.setColor(glow)
        # Compact and full previews have separate glow budgets. At 100% these
        # are exactly 12px and 20px, both contained by their layout margins.
        full_blur = 12 + self._brightness * 0.08
        compact_blur = 7 + self._brightness * 0.05
        self._glow.setBlurRadius(
            full_blur + (compact_blur - full_blur) * self._compact_progress
        )
