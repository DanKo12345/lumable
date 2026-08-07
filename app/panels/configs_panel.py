from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.constants import ROW_SPACING_TIGHT, ROW_TOP_MARGIN, SAVE_BUTTON_MIN_WIDTH
from app.panels.list_rows import Hairline
from app.panels.types import PanelHost
from app.widgets import GlassCard, ProfileListDelegate
from app.widgets.themed_line_edit import ThemedLineEdit

ACTION_SIZE = 38


class InlineProfileList(QListWidget):
    renameRequested = Signal()
    deleteRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._hover_action_row = -1
        self._hover_action = ""
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        row = self.row(item) if item is not None and item is self.currentItem() else -1
        action = self._action_at(item, event.position()) if item is not None and row >= 0 else ""
        if row != self._hover_action_row or action != self._hover_action:
            self._hover_action_row = row
            self._hover_action = action
            self.viewport().update()
            self.setCursor(Qt.PointingHandCursor if action else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        if item is not None and item is self.currentItem():
            action = self._action_at(item, event.position())
            if action == "rename":
                self.renameRequested.emit()
                return
            if action == "delete":
                self.deleteRequested.emit()
                return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_action_row = -1
        self._hover_action = ""
        self.unsetCursor()
        self.viewport().update()
        super().leaveEvent(event)

    def _action_at(self, item, position) -> str:
        if item is None:
            return ""
        row = QRectF(self.visualItemRect(item)).adjusted(6.0, 5.0, -8.0, -5.0)
        tile_left = row.right() - 36.0 - 17.0
        delete_left = tile_left - ProfileListDelegate.ACTION_GAP - ProfileListDelegate.ACTION_SIZE
        rename_left = delete_left - ProfileListDelegate.ACTION_GAP - ProfileListDelegate.ACTION_SIZE
        y = row.center().y() - ProfileListDelegate.ACTION_SIZE / 2.0
        rename_rect = QRectF(rename_left, y, ProfileListDelegate.ACTION_SIZE, ProfileListDelegate.ACTION_SIZE)
        delete_rect = QRectF(delete_left, y, ProfileListDelegate.ACTION_SIZE, ProfileListDelegate.ACTION_SIZE)
        if rename_rect.contains(position):
            return "rename"
        if delete_rect.contains(position):
            return "delete"
        return ""


def build_configs_section(host: PanelHost) -> GlassCard:
    host.configs_card = host._card(host._tr("configs.title"), host._tr("configs.subtitle"), icon="configs")
    host.configs_card.setMinimumHeight(host._sz(374))
    host.configs_card.subtitle_label.setMinimumHeight(0)
    host.configs_card.subtitle_label.setContentsMargins(0, 0, 0, 0)
    host.configs_card.content_layout.setContentsMargins(0, host._sz(8), 0, 0)
    host.configs_card.content_layout.setSpacing(host._sz(12))

    library, library_layout, host.configs_library_label, host.configs_library_hint = _section(
        host, "configs.library_title", "configs.library_hint"
    )
    config_top = QHBoxLayout()
    config_top.setSpacing(ROW_SPACING_TIGHT)
    config_top.setContentsMargins(0, ROW_TOP_MARGIN, 0, 0)
    host.profile_name = ThemedLineEdit()
    host.profile_name.setMinimumHeight(host._control_height)
    host.profile_name.setPlaceholderText(host._tr("configs.placeholder"))
    host.save_profile_button = host._button(host._tr("configs.save"), "accent_soft")
    host.save_profile_button.setMinimumWidth(SAVE_BUTTON_MIN_WIDTH)
    host.import_profiles_button = _icon_action(host, "upload", "configs.import_tooltip")
    host.export_profiles_button = _icon_action(host, "download", "configs.export_tooltip")
    host.configs_menu_button = _icon_action(host, "more-horizontal", "configs.menu")

    host.configs_reset_menu = QMenu(host.configs_card)
    host.reset_profiles_action = QAction(host._tr("configs.menu_reset"), host.configs_reset_menu)
    host.configs_reset_menu.addAction(host.reset_profiles_action)
    host.configs_menu_button.clicked.connect(
        lambda: host.configs_reset_menu.exec(host.configs_menu_button.mapToGlobal(QPoint(0, host.configs_menu_button.height())))
    )
    config_top.addWidget(host.profile_name, 1)
    config_top.addWidget(host.save_profile_button, 0, Qt.AlignVCenter)
    config_top.addWidget(host.import_profiles_button, 0, Qt.AlignVCenter)
    config_top.addWidget(host.export_profiles_button, 0, Qt.AlignVCenter)
    config_top.addWidget(host.configs_menu_button, 0, Qt.AlignVCenter)
    library_layout.addLayout(config_top)
    host.configs_card.content_layout.addWidget(library)
    host.configs_card.content_layout.addWidget(Hairline())

    saved, saved_layout, host.configs_saved_label, host.configs_saved_hint = _section(
        host, "configs.saved_title", "configs.saved_hint"
    )

    host.profile_list = InlineProfileList()
    host.profile_list.setObjectName("profileList")
    host.profile_list.setMinimumHeight(host._sz(236))
    host.profile_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    host.profile_list.verticalScrollBar().setSingleStep(18)
    host.profile_list.setUniformItemSizes(True)
    host.profile_list.setItemDelegate(ProfileListDelegate(host.profile_list))
    saved_layout.addWidget(host.profile_list)
    host.configs_card.content_layout.addWidget(saved)
    return host.configs_card


def _section(host: PanelHost, title_key: str, hint_key: str):
    section = QWidget()
    layout = QVBoxLayout(section)
    layout.setContentsMargins(host._sz(2), host._sz(2), host._sz(2), host._sz(2))
    layout.setSpacing(host._sz(6))

    title = QLabel(host._tr(title_key))
    title.setObjectName("sceneFormHeading")
    layout.addWidget(title)
    hint = QLabel(host._tr(hint_key))
    hint.setObjectName("cardSubtitle")
    hint.setWordWrap(True)
    hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    layout.addWidget(hint)
    return section, layout, title, hint


def _icon_action(host: PanelHost, icon: str, text_key: str):
    label = host._tr(text_key)
    button = host._button("", "ghost")
    button.set_icon_kind(icon)
    button.setIconSize(QSize(17, 17))
    button.setAccessibleName(label)
    button.setToolTip(label)
    button.setFixedSize(host._sz(ACTION_SIZE), host._sz(ACTION_SIZE))
    button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return button
