from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.panels.empty_state import empty_state
from app.panels.types import PanelHost
from app.widgets import GlassCard, StaticPopupComboBox
from app.widgets.themed_line_edit import ThemedLineEdit


def _row(host: PanelHost) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(host._sz(10))
    return row


def _section(host: PanelHost, title: str) -> tuple[QWidget, QVBoxLayout, QLabel]:
    section = QWidget()
    layout = QVBoxLayout(section)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(host._sz(8))
    heading = QLabel(title)
    heading.setObjectName("sceneFormHeading")
    layout.addWidget(heading)
    return section, layout, heading


def build_groups_section(host: PanelHost) -> GlassCard:
    """Name connected strips as one scene target."""
    host.groups_card = host._card(host._tr("groups.title"), host._tr("groups.subtitle"), icon="combine")

    host.groups_create_section, create_layout, host.groups_create_heading = _section(
        host, host._tr("groups.create_section")
    )
    host.groups_hint = QLabel(host._tr("groups.hint"))
    host.groups_hint.setObjectName("sceneHint")
    host.groups_hint.setWordWrap(True)
    create_layout.addWidget(host.groups_hint)

    # Connected strips are compact two-column choices. A single strip no longer
    # masquerades as a full-width text field, while long setups can still grow
    # vertically without introducing horizontal scrolling.
    host.groups_members_container = QFrame()
    host.groups_members_container.setObjectName("settingsList")
    host.groups_members_container.setAttribute(Qt.WA_StyledBackground, True)
    host.groups_members_layout = QGridLayout(host.groups_members_container)
    host.groups_members_layout.setContentsMargins(
        host._sz(8), host._sz(8), host._sz(8), host._sz(8)
    )
    host.groups_members_layout.setHorizontalSpacing(host._sz(8))
    host.groups_members_layout.setVerticalSpacing(host._sz(6))
    host.groups_members_layout.setColumnStretch(0, 1)
    host.groups_members_layout.setColumnStretch(1, 1)
    create_layout.addWidget(host.groups_members_container)

    host.groups_empty_state, host.groups_empty_label = empty_state(
        host, "combine", "#72c7b7", host._tr("groups.no_strips")
    )
    create_layout.addWidget(host.groups_empty_state)

    create_row = _row(host)
    host.groups_name_field = ThemedLineEdit()
    host.groups_name_field.setPlaceholderText(host._tr("groups.name_placeholder"))
    host.groups_name_field.setMinimumWidth(host._sz(150))
    host.groups_create_button = host._button(host._tr("groups.create"), "accent")
    host.groups_create_button.set_icon_kind("plus")
    create_row.addWidget(host.groups_name_field, 1, Qt.AlignVCenter)
    create_row.addWidget(host.groups_create_button, 0, Qt.AlignVCenter)
    create_layout.addLayout(create_row)
    host.groups_card.content_layout.addWidget(host.groups_create_section)

    separator = QFrame()
    separator.setObjectName("sceneDivider")
    separator.setFrameShape(QFrame.HLine)
    host.groups_card.content_layout.addWidget(separator)

    host.groups_saved_section, saved_layout, host.groups_saved_heading = _section(
        host, host._tr("groups.saved_section")
    )
    host.groups_manage_row = QWidget()
    manage_row = _row(host)
    host.groups_manage_row.setLayout(manage_row)
    host.groups_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.groups_combo.setMinimumWidth(host._sz(150))
    host.groups_delete_button = host._button("", "danger")
    host.groups_delete_button.set_icon_kind("trash-2")
    host.groups_delete_button.setIconSize(QSize(host._sz(17), host._sz(17)))
    host.groups_delete_button.setFixedSize(host._sz(42), host._sz(42))
    host.groups_delete_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    host.groups_delete_button.setAccessibleName(host._tr("groups.delete"))
    host.groups_delete_button.setToolTip(host._tr("groups.delete"))
    manage_row.addWidget(host.groups_combo, 1, Qt.AlignVCenter)
    manage_row.addWidget(host.groups_delete_button, 0, Qt.AlignVCenter)
    saved_layout.addWidget(host.groups_manage_row)

    host.groups_saved_empty = QLabel(host._tr("groups.empty"))
    host.groups_saved_empty.setObjectName("sceneHint")
    host.groups_saved_empty.setWordWrap(True)
    saved_layout.addWidget(host.groups_saved_empty)
    host.groups_card.content_layout.addWidget(host.groups_saved_section)

    return host.groups_card
