"""Picking which part of the screen drives the strip, as a picture.

A dropdown reading "Full screen" explains nothing: the everyday complaint is
"why is my strip blue when the sunset is orange", and the answer is usually
that full screen honestly averages a frame which is mostly sky and water. A
schematic monitor with the sampled area lit and the rest dimmed answers that
before it is asked.

Two things are shown, in two places that cannot be confused:

* **inside the screen** — the sampled rectangle in the accent colour, the rest
  under a dimming mask. This is geometry: which pixels count.
* **outside it** — a faint wash in the strip's current colour, where a bias
  light actually sits. This is the result.

The rectangles come from :mod:`app.capture_regions`, the same source the capture
loop crops with, so the drawing cannot promise a crop the loop does not take.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.capture_regions import REGION_IDS, normalize_region, region_box
from app.theme import qcolor_from_token, theme_manager
from app.widgets.animation_helpers import make_property_animation, restart_animation
from app.widgets.segmented_control import SegmentedControl

# The card has roughly 60–90px to spare before it outgrows a 1000×700 window, so
# the whole row is budgeted at ~64: the monitor at 112×63 beside a 42px control.
# At this size a third of the height is still 21px and the centre is 56×31 — the
# proportions stay legible, which is the only reason the picture exists.
_DIAGRAM_WIDTH = 112
_DIAGRAM_HEIGHT = 63
# Narrow cards shrink the monitor instead of stacking: stacking is what put the
# row over the height budget in the first place.
_DIAGRAM_MIN_WIDTH = 96
_DIAGRAM_MIN_HEIGHT = 54


class MonitorDiagram(QWidget):
    """A schematic screen with the sampled area lit and a wash of the result."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._region = REGION_IDS[0]
        self._result: tuple[int, int, int] | None = None
        # A float from 0 to 1 is animated and the four edges are computed from
        # it. Animating the rectangle itself as a QVariant tuple looks tidier and
        # does not work: Qt cannot interpolate a Python tuple, so it hands the
        # setter None, the box never moves, and the picture keeps showing the
        # old area while the capture has already switched.
        self._box = (0.0, 0.0, 1.0, 1.0)
        self._from = self._box
        self._to = self._box
        self._progress = 1.0
        self._anim = make_property_animation(self, b"progressValue", 180, QEasingCurve.OutCubic)
        self.setFixedSize(_DIAGRAM_WIDTH, _DIAGRAM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_region(self, region: str, *, animate: bool = True) -> None:
        self._region = normalize_region(region)
        box = region_box(self._region)
        target = (box.left, box.top, box.width, box.height)
        if animate:
            # From wherever the rectangle currently is, so interrupting a move
            # continues from what is on screen rather than snapping back.
            self._from = self._box
            self._to = target
            restart_animation(self._anim, 0.0, 1.0)
        else:
            self._anim.stop()
            self._from = self._to = self._box = target
            self._progress = 1.0
            self.update()

    def set_result_color(self, rgb: tuple[int, int, int] | None) -> None:
        """The strip's current colour, or ``None`` when nothing is running.

        Cleared rather than frozen on stop: a wash left glowing would claim the
        strip is showing a colour it stopped showing.
        """
        if rgb == self._result:
            return
        self._result = rgb
        self.update()

    # ── animation prop ────────────────────────────────────────────────
    def get_progress_value(self) -> float:
        return self._progress

    def set_progress_value(self, value: float) -> None:
        self._progress = float(value)
        if self._progress >= 1.0:
            # Snapped, not interpolated: at a progress of exactly 1 the
            # arithmetic still lands a hair off the target, and the rectangle
            # that is finally shown must be the one that will be captured.
            self._box = self._to
        else:
            self._box = tuple(
                start + (end - start) * self._progress
                for start, end in zip(self._from, self._to, strict=True)
            )
        self.update()

    progressValue = Property(float, get_progress_value, set_progress_value)

    # ── paint ─────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        is_dark = theme_manager.is_dark
        accent = qcolor_from_token(theme_manager.palette["accent_start"])

        stand_h = 6.0
        screen = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - stand_h - 5.0)

        if self._result is not None:
            self._paint_result_wash(painter, screen)

        screen_path = QPainterPath()
        screen_path.addRoundedRect(screen, 5.0, 5.0)
        painter.fillPath(screen_path, QColor(255, 255, 255, 12) if is_dark else QColor(28, 34, 48, 20))

        painter.save()
        painter.setClipPath(screen_path)
        # The mask is the message: everything outside the sampled area is not
        # counted, and dimming it says so more plainly than tinting the rest.
        painter.fillRect(screen, QColor(6, 8, 12, 150) if is_dark else QColor(20, 26, 38, 90))
        left, top, width, height = self._box
        area = QRectF(
            screen.left() + screen.width() * left,
            screen.top() + screen.height() * top,
            screen.width() * width,
            screen.height() * height,
        )
        painter.fillRect(area, QColor(accent.red(), accent.green(), accent.blue(), 46))
        painter.setPen(QColor(accent.red(), accent.green(), accent.blue(), 210))
        painter.drawRect(area.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.restore()

        painter.setPen(QColor(255, 255, 255, 60) if is_dark else QColor(28, 34, 48, 70))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(screen_path)

        stand = QRectF(self.width() * 0.38, screen.bottom() + 1.0, self.width() * 0.24, stand_h)
        painter.fillRect(stand, QColor(255, 255, 255, 45) if is_dark else QColor(28, 34, 48, 55))

    def _paint_result_wash(self, painter: QPainter, screen: QRectF) -> None:
        """A faint spill of the strip's colour behind the monitor.

        Kept very low: this is atmosphere, and the exact figures live in the
        preview above. Loud enough to compete with the sampled area, it would
        turn one picture into two competing readings.
        """
        red, green, blue = self._result
        centre = screen.center()
        radius = max(screen.width(), screen.height()) * 0.85
        gradient = QRadialGradient(centre, radius)
        gradient.setColorAt(0.0, QColor(red, green, blue, 46))
        gradient.setColorAt(0.6, QColor(red, green, blue, 16))
        gradient.setColorAt(1.0, QColor(red, green, blue, 0))
        painter.fillRect(self.rect(), gradient)


class CaptureAreaSelector(QWidget):
    """The diagram and the four choices, side by side until the card is narrow."""

    selected = Signal(str)

    def __init__(self, labels: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.diagram = MonitorDiagram(self)
        self.segments = SegmentedControl([(region, labels.get(region, region)) for region in REGION_IDS])
        self.title = QLabel()
        self.title.setObjectName("sliderLabel")
        self._title_text = ""
        self._labels = dict(labels)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        text.addWidget(self.title, 0, Qt.AlignLeft | Qt.AlignBottom)
        text.addWidget(self.segments, 0, Qt.AlignLeft)

        self._row = QBoxLayout(QBoxLayout.LeftToRight, self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(14)
        self._row.addWidget(self.diagram, 0, Qt.AlignVCenter)
        self._row.addLayout(text, 1)

        # Fixed vertically, or the card's layout hands it every spare pixel: the
        # block claimed the whole card and pushed the sliders out of the window.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.segments.selected.connect(self._on_selected)
        self.diagram.set_region(self.segments.current_key(), animate=False)

    def current_region(self) -> str:
        return self.segments.current_key()

    def set_current_region(self, region: str, *, animate: bool = True) -> None:
        region = normalize_region(region)
        self.segments.set_current(region, animate=animate)
        self.diagram.set_region(region, animate=animate)
        self._announce()

    def set_result_color(self, rgb: tuple[int, int, int] | None) -> None:
        self.diagram.set_result_color(rgb)

    def set_texts(self, *, title: str, help_text: str, labels: dict[str, str]) -> None:
        """The caption is short by design; the sentence goes where it costs no
        height — a tooltip, and the accessible description a screen reader
        reads out, since the picture itself says nothing out loud."""
        self.title.setText(title)
        self.segments.set_labels(labels)
        self._title_text = title
        self._labels = dict(labels)
        for widget in (self, self.diagram, self.segments):
            widget.setToolTip(help_text)
            widget.setAccessibleDescription(help_text)
        self._announce()

    def _announce(self) -> None:
        """Put the choice and its position into the accessible name.

        This is a workaround, not a radio group. A painted QWidget has the role
        Qt gives it, and no name can turn it into four options with one checked
        — a screen reader still hears a single control. Spelling out "2 of 4"
        at least means the current choice and how many there are can be heard,
        which is more than the name alone conveyed.
        """
        region = self.segments.current_key()
        label = self._labels.get(region, region)
        position = REGION_IDS.index(region) + 1 if region in REGION_IDS else 0
        spoken = f"{self._title_text}, {label}, {position} / {len(REGION_IDS)}"
        self.segments.setAccessibleName(spoken)
        self.diagram.setAccessibleName(spoken)
        self.setAccessibleName(spoken)

    def _on_selected(self, region: str) -> None:
        self.diagram.set_region(region)
        self._announce()
        self.selected.emit(region)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Stacking is what pushed this row over the card's height budget, so a
        # narrow card shrinks the monitor instead — down to a floor, below which
        # the thirds and the centre stop being tellable apart.
        spare = self.width() - self.segments.sizeHint().width() - self._row.spacing()
        width = max(_DIAGRAM_MIN_WIDTH, min(_DIAGRAM_WIDTH, spare))
        height = round(width * _DIAGRAM_MIN_HEIGHT / _DIAGRAM_MIN_WIDTH)
        if self.diagram.width() != width:
            self.diagram.setFixedSize(width, height)
            self.updateGeometry()
