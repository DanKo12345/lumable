from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from app.constants import BODY_SPACING, ROOT_MARGINS, ROOT_SPACING, SECTION_SPACING
from app.hero_header import build_hero_header
from app.panels import (
    build_color_section,
    build_configs_section,
    build_device_section,
    build_diagnostics_section,
    build_effects_section,
    build_schedule_section,
)


def build_main_layout(host) -> QWidget:
    root = QWidget()
    root.setObjectName("rootWidget")
    root_layout = QVBoxLayout(root)
    root_layout.setContentsMargins(*ROOT_MARGINS)
    root_layout.setSpacing(ROOT_SPACING)

    host.content_shell = QWidget()
    host.content_shell.setObjectName("contentShell")
    host.content_shell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    shell_layout = QVBoxLayout(host.content_shell)
    shell_layout.setContentsMargins(0, 0, 0, 0)
    shell_layout.setSpacing(ROOT_SPACING)

    root_layout.addWidget(host.content_shell, 1, Qt.AlignHCenter)
    shell_layout.addWidget(build_hero_header(host))
    _build_body(host, shell_layout)
    return root


def _build_body(host, shell_layout: QVBoxLayout) -> None:
    host.body_scroll = QScrollArea()
    host.body_scroll.setWidgetResizable(True)
    host.body_scroll.setFrameShape(QFrame.NoFrame)
    host.body_scroll.setObjectName("bodyScroll")
    shell_layout.addWidget(host.body_scroll, 1)

    host.body_canvas = QWidget()
    host.body_canvas.setObjectName("bodyCanvas")
    host.body_scroll.setWidget(host.body_canvas)

    body_layout = QHBoxLayout(host.body_canvas)
    body_layout.setContentsMargins(0, 8, 0, 0)
    body_layout.setSpacing(BODY_SPACING)
    body_layout.setAlignment(Qt.AlignTop)

    left = QVBoxLayout()
    right = QVBoxLayout()
    left.setSpacing(SECTION_SPACING)
    right.setSpacing(SECTION_SPACING)
    left.setAlignment(Qt.AlignTop)
    right.setAlignment(Qt.AlignTop)
    body_layout.addLayout(left, 3)
    body_layout.addLayout(right, 2)

    left.addWidget(build_device_section(host))
    left.addWidget(build_color_section(host))
    left.addWidget(build_effects_section(host))

    right.addWidget(build_configs_section(host))
    right.addWidget(build_schedule_section(host))
    right.addWidget(build_diagnostics_section(host))
    right.addStretch(1)
    left.addStretch(1)
