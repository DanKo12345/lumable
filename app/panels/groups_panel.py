from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.panels.empty_state import empty_state
from app.panels.types import PanelHost
from app.widgets import GlassCard, StaticPopupComboBox
from app.widgets.themed_line_edit import ThemedLineEdit


def _row(host: PanelHost) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(host._sz(10))
    return row


def build_groups_section(host: PanelHost) -> GlassCard:
    """Name a set of connected strips so a scene can drive just those — e.g.
    "Desk" or "TV". Groups are referenced by a stable id, so renaming one never
    breaks the scenes that point at it."""
    host.groups_card = host._card(host._tr("groups.title"), host._tr("groups.subtitle"), icon="combine")

    # Pick the members: one toggle per connected strip, rebuilt from the live list.
    host.groups_members_container = QWidget()
    host.groups_members_layout = QVBoxLayout(host.groups_members_container)
    host.groups_members_layout.setContentsMargins(0, 0, 0, host._sz(4))
    host.groups_members_layout.setSpacing(host._sz(6))
    host.groups_card.content_layout.addWidget(host.groups_members_container)

    host.groups_empty_state, host.groups_empty_label = empty_state(
        host, "combine", "#72c7b7", host._tr("groups.no_strips")
    )
    host.groups_card.content_layout.addWidget(host.groups_empty_state)

    create_row = _row(host)
    host.groups_name_field = ThemedLineEdit()
    host.groups_name_field.setPlaceholderText(host._tr("groups.name_placeholder"))
    host.groups_name_field.setMinimumWidth(host._sz(150))
    host.groups_create_button = host._button(host._tr("groups.create"), "accent")
    create_row.addWidget(host.groups_name_field, 1, Qt.AlignVCenter)
    create_row.addWidget(host.groups_create_button, 0, Qt.AlignVCenter)
    host.groups_card.content_layout.addLayout(create_row)

    manage_row = _row(host)
    host.groups_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.groups_combo.setMinimumWidth(host._sz(150))
    host.groups_delete_button = host._button(host._tr("groups.delete"), "ghost")
    manage_row.addWidget(host.groups_combo, 1, Qt.AlignVCenter)
    manage_row.addWidget(host.groups_delete_button, 0, Qt.AlignVCenter)
    host.groups_card.content_layout.addLayout(manage_row)

    host.groups_hint = QLabel(host._tr("groups.hint"))
    host.groups_hint.setObjectName("timerConnect")
    host.groups_hint.setWordWrap(True)
    host.groups_card.content_layout.addWidget(host.groups_hint)

    return host.groups_card
