from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.panels.empty_state import empty_state
from app.panels.types import PanelHost
from app.widgets import GlassCard, SceneTileGrid, StaticPopupComboBox
from app.widgets.themed_line_edit import ThemedLineEdit


def _row(host: PanelHost) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(host._sz(10))
    return row


def _section(host: PanelHost, title: str) -> tuple[QWidget, QVBoxLayout, QLabel]:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(host._sz(8))
    heading = QLabel(title)
    heading.setObjectName("sceneFormHeading")
    layout.addWidget(heading)
    return container, layout, heading


def build_scenes_section(host: PanelHost) -> GlassCard:
    """Save the current look as a scene and recall it with one tap. Scenes are one
    model shared by the PC, the phone remote and the API. Since 0.3.3 a scene
    carries a target — all strips, the main strip, or a group — so the selector
    here picks who the saved look is aimed at."""
    host.scenes_card = host._card(host._tr("scenes.title"), host._tr("scenes.subtitle"), icon="layers-3")

    # Creating a scene is one small, self-contained action: name it, decide
    # where it should apply, then save the current light state.
    host.scenes_create_section, create_layout, host.scenes_create_heading = _section(
        host, host._tr("scenes.create_section")
    )
    save_row = _row(host)
    host.scenes_name_field = ThemedLineEdit()
    host.scenes_name_field.setPlaceholderText(host._tr("scenes.name_placeholder"))
    host.scenes_name_field.setMinimumWidth(host._sz(150))
    host.scenes_save_button = host._button(host._tr("scenes.save"), "accent")
    save_row.addWidget(host.scenes_name_field, 1, Qt.AlignVCenter)
    save_row.addWidget(host.scenes_save_button, 0, Qt.AlignVCenter)
    create_layout.addLayout(save_row)

    # Which strips a newly saved scene should drive.
    target_row = _row(host)
    host.scenes_target_label = QLabel(host._tr("scenes.target_label"))
    host.scenes_target_label.setObjectName("sliderLabel")
    host.scenes_target_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.scenes_target_combo.setMinimumWidth(host._sz(150))
    target_row.addWidget(host.scenes_target_label, 0, Qt.AlignVCenter)
    target_row.addWidget(host.scenes_target_combo, 1, Qt.AlignVCenter)
    create_layout.addLayout(target_row)
    host.scenes_hint = QLabel(host._tr("scenes.hint"))
    host.scenes_hint.setObjectName("sceneHint")
    host.scenes_hint.setWordWrap(True)
    create_layout.addWidget(host.scenes_hint)
    host.scenes_card.content_layout.addWidget(host.scenes_create_section)

    divider = QFrame()
    divider.setObjectName("sceneDivider")
    divider.setFrameShape(QFrame.HLine)
    host.scenes_card.content_layout.addWidget(divider)

    # Saved scenes get their own block: a tile grid — one tap (or Enter) applies
    # a scene, the tile's "…" menu deletes it. No dropdown ceremony.
    host.scenes_saved_section, saved_layout, host.scenes_saved_heading = _section(
        host, host._tr("scenes.saved_section")
    )
    host.scenes_grid = SceneTileGrid(getattr(host, "_ui_scale", 1.0))
    saved_layout.addWidget(host.scenes_grid)
    host.scenes_empty_state, host.scenes_empty_label = empty_state(
        host, "layers-3", "#78a7ff", host._tr("scenes.empty")
    )
    saved_layout.addWidget(host.scenes_empty_state)
    host.scenes_card.content_layout.addWidget(host.scenes_saved_section)

    return host.scenes_card
