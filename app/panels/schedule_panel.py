from __future__ import annotations

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy

from app.constants import ACTION_SPACING, ROW_SPACING_TIGHT
from app.panels.types import PanelHost
from app.widgets import GlassCard, TimeButton
from app.widgets.clickable_label import ClickableLabel
from app.widgets.day_toggle import DayToggle


def build_schedule_section(host: PanelHost) -> GlassCard:
    host.schedule_card = host._card(host._tr("schedule.title"), host._tr("schedule.subtitle"), icon="schedule")
    host.schedule_card.setMinimumHeight(host._sz(180))

    # Pro badge shown when scheduling isn't unlocked (toggled by the controller).
    # Clicking it opens the Pro/license window, same as clicking the toggle.
    host.schedule_lock_label = ClickableLabel(host._tr("schedule.pro_locked"))
    host.schedule_lock_label.setObjectName("proBadge")
    host.schedule_lock_label.setStyleSheet(
        "QLabel#proBadge { background: rgba(143, 191, 255, 0.16); color: #9fc0ff;"
        " padding: 5px 12px; border-radius: 11px; }"
        "QLabel#proBadge:hover { background: rgba(143, 191, 255, 0.26); }"
    )
    host.schedule_lock_label.setCursor(Qt.PointingHandCursor)
    host.schedule_lock_label.clicked.connect(host._show_license_overlay)
    host.schedule_lock_label.hide()
    host.schedule_card.content_layout.addWidget(host.schedule_lock_label, 0, Qt.AlignLeft)

    row = QHBoxLayout()
    row.setSpacing(0)

    left = QHBoxLayout()
    left.setContentsMargins(0, 0, 0, 0)
    left.setSpacing(10)
    left.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.schedule_toggle_button = host._button(host._tr("schedule.toggle_off"), "ghost")
    host.schedule_toggle_button.setCheckable(True)
    host.schedule_toggle_button.setFixedSize(host._sz(86), host._sz(42))
    host.schedule_toggle_button.setToolTip(host._tr("schedule.toggle_hint"))
    host.schedule_startup_button = host._button(host._tr("schedule.startup_off"), "ghost")
    host.schedule_startup_button.setCheckable(True)
    host.schedule_startup_button.setFixedSize(host._sz(138), host._sz(42))
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

    # Day-of-week chips (Mon..Sun) — the schedule only fires on the selected days.
    days_row = QHBoxLayout()
    days_row.setContentsMargins(0, host._sz(4), 0, 0)
    days_row.setSpacing(host._sz(6))
    days_row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.schedule_day_buttons = []
    for index in range(7):
        chip = DayToggle(host._tr(f"schedule.day_{index}"), lambda: host._theme_tokens)
        chip.setFixedSize(host._sz(44), host._sz(34))
        host.schedule_day_buttons.append(chip)
        days_row.addWidget(chip)
    days_row.addStretch(1)
    host.schedule_card.content_layout.addLayout(days_row)

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
