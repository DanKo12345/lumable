from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.animation_helpers import make_property_animation, restart_animation


class SegmentedControl(QWidget):
    """An iOS-style segmented toggle: several options share one rounded track, and
    a highlighted pill slides between them. Reads clearly as a single "pick one"
    control instead of separate buttons. Emits ``selected(key)`` on change."""

    selected = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._options = list(options)
        self._keys = [key for key, _ in self._options]
        self._labels = dict(self._options)
        self._current = self._keys[0] if self._keys else ""
        self._pos = 0.0  # animated highlight index
        self._pad = 20
        self._anim = make_property_animation(self, b"posValue", 240, QEasingCurve.OutCubic)
        self.setMinimumHeight(38)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    # ── api ───────────────────────────────────────────────────────────
    def set_labels(self, labels: dict[str, str]) -> None:
        for key, label in labels.items():
            if key in self._labels:
                self._labels[key] = label
        self.updateGeometry()
        self.update()

    def current_key(self) -> str:
        return self._current

    def set_current(self, key: str, *, animate: bool = True) -> None:
        if key not in self._keys:
            return
        self._current = key
        target = float(self._keys.index(key))
        if animate:
            restart_animation(self._anim, self._pos, target)
        else:
            self._anim.stop()
            self._pos = target
            self.update()

    # ── sizing ────────────────────────────────────────────────────────
    def _segment_width(self) -> float:
        metrics = self.fontMetrics()
        widest = max((metrics.horizontalAdvance(label) for label in self._labels.values()), default=40)
        return float(widest + self._pad * 2)

    def sizeHint(self) -> QSize:
        seg = self._segment_width()
        return QSize(round(seg * max(1, len(self._keys))) + 6, 40)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # ── interaction ───────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or not self._keys:
            super().mousePressEvent(event)
            return
        seg = self.width() / len(self._keys)
        index = int(max(0, min(len(self._keys) - 1, event.position().x() // seg)))
        key = self._keys[index]
        if key != self._current:
            self.set_current(key)
            self.selected.emit(key)
        event.accept()

    # ── animation prop ────────────────────────────────────────────────
    def get_pos_value(self) -> float:
        return self._pos

    def set_pos_value(self, value: float) -> None:
        self._pos = float(value)
        self.update()

    posValue = Property(float, get_pos_value, set_pos_value)

    # ── paint ─────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        if not self._keys:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        is_dark = theme_manager.is_dark
        enabled = self.isEnabled()
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        radius = rect.height() / 2.0

        # track
        track = QPainterPath()
        track.addRoundedRect(rect, radius, radius)
        track_bg = QColor(255, 255, 255, 16) if is_dark else QColor(92, 120, 190, 26)
        painter.fillPath(track, track_bg)

        # sliding highlight pill
        count = len(self._keys)
        seg_w = rect.width() / count
        pill = QRectF(rect.left() + self._pos * seg_w + 3.0, rect.top() + 3.0, seg_w - 6.0, rect.height() - 6.0)
        pill_path = QPainterPath()
        pill_radius = pill.height() / 2.0
        pill_path.addRoundedRect(pill, pill_radius, pill_radius)
        # Neutral raised pill (iOS-style), so it matches the card without pulling
        # in the blue brand accent that clashes with the warm sliders/preview here.
        fill = QColor(255, 255, 255, 34 if is_dark else 240)
        if not enabled:
            fill.setAlpha(16 if is_dark else 120)
        painter.fillPath(pill_path, fill)
        painter.setPen(QPen(QColor(255, 255, 255, 40 if is_dark else 0), 1.0))
        painter.drawPath(pill_path)

        # labels
        font = self.font()
        for index, key in enumerate(self._keys):
            seg_rect = QRectF(rect.left() + index * seg_w, rect.top(), seg_w, rect.height())
            active = abs(self._pos - index) < 0.5
            font.setWeight(QFont.Weight.DemiBold if active else QFont.Weight.Medium)
            painter.setFont(font)
            if active:
                # On the pale pill in light mode the label must be dark to read.
                color = QColor(255, 255, 255, 245) if is_dark else QColor(24, 36, 61, 250)
            else:
                color = qcolor_from_token(theme_manager.palette["text_soft"])
            if not enabled:
                color.setAlpha(110)
            painter.setPen(color)
            painter.drawText(seg_rect, Qt.AlignCenter, self._labels.get(key, key))
