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
    row.setSpacing(10)
    host.schedule_toggle_button = host._button(host._tr("schedule.toggle_off"), "ghost")
    host.schedule_toggle_button.setCheckable(True)
    host.schedule_toggle_button.setFixedSize(86, 42)

    left_slot = QHBoxLayout()
    left_slot.setContentsMargins(0, 0, 0, 0)
    left_slot.addWidget(host.schedule_toggle_button, 0, Qt.AlignLeft | Qt.AlignVCenter)
    row.addLayout(left_slot, 1)

    time_slot = QHBoxLayout()
    time_slot.setContentsMargins(0, 0, 0, 0)
    time_slot.setSpacing(ACTION_SPACING)
    time_slot.setAlignment(Qt.AlignCenter)
    host.schedule_on_time = _time_group(host, time_slot, "schedule.on", QTime(19, 0))
    host.schedule_off_time = _time_group(host, time_slot, "schedule.off", QTime(23, 0))
    row.addLayout(time_slot, 0)

    row.addStretch(1)
    host.schedule_card.content_layout.addLayout(row)

    host.schedule_runtime_note = QLabel(host._tr("schedule.runtime_note"))
    host.schedule_runtime_note.setObjectName("scheduleNote")
    host.schedule_runtime_note.setWordWrap(True)
    host.schedule_runtime_note.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.schedule_runtime_note.setContentsMargins(0, 2, 0, 0)
    host.schedule_card.content_layout.addWidget(host.schedule_runtime_note)
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
