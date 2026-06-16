from __future__ import annotations

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy

from app.constants import ACTION_SPACING, ROW_SPACING_TIGHT
from app.panels.types import PanelHost
from app.widgets import GlassCard, TimeButton


def build_schedule_section(host: PanelHost) -> GlassCard:
    host.schedule_card = host._card(host._tr("schedule.title"), icon="schedule")
    host.schedule_card.setMinimumHeight(118)
    host.schedule_card.layout().setContentsMargins(24, 4, 24, 18)
    host.schedule_card.header_widget.setMinimumHeight(38)
    host.schedule_card.header_widget.setMaximumHeight(38)
    host.schedule_card.title_label.setMinimumHeight(38)
    host.schedule_card.title_label.setMaximumHeight(38)
    host.schedule_card.title_label.setContentsMargins(0, 0, 0, 0)
    host.schedule_card.content_layout.setSpacing(8)
    host.schedule_card.content_layout.setContentsMargins(0, 12, 0, 0)

    row = QHBoxLayout()
    row.setSpacing(0)

    left = QHBoxLayout()
    left.setContentsMargins(0, 0, 0, 0)
    left.setSpacing(10)
    left.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.schedule_toggle_button = host._button(host._tr("schedule.toggle_off"), "ghost")
    host.schedule_toggle_button.setCheckable(True)
    host.schedule_toggle_button.setFixedSize(86, 42)
    host.schedule_toggle_button.setToolTip(host._tr("schedule.toggle_hint"))
    host.schedule_startup_button = host._button(host._tr("schedule.startup_off"), "ghost")
    host.schedule_startup_button.setCheckable(True)
    host.schedule_startup_button.setFixedSize(138, 42)
    host.schedule_startup_button.setToolTip(host._tr("schedule.startup_hint"))
    left.addWidget(host.schedule_toggle_button)
    left.addWidget(host.schedule_startup_button)

    times = QHBoxLayout()
    times.setContentsMargins(0, 0, 0, 0)
    times.setSpacing(ACTION_SPACING)
    times.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
    host.schedule_on_time = _time_group(host, times, "schedule.on", QTime(19, 0))
    host.schedule_off_time = _time_group(host, times, "schedule.off", QTime(23, 0))

    row.addLayout(left, 1)
    row.addLayout(times, 1)
    row.addStretch(1)
    host.schedule_card.content_layout.addLayout(row)

    host.schedule_runtime_note = QLabel(host._tr("schedule.runtime_note"))
    host.schedule_runtime_note.setObjectName("scheduleNote")
    host.schedule_runtime_note.setWordWrap(True)
    host.schedule_runtime_note.hide()
    return host.schedule_card


def _time_group(host: PanelHost, parent_layout: QHBoxLayout, label_key: str, default_time: QTime) -> TimeButton:
    group = QHBoxLayout()
    group.setSpacing(ROW_SPACING_TIGHT)
    group.setAlignment(Qt.AlignVCenter)
    label = QLabel(host._tr(label_key))
    label.setObjectName("sliderLabel")
    label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    editor = TimeButton(default_time.toString("HH:mm"))
    editor.set_picker_title(host._tr(label_key))
    group.addWidget(label)
    group.addWidget(editor)
    parent_layout.addLayout(group, 0)
    if label_key == "schedule.on":
        host.schedule_on_label = label
    else:
        host.schedule_off_label = label
    return editor
