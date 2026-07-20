"""A friendly empty-state block: icon tile + hint on a quiet solid backing.

A bare grey sentence reads like something is broken; this block makes "nothing
here yet" look intentional and points at the action that fills it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from app.panels.types import PanelHost
from app.widgets import IconTile


def empty_state(host: PanelHost, kind: str, tint: str, text: str) -> tuple[QWidget, QLabel]:
    """Build the block; returns (frame, label) — hide the frame, retext the label."""
    frame = QFrame()
    frame.setObjectName("emptyState")
    frame.setAttribute(Qt.WA_StyledBackground, True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(host._sz(14), host._sz(12), host._sz(14), host._sz(12))
    layout.setSpacing(host._sz(6))
    layout.addWidget(IconTile(kind, tint), 0, Qt.AlignHCenter)
    label = QLabel(text)
    label.setObjectName("emptyStateText")
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
    layout.addWidget(label)
    return frame, label
