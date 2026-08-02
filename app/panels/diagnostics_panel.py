from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QTextEdit

from app.panels.list_rows import BTN_H, divider, list_container, list_row
from app.panels.types import PanelHost
from app.widgets import GlassCard

_LOG_TINT = "#78a7ff"
_SCAN_TINT = "#65d7ca"
_UPDATE_TINT = "#c69aff"


def build_diagnostics_section(host: PanelHost) -> GlassCard:
    host.diagnostics_card = host._card(
        host._tr("diagnostics.title"), host._tr("diagnostics.subtitle"), icon="diagnostics"
    )
    host.diagnostics_card.setMinimumHeight(host._sz(250))

    report_header = QHBoxLayout()
    report_header.setContentsMargins(0, host._sz(2), 0, 0)
    report_header.setSpacing(host._sz(8))
    host.diagnostics_report_label = QLabel(host._tr("diagnostics.report_section"))
    host.diagnostics_report_label.setObjectName("sceneFormHeading")
    report_header.addWidget(host.diagnostics_report_label, 0, Qt.AlignVCenter)
    report_header.addStretch(1)

    host.copy_diagnostics_button = _icon_action(
        host, "copy", host._tr("diagnostics.copy"), host._tr("diagnostics.support_hint")
    )
    host.export_diagnostics_button = _icon_action(
        host, "download", host._tr("diagnostics.export"), host._tr("diagnostics.support_hint")
    )
    host.report_device_button = host._button(host._tr("diagnostics.report"), "accent")
    host.report_device_button.set_icon_kind("send")
    host.report_device_button.setToolTip(host._tr("diagnostics.report_hint"))
    _prepare_text_action(host.report_device_button)
    report_header.addWidget(host.copy_diagnostics_button, 0, Qt.AlignVCenter)
    report_header.addWidget(host.export_diagnostics_button, 0, Qt.AlignVCenter)
    report_header.addWidget(host.report_device_button, 0, Qt.AlignVCenter)
    host.diagnostics_card.content_layout.addLayout(report_header)

    host.diagnostics_output = QTextEdit()
    host.diagnostics_output.setObjectName("diagnosticsOutput")
    host.diagnostics_output.setReadOnly(True)
    host.diagnostics_output.setMinimumHeight(host._sz(190))
    host.diagnostics_output.verticalScrollBar().setSingleStep(18)
    host.diagnostics_card.content_layout.addWidget(host.diagnostics_output)

    host.diagnostics_support_label = QLabel(host._tr("diagnostics.support_hint"))
    host.diagnostics_support_label.setObjectName("diagnosticsSupportHint")
    host.diagnostics_support_label.setWordWrap(True)
    host.diagnostics_support_label.hide()

    tools, tools_layout = list_container(host)
    host.diagnostics_tools_list = tools

    logs_row, logs_layout, host.diagnostics_logs_label, host.diagnostics_logs_hint, _ = list_row(
        host, "logs", _LOG_TINT, host._tr("diagnostics.logs_title")
    )
    assert host.diagnostics_logs_hint is not None
    host.diagnostics_logs_hint.setText(host._tr("diagnostics.logs_hint"))
    host.show_logs_button = host._button(host._tr("diagnostics.open"), "ghost")
    logs_layout.addWidget(host.show_logs_button, 0, Qt.AlignVCenter)
    tools_layout.addWidget(logs_row)
    tools_layout.addWidget(divider(host))

    scan_row, scan_layout, host.diagnostics_scan_label, host.diagnostics_scan_hint, _ = list_row(
        host, "diagnostics", _SCAN_TINT, host._tr("diagnostics.scan_title")
    )
    assert host.diagnostics_scan_hint is not None
    host.diagnostics_scan_hint.setText(host._tr("diagnostics.scan_hint"))
    host.export_scan_button = host._button(host._tr("diagnostics.save"), "ghost")
    host.export_scan_button.setToolTip(host._tr("scan_snapshot.export_hint"))
    scan_layout.addWidget(host.export_scan_button, 0, Qt.AlignVCenter)
    tools_layout.addWidget(scan_row)
    tools_layout.addWidget(divider(host))

    update_row, update_layout, host.diagnostics_update_label, host.diagnostics_update_hint, _ = list_row(
        host, "refresh-cw", _UPDATE_TINT, host._tr("diagnostics.updates_title")
    )
    assert host.diagnostics_update_hint is not None
    host.diagnostics_update_hint.setText(host._tr("diagnostics.updates_hint"))
    host.check_update_button = host._button(host._tr("updates.check"), "ghost")
    update_layout.addWidget(host.check_update_button, 0, Qt.AlignVCenter)
    tools_layout.addWidget(update_row)

    host.diagnostics_card.content_layout.addWidget(tools)
    resize_diagnostics_action_buttons(host)
    return host.diagnostics_card


def resize_diagnostics_action_buttons(host: PanelHost) -> None:
    icon_size = host._sz(42)
    for button in (host.copy_diagnostics_button, host.export_diagnostics_button):
        button.setFixedSize(icon_size, icon_size)

    _prepare_text_action(host.report_device_button)
    row_buttons = (host.show_logs_button, host.export_scan_button, host.check_update_button)
    width = max(_action_button_width(button) for button in row_buttons)
    for button in row_buttons:
        button.setFixedSize(width, host._sz(BTN_H))


def _icon_action(host: PanelHost, icon: str, accessible_name: str, tooltip: str):
    button = host._button("", "ghost")
    button.set_icon_kind(icon)
    button.setIconSize(QSize(17, 17))
    button.setAccessibleName(accessible_name)
    button.setToolTip(f"{accessible_name}\n{tooltip}")
    button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return button


def _prepare_text_action(button) -> None:
    button.setIconSize(QSize(14, 14))
    font = button.font()
    font.setPointSize(10)
    button.setFont(font)
    button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    button.setMinimumWidth(_action_button_width(button))


def _action_button_width(button) -> int:
    metrics = QFontMetrics(button.font())
    icon_extra = 0
    if getattr(button, "_icon_kind", ""):
        icon_extra = (button.iconSize().width() or 14) + 7
    return max(140, metrics.horizontalAdvance(button.text()) + icon_extra + 42)
