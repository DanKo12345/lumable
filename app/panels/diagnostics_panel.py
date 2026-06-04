from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QHBoxLayout, QTextEdit

from app.panels.types import PanelHost
from app.widgets import GlassCard


def build_diagnostics_section(host: PanelHost) -> GlassCard:
    host.diagnostics_card = host._card(host._tr("diagnostics.title"), host._tr("diagnostics.subtitle"), icon="diagnostics")
    host.diagnostics_card.setMinimumHeight(250)
    host.diagnostics_output = QTextEdit()
    host.diagnostics_output.setObjectName("diagnosticsOutput")
    host.diagnostics_output.setReadOnly(True)
    host.diagnostics_output.setMinimumHeight(200)
    host.diagnostics_output.verticalScrollBar().setSingleStep(18)
    host.diagnostics_card.content_layout.addWidget(host.diagnostics_output)

    button_row = QHBoxLayout()
    button_row.setContentsMargins(0, 2, 0, 0)
    button_row.setSpacing(10)
    button_row.addStretch(1)
    host.copy_diagnostics_button = host._button(host._tr("diagnostics.copy"), "ghost")
    host.copy_diagnostics_button.set_icon_kind("copy")
    _prepare_action_button(host.copy_diagnostics_button, 164)
    button_row.addWidget(host.copy_diagnostics_button)
    host.show_logs_button = host._button(host._tr("device.show_logs"), "ghost")
    host.show_logs_button.set_icon_kind("logs")
    _prepare_action_button(host.show_logs_button, 164)
    button_row.addWidget(host.show_logs_button)
    host.export_diagnostics_button = host._button(host._tr("diagnostics.export"), "ghost")
    host.export_diagnostics_button.set_icon_kind("download")
    _prepare_action_button(host.export_diagnostics_button, 196)
    button_row.addWidget(host.export_diagnostics_button)
    host.check_update_button = host._button(host._tr("updates.check"), "ghost")
    _prepare_action_button(host.check_update_button, 196)
    button_row.addWidget(host.check_update_button)

    host.diagnostics_card.content_layout.addLayout(button_row)
    return host.diagnostics_card


def _prepare_action_button(button, width: int) -> None:
    button.setMinimumWidth(width)
    button.setIconSize(QSize(14, 14))
    font = button.font()
    font.setPointSize(10)
    button.setFont(font)
