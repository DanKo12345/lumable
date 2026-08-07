"""Picking which part of the screen drives the strip.

A dropdown reading "Full screen" explains nothing: the everyday complaint is
"why is my strip blue when the sunset is orange", and the answer is usually
that full screen honestly averages a frame which is mostly sky and water.

Each option carries a small drawing of the crop it takes, inside the segment
that selects it. A separate monitor illustration was tried first and read as a
foreign object: it had a stand while the rest of the interface is flat, its
frame competed with the focus ring beside it, and in the default region it was
one plain filled rectangle — a picture that said nothing most of the time.

The glyphs are drawn from :mod:`app.capture_regions`, the same fractions the
capture loop crops with, so they cannot promise a crop the loop does not take.
At 24×14 they show *where* the crop is; how much of the frame that is belongs
in the per-option tooltip, where a number can actually be read.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.capture_regions import REGION_IDS, normalize_region, region_box
from app.theme import qcolor_from_token, theme_manager
from app.widgets.segmented_control import SegmentedControl

# Large enough for a third of the height to be about 5px and the centre to be
# 12×7 — the difference between a band and a quarter stays visible. It sits
# inside the existing 40px segment, so the card gains no height at all.
ICON_WIDTH = 24
ICON_HEIGHT = 14


def paint_region_glyph(
    painter: QPainter, rect, region: str, active: bool, enabled: bool = True
) -> None:
    """A screen outline with the sampled part filled, for one region."""
    is_dark = theme_manager.is_dark
    accent = qcolor_from_token(theme_manager.palette["accent_start"])

    outline = QColor(255, 255, 255, 90 if is_dark else 0)
    if not is_dark:
        outline = QColor(24, 36, 61, 90)
    fill_alpha = 200 if active else 120
    if not enabled:
        fill_alpha = 60
        outline.setAlpha(45)

    frame_rect = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    frame = QPainterPath()
    frame.addRoundedRect(frame_rect, 2.0, 2.0)
    box = region_box(region)
    sampled = QRectF(
        frame_rect.left() + frame_rect.width() * box.left,
        frame_rect.top() + frame_rect.height() * box.top,
        frame_rect.width() * box.width,
        frame_rect.height() * box.height,
    )
    # The sample and the outline are one screen, not two stacked shapes. Clip
    # the colour to the same rounded body, then draw its rim on top: full-width
    # regions reach both edges without square corners protruding past the frame.
    painter.save()
    painter.setClipPath(frame)
    painter.fillRect(sampled, QColor(accent.red(), accent.green(), accent.blue(), fill_alpha))
    painter.restore()
    painter.setPen(outline)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(frame)


class CaptureAreaSelector(QWidget):
    """A caption and the four options, each showing the crop it takes."""

    selected = Signal(str)

    def __init__(self, labels: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.segments = SegmentedControl([(region, labels.get(region, region)) for region in REGION_IDS])
        self.segments.set_icon_painter(paint_region_glyph, (ICON_WIDTH, ICON_HEIGHT))
        # Four options, each with a glyph and a word, against a card that is
        # already narrow once the sidebar is out. The default padding multiplied
        # by four is what pushed this control past the card's width.
        self.segments.set_metrics(pad=12, icon_gap=6)
        self.title = QLabel()
        self.title.setObjectName("sliderLabel")
        self._title_text = ""
        self._labels = dict(labels)
        self._tooltips: dict[str, str] = {}
        self._help_text = ""

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addWidget(self.title, 0, Qt.AlignLeft)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.segments, 0, Qt.AlignLeft)
        row.addStretch(1)
        column.addLayout(row)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.segments.selected.connect(self._on_selected)

    def current_region(self) -> str:
        return self.segments.current_key()

    def set_current_region(self, region: str, *, animate: bool = True) -> None:
        self.segments.set_current(normalize_region(region), animate=animate)
        self._announce()

    def set_texts(
        self,
        *,
        title: str,
        help_text: str,
        labels: dict[str, str],
        tooltips: dict[str, str] | None = None,
    ) -> None:
        """The caption is short by design; what each option actually crops goes
        in its own tooltip, where "a quarter of the frame" can be stated rather
        than inferred from a 24-pixel drawing."""
        self.title.setText(title)
        self.segments.set_labels(labels)
        self._title_text = title
        self._labels = dict(labels)
        self._tooltips = dict(tooltips or {})
        self._help_text = help_text
        self.segments.set_tooltips(self._tooltips)
        self.setToolTip(help_text)
        self._announce()

    def _announce(self) -> None:
        """Put the choice and its position into the accessible name.

        This is a workaround, not a radio group. A painted QWidget has the role
        Qt gives it, and no name can turn it into four options with one checked
        — a screen reader still hears a single control. Spelling out "2 of 4"
        at least means the current choice and how many there are can be heard.
        """
        region = self.segments.current_key()
        label = self._labels.get(region, region)
        position = REGION_IDS.index(region) + 1 if region in REGION_IDS else 0
        spoken = f"{self._title_text}, {label}, {position} / {len(REGION_IDS)}"
        self.segments.setAccessibleName(spoken)
        self.setAccessibleName(spoken)
        # What this option actually crops, in the description that changes with
        # the choice. A tooltip needs a pointer; without this, someone on a
        # screen reader hears the general sentence and never "the central
        # quarter of the screen" — the one thing the glyph cannot say.
        described = self._tooltips.get(region, self._help_text)
        for widget in (self, self.segments):
            widget.setAccessibleDescription(described)

    def _on_selected(self, region: str) -> None:
        self._announce()
        self.selected.emit(region)
