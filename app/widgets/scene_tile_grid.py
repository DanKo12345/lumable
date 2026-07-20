"""Saved scenes as an adaptive tile grid (Apple Home style).

Each tile shows the scene's colour, name and target; clicking (or Enter/Space)
applies it, the trailing "…" zone opens the tile's menu. The grid re-lays itself
out into 1–4 columns from its actual width, spacing included, so it degrades
gracefully on narrow windows and compact UI densities.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QGridLayout, QWidget

from app.theme import qcolor_from_token, theme_manager


@dataclass(frozen=True)
class SceneTileData:
    scene_id: str
    name: str
    color: str  # hex chip; empty string falls back to a neutral accent
    target_label: str


class SceneTile(QWidget):
    activated = Signal()
    menu_requested = Signal(QPoint)  # global position to anchor the menu at

    _FALLBACK_COLOR = "#8fbfff"
    _MENU_W = 26  # unscaled width of the trailing "…" hit zone

    def __init__(self, data: SceneTileData, ui_scale: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = data
        self._color = QColor(data.color or self._FALLBACK_COLOR)
        if not self._color.isValid():
            self._color = QColor(self._FALLBACK_COLOR)
        self._s = max(0.6, float(ui_scale))
        self._active = False
        self._hover = False
        self.setMinimumHeight(round(56 * self._s))
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"{data.name} — {data.target_label}")

    @property
    def scene_id(self) -> str:
        return self._data.scene_id

    def set_active(self, active: bool) -> None:
        active = bool(active)
        if active != self._active:
            self._active = active
            self.update()

    def is_active(self) -> bool:
        return self._active

    # ── input ─────────────────────────────────────────────────────────
    def _menu_zone(self) -> QRectF:
        width = self._MENU_W * self._s
        return QRectF(self.width() - width, 0.0, width, float(self.height()))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            if self._menu_zone().contains(event.position()):
                self.menu_requested.emit(event.globalPosition().toPoint())
            else:
                self.activated.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.menu_requested.emit(event.globalPos())
        event.accept()

    def event(self, ev):
        if ev.type() in (ev.Type.HoverEnter, ev.Type.HoverLeave):
            self._hover = ev.type() == ev.Type.HoverEnter
            self.update()
        return super().event(ev)

    # ── paint ─────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        s = self._s
        tokens = theme_manager.palette
        dark = theme_manager.is_dark
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = 13.0 * s
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        # Backing: neutral chip; the active tile takes a wash of its own colour.
        if self._active:
            wash = QColor(self._color)
            wash.setAlpha(52 if dark else 64)
            painter.fillPath(path, wash)
        else:
            painter.fillPath(path, qcolor_from_token(tokens["chip"]))
        if self._hover and not self._active:
            painter.fillPath(path, QColor(255, 255, 255, 14) if dark else QColor(22, 25, 31, 10))

        border = QColor(self._color) if self._active else qcolor_from_token(tokens["chip_border"])
        if self._active:
            border.setAlpha(170 if dark else 190)
        painter.setPen(QPen(border, 1.2 if self._active else 1.0))
        painter.drawRoundedRect(rect, radius, radius)

        if self.hasFocus():
            focus = qcolor_from_token(tokens["accent_start"])
            focus.setAlpha(200)
            painter.setPen(QPen(focus, 1.6))
            painter.drawRoundedRect(rect.adjusted(1.2, 1.2, -1.2, -1.2), radius - 1.2, radius - 1.2)

        # Colour swatch with a soft glow — the scene's light, not just a dot.
        cx = rect.left() + 22 * s
        cy = rect.center().y()
        glow = QRadialGradient(cx, cy, 18 * s)
        glow.setColorAt(0.0, QColor(self._color.red(), self._color.green(), self._color.blue(), 90))
        glow.setColorAt(1.0, QColor(self._color.red(), self._color.green(), self._color.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(cx - 18 * s, cy - 18 * s, 36 * s, 36 * s))
        painter.setBrush(self._color)
        dot_radius = 8.5 * s
        painter.drawEllipse(QRectF(cx - dot_radius, cy - dot_radius, dot_radius * 2, dot_radius * 2))
        painter.setPen(QPen(QColor(255, 255, 255, 70 if dark else 110), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(cx - dot_radius, cy - dot_radius, dot_radius * 2, dot_radius * 2))

        # "…" affordance on the right: the visible way into delete, so the
        # action isn't hidden behind right-click only.
        menu_w = self._MENU_W * s
        dots_color = qcolor_from_token(tokens["muted"])
        if self._hover:
            dots_color = qcolor_from_token(tokens["text_soft"])
        dots_x = rect.right() - menu_w / 2 - 4 * s
        dot_r = 1.6 * s
        painter.setPen(Qt.NoPen)
        painter.setBrush(dots_color)
        for offset in (-5 * s, 0.0, 5 * s):
            painter.drawEllipse(QRectF(dots_x + offset - dot_r, cy - dot_r, dot_r * 2, dot_r * 2))

        # Name + target, elided to the space left of the menu zone.
        text_left = rect.left() + 40 * s
        text_width = rect.right() - text_left - menu_w - 6 * s
        name_font = QFont(self.font())
        name_font.setPointSizeF(10.5 * s)
        name_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(name_font)
        painter.setPen(qcolor_from_token(tokens["text"]))
        metrics = painter.fontMetrics()
        painter.drawText(
            QRectF(text_left, rect.top() + 8 * s, text_width, metrics.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            metrics.elidedText(self._data.name, Qt.ElideRight, round(text_width)),
        )
        sub_font = QFont(self.font())
        sub_font.setPointSizeF(8.5 * s)
        sub_font.setWeight(QFont.Weight.Medium)
        painter.setFont(sub_font)
        painter.setPen(qcolor_from_token(tokens["muted"]))
        sub_metrics = painter.fontMetrics()
        painter.drawText(
            QRectF(text_left, rect.bottom() - 8 * s - sub_metrics.height(), text_width, sub_metrics.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            sub_metrics.elidedText(self._data.target_label, Qt.ElideRight, round(text_width)),
        )


class SceneTileGrid(QWidget):
    scene_activated = Signal(str)
    scene_menu_requested = Signal(str, QPoint)

    TILE_MIN = 168  # unscaled minimum tile width
    MAX_COLUMNS = 4

    def __init__(self, ui_scale: float = 1.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._s = max(0.6, float(ui_scale))
        self._tiles: list[SceneTile] = []
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(round(10 * self._s))

    def set_scenes(self, entries: list[SceneTileData], active_id: str = "") -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._tiles = []
        for entry in entries:
            tile = SceneTile(entry, self._s, self)
            tile.set_active(entry.scene_id == active_id)
            tile.activated.connect(lambda scene_id=entry.scene_id: self.scene_activated.emit(scene_id))
            tile.menu_requested.connect(
                lambda pos, scene_id=entry.scene_id: self.scene_menu_requested.emit(scene_id, pos)
            )
            self._tiles.append(tile)
        self._columns = 0  # force a fresh layout pass
        self._relayout(self._column_count(self.width()))

    def set_active(self, scene_id: str | None) -> None:
        for tile in self._tiles:
            tile.set_active(tile.scene_id == scene_id)

    def tiles(self) -> list[SceneTile]:
        return list(self._tiles)

    def _column_count(self, width: int) -> int:
        tile_min = self.TILE_MIN * self._s
        gap = self._grid.spacing()
        return max(1, min(self.MAX_COLUMNS, int((width + gap) // (tile_min + gap))))

    def _relayout(self, columns: int) -> None:
        if columns == self._columns and self._grid.count() == len(self._tiles):
            return
        self._columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for index, tile in enumerate(self._tiles):
            self._grid.addWidget(tile, index // columns, index % columns)
        for col in range(self.MAX_COLUMNS):
            self._grid.setColumnStretch(col, 1 if col < columns else 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout(self._column_count(self.width()))
