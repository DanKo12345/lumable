from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel

from app.panels.types import PanelHost
from app.widgets import GlassCard, StaticPopupComboBox
from app.widgets.themed_line_edit import ThemedLineEdit


def _row(host: PanelHost) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(host._sz(10))
    return row


def build_scenes_section(host: PanelHost) -> GlassCard:
    """Save the current look as a scene and recall it with one tap. Scenes are one
    model shared by the PC, the phone remote and the API. In 0.3.2 a scene applies
    to every connected strip; per-strip targeting arrives with BLE addressing in
    0.3.3, which is why there is no target/group selector here yet."""
    host.scenes_card = host._card(host._tr("scenes.title"), host._tr("scenes.subtitle"), icon="layers-3")

    # Save the current look under a name.
    save_row = _row(host)
    host.scenes_name_field = ThemedLineEdit()
    host.scenes_name_field.setPlaceholderText(host._tr("scenes.name_placeholder"))
    host.scenes_name_field.setMinimumWidth(host._sz(150))
    host.scenes_save_button = host._button(host._tr("scenes.save"), "accent_soft")
    save_row.addWidget(host.scenes_name_field, 1, Qt.AlignVCenter)
    save_row.addWidget(host.scenes_save_button, 0, Qt.AlignVCenter)
    host.scenes_card.content_layout.addLayout(save_row)

    # Pick a saved scene and apply or delete it.
    pick_row = _row(host)
    host.scenes_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.scenes_combo.setMinimumWidth(host._sz(150))
    host.scenes_apply_button = host._button(host._tr("scenes.apply"), "accent_soft")
    host.scenes_delete_button = host._button(host._tr("scenes.delete"), "ghost")
    pick_row.addWidget(host.scenes_combo, 1, Qt.AlignVCenter)
    pick_row.addWidget(host.scenes_apply_button, 0, Qt.AlignVCenter)
    pick_row.addWidget(host.scenes_delete_button, 0, Qt.AlignVCenter)
    host.scenes_card.content_layout.addLayout(pick_row)

    host.scenes_hint = QLabel(host._tr("scenes.hint"))
    host.scenes_hint.setObjectName("timerConnect")
    host.scenes_hint.setWordWrap(True)
    host.scenes_card.content_layout.addWidget(host.scenes_hint)

    return host.scenes_card
