from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
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
        outer.setContentsMargins(24, 20, 24, 22)
        outer.setSpacing(6)
        self.icon_widget = SectionIcon(icon, self) if icon else None
        self.header_widget = QWidget(self)
        self.header_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.header_widget.setMinimumHeight(32)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.title_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title_label.setMinimumHeight(32)
        header = QHBoxLayout(self.header_widget)
        self.header_layout = header
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(0)
        header.addStretch(1)
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
            self.subtitle_label.setMinimumHeight(34)
            self.subtitle_label.setContentsMargins(0, 2, 0, 12)
            self.subtitle_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            outer.addWidget(self.subtitle_label)
        else:
            self.subtitle_label = None
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 16, 0, 0)
        self.content_layout.setSpacing(16)
        outer.addLayout(self.content_layout)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2.0, 2.0, -2.0, -2.0)
        radius = 26.0
        path_bg = QPainterPath()
        path_bg.addRoundedRect(rect, radius, radius)
        palette = theme_manager.palette

        fill = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        surface_top = qcolor_from_token(palette["surface_soft"])
        surface_bottom = qcolor_from_token(palette["surface"])
        if theme_manager.is_dark:
            surface_top = surface_top.lighter(102)
            surface_bottom = surface_bottom.darker(102)
        else:
            surface_top = surface_top.lighter(101)
            surface_bottom = surface_bottom.darker(101)
        fill.setColorAt(0.0, surface_top)
        fill.setColorAt(1.0, surface_bottom)
        painter.fillPath(path_bg, fill)

        haze = QRadialGradient(self.width() * 0.18, self.height() * 0.0, max(self.width(), self.height()) * 0.62)
        haze.setColorAt(0.0, QColor(255, 255, 255, 20 if theme_manager.is_dark else 8))
        haze.setColorAt(0.35, QColor(210, 226, 255, 8 if theme_manager.is_dark else 3))
        haze.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path_bg, haze)

        inner_height = max(24.0, min(78.0, self.height() * 0.31))
        inner_top = rect.top() + 1.0
        inner = QRectF(rect.left() + 1.0, inner_top, rect.width() - 2.0, inner_height)
        if theme_manager.is_dark:
            inner_pen = QColor(255, 255, 255, 72)
        else:
            inner_pen = QColor(80, 120, 200, 85)
        painter.setPen(QPen(inner_pen, 1.0))
        painter.drawRoundedRect(inner, radius - 4.0, radius - 4.0)

        shine = QLinearGradient(0, 0, 0, inner.height())
        shine.setColorAt(0.0, QColor(255, 255, 255, 18 if theme_manager.is_dark else 10))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        path = QPainterPath()
        path.addRoundedRect(inner, radius - 4.0, radius - 4.0)
        painter.fillPath(path, shine)

        if theme_manager.is_dark:
            painter.setPen(QPen(QColor(255, 255, 255, 22), 1.0))
            painter.drawRoundedRect(rect, radius, radius)

        if not theme_manager.is_dark:
            painter.setPen(QPen(QColor(90, 130, 210, 66), 1.0))
            painter.drawRoundedRect(rect.adjusted(0.6, 0.6, -0.6, -0.6), radius - 0.6, radius - 0.6)
