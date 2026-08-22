from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
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
    COMPACT_HEIGHT = 54

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
        # Generous side/top margins so the coloured glow has room to render —
        # the effect is clipped to this widget's bounds, so margins must be at
        # least the glow's blur radius or the aura gets cut off.
        layout.setContentsMargins(24, 16, 24, 14)
        layout.setSpacing(7)
        self.swatch = QFrame()
        self.swatch.setObjectName("previewSwatch")
        self.swatch.setMinimumHeight(62)
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
        self._compact_animation = QParallelAnimationGroup(self)
        self._height_animation = QPropertyAnimation(self, b"maximumHeight", self)
        self._info_animation = QPropertyAnimation(self._info_opacity, b"opacity", self)
        for animation in (
            self._height_animation,
            self._info_animation,
        ):
            animation.setDuration(240)
            animation.setEasingCurve(QEasingCurve.InOutCubic)
            self._compact_animation.addAnimation(animation)
        self._compact_animation.finished.connect(self._finish_compact_animation)
        self._refresh()

    def set_compact(self, compact: bool, *, animate: bool = True) -> None:
        """Switch between the live-light hero and the compact status strip."""
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        target = self.COMPACT_HEIGHT if compact else self.FULL_HEIGHT
        target_margins = (12, 7, 12, 7) if compact else (24, 16, 24, 14)
        target_swatch = 38 if compact else 62
        target_opacity = 0.0 if compact else 1.0
        self._compact_animation.stop()

        # Re-style the swatch: the corner radius depends on the compact state
        # (a radius over half the box height makes Qt draw square corners).
        self._refresh()

        if not animate or not self.isVisible():
            self._apply_compact_state(
                target,
                target_margins,
                target_swatch,
                target_opacity,
            )
            return

        if not compact:
            # Prepare the full layout while it is still clipped by the compact
            # outer height; only that outer edge and the label opacity move.
            self._layout.setContentsMargins(*target_margins)
            self._layout.setSpacing(7)
            self.swatch.setMinimumHeight(target_swatch)
            self.swatch.setMaximumHeight(16777215)
            self.info_label.show()
        start = max(self.COMPACT_HEIGHT, min(self.FULL_HEIGHT, self.maximumHeight()))
        self._height_animation.setStartValue(start)
        self._height_animation.setEndValue(target)
        self._info_animation.setStartValue(self._info_opacity.opacity())
        self._info_animation.setEndValue(target_opacity)
        play_or_complete(self._compact_animation)

    def _apply_compact_state(
        self,
        height: int,
        margins: tuple[int, int, int, int],
        swatch_height: int,
        info_opacity: float,
    ) -> None:
        self.setMaximumHeight(height)
        self._layout.setContentsMargins(*margins)
        self._layout.setSpacing(0 if self._compact else 7)
        self.swatch.setMinimumHeight(swatch_height)
        self.swatch.setMaximumHeight(swatch_height if self._compact else 16777215)
        self._info_opacity.setOpacity(info_opacity)
        self.info_label.setVisible(not self._compact)

    def _finish_compact_animation(self) -> None:
        margins = (12, 7, 12, 7) if self._compact else (24, 16, 24, 14)
        self._apply_compact_state(
            self.COMPACT_HEIGHT if self._compact else self.FULL_HEIGHT,
            margins,
            38 if self._compact else 62,
            0.0 if self._compact else 1.0,
        )

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
        # Full capsule in compact mode; the radius must stay at or below half the
        # swatch height, otherwise Qt silently falls back to square corners.
        radius = 19 if self._compact else 20
        self.swatch.setStyleSheet(
            "QFrame#previewSwatch { "
            f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {top.name()}, stop:0.5 {color.name()}, stop:1 {bottom.name()}); "
            f"border: 1px solid {border}; border-radius: {radius}px; }}"
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
