from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from app.theme import qcolor_from_token, theme_manager
from app.widgets.color_swatch import paint_color_tile

LUCIDE_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons" / "lucide"


class ProfileListDelegate(QStyledItemDelegate):
    _tile_cache: dict[tuple[int, int, int, bool, bool], QPixmap] = {}
    ACTION_SIZE = 22
    ACTION_GAP = 7

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(super().sizeHint(option, index).width(), 52)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        palette = theme_manager.palette
        is_dark = theme_manager.is_dark
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        row = QRectF(option.rect).adjusted(6.0, 5.0, -8.0, -5.0)
        radius = 13.0
        row_path = QPainterPath()
        row_path.addRoundedRect(row, radius, radius)

        if selected:
            fill_top = qcolor_from_token(palette["list_sel"])
            fill_top.setAlpha(66 if is_dark else 76)
            fill_bottom = QColor(fill_top)
            fill_bottom.setAlpha(38 if is_dark else 42)
        elif hovered:
            fill_top = qcolor_from_token(palette["list_hover"])
            fill_top.setAlpha(42 if is_dark else 44)
            fill_bottom = QColor(fill_top)
            fill_bottom.setAlpha(22 if is_dark else 26)
        else:
            fill_top = QColor(255, 255, 255, 10)
            fill_bottom = QColor(255, 255, 255, 3) if is_dark else QColor(255, 255, 255, 4)

        row_fill = QLinearGradient(row.left(), row.top(), row.left(), row.bottom())
        row_fill.setColorAt(0.0, fill_top)
        row_fill.setColorAt(1.0, fill_bottom)
        painter.fillPath(row_path, row_fill)

        edge = QColor(255, 255, 255, 14) if is_dark else QColor(100, 130, 210, 28)
        if hovered:
            edge = QColor(255, 255, 255, 30) if is_dark else QColor(100, 130, 210, 58)
        if selected:
            edge = qcolor_from_token(palette["accent_start"])
            edge.setAlpha(82 if is_dark else 112)
        painter.setPen(QPen(edge, 0.9))
        painter.drawPath(row_path)
        if selected:
            accent = qcolor_from_token(palette["accent_start"])
            accent.setAlpha(180 if is_dark else 210)
            accent_line = QRectF(row.left() + 1.0, row.top() + 8.0, 2.0, row.height() - 16.0)
            painter.setPen(Qt.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(accent_line, 1.0, 1.0)

        action_width = (self.ACTION_SIZE * 2 + self.ACTION_GAP + 8) if selected else 0
        text_rect = row.adjusted(18.0, 0.0, -(58.0 + action_width), 0.0)
        font = QFont(option.font)
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(qcolor_from_token(palette["text"]))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, index.data(Qt.DisplayRole) or "")

        profile = index.data(Qt.UserRole) or {}
        self._paint_color_tile(painter, row, profile, selected)
        if selected:
            self._paint_action_icon(painter, self.action_rect(option, "rename"), "pencil", self._is_action_hovered(index, "rename"))
            self._paint_action_icon(painter, self.action_rect(option, "delete"), "trash-2", self._is_action_hovered(index, "delete"))
        painter.restore()

    def _is_action_hovered(self, index, action: str) -> bool:
        view = self.parent()
        return (
            getattr(view, "_hover_action_row", -1) == index.row()
            and getattr(view, "_hover_action", "") == action
        )

    def action_rect(self, option: QStyleOptionViewItem, action: str) -> QRectF:
        row = QRectF(option.rect).adjusted(6.0, 5.0, -8.0, -5.0)
        tile_left = row.right() - 42.0 - 17.0
        delete_left = tile_left - self.ACTION_GAP - self.ACTION_SIZE
        rename_left = delete_left - self.ACTION_GAP - self.ACTION_SIZE
        left = rename_left if action == "rename" else delete_left
        return QRectF(left, row.center().y() - self.ACTION_SIZE / 2.0, self.ACTION_SIZE, self.ACTION_SIZE)

    def _paint_action_icon(self, painter: QPainter, rect: QRectF, kind: str, hovered: bool) -> None:
        renderer = QSvgRenderer(str(LUCIDE_ICON_DIR / f"{kind}.svg"))
        if not renderer.isValid():
            return
        background = qcolor_from_token(theme_manager.palette["surface_soft"])
        background.setAlpha(140 if hovered and theme_manager.is_dark else 178 if hovered else 92 if theme_manager.is_dark else 135)
        border = qcolor_from_token(theme_manager.palette["surface_border"])
        if hovered:
            border = qcolor_from_token(theme_manager.palette["accent_start"])
        border.setAlpha(132 if hovered else 72 if theme_manager.is_dark else 98)
        path = QPainterPath()
        path.addRoundedRect(rect, 8.0, 8.0)
        painter.fillPath(path, background)
        painter.setPen(QPen(border, 0.8))
        painter.drawPath(path)
        if hovered:
            glow = qcolor_from_token(theme_manager.palette["accent_start"])
            glow.setAlpha(42 if theme_manager.is_dark else 34)
            painter.fillPath(path, glow)

        icon_size = 14.0
        image = QPixmap(rect.size().toSize())
        image.fill(Qt.transparent)
        icon_painter = QPainter(image)
        icon_painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(icon_painter, QRectF(4.0, 4.0, icon_size, icon_size))
        icon_painter.end()

        tint = QPixmap(image.size())
        tint.fill(Qt.transparent)
        tint_painter = QPainter(tint)
        color = qcolor_from_token(theme_manager.palette["text"])
        color.setAlpha(220)
        tint_painter.fillRect(tint.rect(), color)
        tint_painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        tint_painter.drawPixmap(0, 0, image)
        tint_painter.end()
        painter.drawPixmap(rect.topLeft(), tint)

    def _paint_color_tile(self, painter: QPainter, row: QRectF, profile: dict, selected: bool) -> None:
        color_data = profile.get("color", {})
        color = QColor(
            int(color_data.get("r", 132)),
            int(color_data.get("g", 168)),
            int(color_data.get("b", 236)),
        )

        tile_width = 42
        tile_height = 30
        tile = QRectF(
            row.right() - tile_width - 17.0,
            row.center().y() - tile_height / 2.0,
            tile_width,
            tile_height,
        )
        key = (color.red(), color.green(), color.blue(), theme_manager.is_dark, selected)
        pixmap = self._tile_cache.get(key)
        if pixmap is None:
            pixmap = self._build_tile_pixmap(color, selected)
            self._tile_cache[key] = pixmap
        painter.drawPixmap(tile.toRect(), pixmap)

    def _build_tile_pixmap(self, color: QColor, selected: bool) -> QPixmap:
        pixmap = QPixmap(42, 30)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        border = QColor(255, 255, 255, 44 if theme_manager.is_dark else 78)
        if selected:
            border = qcolor_from_token(theme_manager.palette["accent_start"])
            border.setAlpha(118 if theme_manager.is_dark else 136)
        paint_color_tile(painter, QRectF(1.0, 1.0, 40.0, 28.0), color, border_color=border, selected=selected)
        painter.end()
        return pixmap
