from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.section_icon import SectionIcon


class GlassCard(QFrame):
    def __init__(self, title: str, subtitle: str | None = None, parent=None, icon: str | None = None):
        super().__init__(parent)
        self.setObjectName("glassCard")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 20)
        outer.setSpacing(4)
        self.icon_widget = SectionIcon(icon, self) if icon else None
        self.header_widget = QWidget(self)
        self.header_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.header_widget.setMinimumHeight(28)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.title_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title_label.setMinimumHeight(28)
        header = QHBoxLayout(self.header_widget)
        self.header_layout = header
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(0)
        if self.icon_widget is not None:
            header.addWidget(self.icon_widget, 0, Qt.AlignVCenter)
            header.addSpacing(10)
        header.addWidget(self.title_label, 0, Qt.AlignVCenter)
        header.addStretch(1)
        outer.addWidget(self.header_widget)
        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setWordWrap(True)
            self.subtitle_label.setObjectName("cardSubtitle")
            self.subtitle_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            self.subtitle_label.setMinimumHeight(26)
            self.subtitle_label.setContentsMargins(0, 1, 0, 6)
            self.subtitle_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            outer.addWidget(self.subtitle_label)
        else:
            self.subtitle_label = None
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 10, 0, 0)
        self.content_layout.setSpacing(13)
        outer.addLayout(self.content_layout)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2.0, 2.0, -2.0, -2.0)
        radius = 22.0
        path_bg = QPainterPath()
        path_bg.addRoundedRect(rect, radius, radius)
        palette = theme_manager.palette
        is_dark = theme_manager.is_dark

        # Translucent surface: the ambient light behind (already tinted with the
        # strip colour) shows softly through, so the card "lives" with the glow
        # without any per-card plumbing. Still opaque enough to keep text legible.
        fill = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        if is_dark:
            # Neutral charcoal panel (not the blue surface token) so cards read as
            # premium dark cards on the near-black canvas, not blue boxes.
            surface_top = QColor(28, 31, 41, 238)
            surface_bottom = QColor(20, 22, 30, 242)
        else:
            surface_top = qcolor_from_token(palette["surface_soft"])
            surface_bottom = qcolor_from_token(palette["surface"])
            surface_top.setAlpha(196)
            surface_bottom.setAlpha(212)
        fill.setColorAt(0.0, surface_top)
        fill.setColorAt(1.0, surface_bottom)
        painter.fillPath(path_bg, fill)

        # Single soft top sheen (no framed inner box, no extra borders).
        sheen = QLinearGradient(0, rect.top(), 0, rect.top() + rect.height() * 0.5)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 16 if is_dark else 12))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path_bg, sheen)

        # Hairline glass rim: bright at the top, fading toward the bottom — reads
        # as a soft edge of glass rather than a hard drawn border.
        edge = QLinearGradient(0, rect.top(), 0, rect.bottom())
        if is_dark:
            edge.setColorAt(0.0, QColor(255, 255, 255, 60))
            edge.setColorAt(1.0, QColor(255, 255, 255, 22))
        else:
            # Visible cool border on light cards (a white top edge vanished on
            # the light background, leaving cards looking borderless/flat).
            edge.setColorAt(0.0, QColor(120, 140, 190, 135))
            edge.setColorAt(1.0, QColor(120, 140, 190, 85))
        painter.setPen(QPen(QBrush(edge), 1.0))
        painter.drawRoundedRect(rect, radius, radius)
