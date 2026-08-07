from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

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
        self._tooltips: dict[str, str] = {}
        self._icon_painter = None
        self._icon_size: tuple[int, int] = (0, 0)
        self._icon_gap = 8
        # Shown for keyboard use only. A ring drawn after every click is noise
        # next to the pill that already says what is selected.
        self._show_focus_ring = False
        self._anim = make_property_animation(self, b"posValue", 240, QEasingCurve.OutCubic)
        self.setMinimumHeight(38)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # One stop in the tab order for the whole group, with the arrows moving
        # inside it — the same bargain a radio group makes. Without this the
        # control was reachable only by mouse.
        self.setFocusPolicy(Qt.StrongFocus)

    # ── api ───────────────────────────────────────────────────────────
    def set_labels(self, labels: dict[str, str]) -> None:
        for key, label in labels.items():
            if key in self._labels:
                self._labels[key] = label
        self.updateGeometry()
        self.update()

    def set_tooltips(self, tooltips: dict[str, str]) -> None:
        """One hint per option, shown for whichever segment is under the cursor.

        A single tooltip on the whole control cannot say what "Centre" actually
        crops, which is the one thing a person hovering it wants to know.
        """
        self._tooltips = dict(tooltips)

    def set_metrics(self, *, pad: int | None = None, icon_gap: int | None = None) -> None:
        """Tighten the spacing for a control that has to fit somewhere narrow.

        The defaults suit a two or three option control with room around it.
        Four options carrying both a glyph and a label multiply that padding by
        four and stop fitting the card, so this one asks for less.
        """
        if pad is not None:
            self._pad = int(pad)
        if icon_gap is not None:
            self._icon_gap = int(icon_gap)
        self.updateGeometry()
        self.update()

    def set_icon_painter(self, painter_fn, size: tuple[int, int]) -> None:
        """Draw a glyph to the left of each label.

        A callback rather than a pixmap so the drawing can be derived from the
        thing it describes — an icon that is merely shaped like the setting
        drifts away from it the first time either changes.
        """
        self._icon_painter = painter_fn
        self._icon_size = size
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
    def _icon_extent(self) -> int:
        return (self._icon_size[0] + self._icon_gap) if self._icon_painter else 0

    def _label_font(self, *, active: bool) -> QFont:
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold if active else QFont.Weight.Medium)
        return font

    def _label_width(self, label: str, *, active: bool) -> int:
        return QFontMetrics(self._label_font(active=active)).horizontalAdvance(label)

    def _label_paint_width(self, label: str, *, active: bool) -> int:
        """Width of the visible glyphs, including their right-side overhang.

        ``horizontalAdvance()`` is the distance to the next glyph, not a paint
        boundary. Cyrillic letters in the selected DemiBold font can extend a
        pixel beyond it, which clipped the last letter only after selection.
        """
        metrics = QFontMetrics(self._label_font(active=active))
        return max(metrics.horizontalAdvance(label), metrics.boundingRect(label).width()) + 2

    def _segment_width(self) -> float:
        # The selected label is DemiBold. Measuring only the resting Medium
        # state makes the last glyph disappear as soon as the pill reaches it.
        widest = max(
            (
                max(
                    self._label_paint_width(label, active=False),
                    self._label_paint_width(label, active=True),
                )
                for label in self._labels.values()
            ),
            default=40,
        )
        return float(widest + self._icon_extent() + self._pad * 2)

    def _segment_index_at(self, x: float) -> int:
        if not self._keys:
            return -1
        seg = self.width() / len(self._keys)
        return int(max(0, min(len(self._keys) - 1, x // seg)))

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
        key = self._keys[self._segment_index_at(event.position().x())]
        if key != self._current:
            self.set_current(key)
            self.selected.emit(key)
        # Focus still moves here, so the arrows work straight after a click —
        # only the ring stays hidden until the keyboard is actually used.
        self._show_focus_ring = False
        self.setFocus(Qt.MouseFocusReason)
        self.update()
        event.accept()

    def event(self, event):
        if event.type() == QEvent.ToolTip and self._tooltips:
            index = self._segment_index_at(event.pos().x())
            if index >= 0:
                QToolTip.showText(event.globalPos(), self._tooltips.get(self._keys[index], ""), self)
                return True
        return super().event(event)

    def focusInEvent(self, event) -> None:
        # Arriving by keyboard shows the ring; arriving by click does not.
        self._show_focus_ring = event.reason() in (
            Qt.TabFocusReason,
            Qt.BacktabFocusReason,
            Qt.ShortcutFocusReason,
        )
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        self._show_focus_ring = False
        super().focusOutEvent(event)
        self.update()

    def keyPressEvent(self, event) -> None:
        """Arrows move the selection; Home and End jump to the ends.

        Moving the selection rather than a separate focus cursor is what a radio
        group does, and it is what makes the choice reachable without a mouse at
        all — the effect is applied as you arrow across, and arrowing back undoes
        it, so nothing is committed that cannot be seen.
        """
        if not self._keys:
            super().keyPressEvent(event)
            return
        index = self._keys.index(self._current) if self._current in self._keys else 0
        if event.key() in (Qt.Key_Left, Qt.Key_Up):
            target = max(0, index - 1)
        elif event.key() in (Qt.Key_Right, Qt.Key_Down):
            target = min(len(self._keys) - 1, index + 1)
        elif event.key() == Qt.Key_Home:
            target = 0
        elif event.key() == Qt.Key_End:
            target = len(self._keys) - 1
        else:
            super().keyPressEvent(event)
            return
        # The keyboard is in use now, whichever way the focus first arrived.
        self._show_focus_ring = True
        key = self._keys[target]
        if key != self._current:
            self.set_current(key)
            self.selected.emit(key)
        self.update()
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

        # labels, with the optional glyph and the label centred together
        icon_w, icon_h = self._icon_size
        extent = self._icon_extent()
        for index, key in enumerate(self._keys):
            seg_rect = QRectF(rect.left() + index * seg_w, rect.top(), seg_w, rect.height())
            active = abs(self._pos - index) < 0.5
            font = self._label_font(active=active)
            painter.setFont(font)
            if active:
                # On the pale pill in light mode the label must be dark to read.
                color = QColor(255, 255, 255, 245) if is_dark else QColor(24, 36, 61, 250)
            else:
                color = qcolor_from_token(theme_manager.palette["text_soft"])
            if not enabled:
                color.setAlpha(110)
            label = self._labels.get(key, key)
            if not extent:
                painter.setPen(color)
                painter.drawText(seg_rect, Qt.AlignCenter, label)
                continue
            text_w = self._label_paint_width(label, active=active)
            content_left = seg_rect.center().x() - (extent + text_w) / 2.0
            icon_rect = QRectF(
                content_left, seg_rect.center().y() - icon_h / 2.0, float(icon_w), float(icon_h)
            )
            painter.save()
            self._icon_painter(painter, icon_rect, key, active, enabled)
            painter.restore()
            painter.setPen(color)
            painter.drawText(
                QRectF(content_left + extent, seg_rect.top(), float(text_w), seg_rect.height()),
                Qt.AlignVCenter | Qt.AlignLeft,
                label,
            )

        if self._show_focus_ring:
            # Drawn around the whole track: the group is one tab stop, so the
            # ring belongs to the group and not to whichever segment is current.
            focus = QPainterPath()
            focus.addRoundedRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5), radius + 1.0, radius + 1.0)
            painter.setPen(QPen(qcolor_from_token(theme_manager.palette["accent_start"]), 2.0))
            painter.drawPath(focus)
