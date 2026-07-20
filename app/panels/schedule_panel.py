from __future__ import annotations

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app.panels.card_header import add_pro_badge
from app.panels.list_rows import (
    BTN_H,
    BTN_W,
    CHIP_H,
    divider,
    half_cell,
    list_container,
    list_row,
    v_divider,
)
from app.panels.types import PanelHost
from app.widgets import GlassCard, TimeButton
from app.widgets.day_toggle import DayToggle

_TIME_W = 88
_DAY_W = 44
_DAY_H = 34

# One hue per meaning: the schedule itself, lights-on, lights-off, and the
# neutral rows that only configure when it runs.
_MASTER_TINT = "#8fbfff"
_ON_TINT = "#ffb066"
_OFF_TINT = "#8f9bff"
_NEUTRAL_TINT = "#a9b0bd"


def build_schedule_section(host: PanelHost) -> GlassCard:
    host.schedule_card = host._card(host._tr("schedule.title"), host._tr("schedule.subtitle"), icon="schedule")
    host.schedule_card.setMinimumHeight(host._sz(180))
    host.schedule_lock_label = add_pro_badge(host, host.schedule_card, "schedule.pro_locked")

    schedule_list, list_layout = list_container(host)

    # ── Master switch: everything below only matters when this is on ──────────
    master_row, master_controls, host.schedule_master_label, host.schedule_master_status, _ = list_row(
        host, "power", _MASTER_TINT, host._tr("schedule.row_master")
    )
    host.schedule_row = master_row
    host.schedule_toggle_button = host._button(host._tr("schedule.toggle_off"), "ghost")
    host.schedule_toggle_button.setCheckable(True)
    host.schedule_toggle_button.setFixedSize(host._sz(BTN_W), host._sz(BTN_H))
    host.schedule_toggle_button.setToolTip(host._tr("schedule.toggle_hint"))
    master_controls.addWidget(host.schedule_toggle_button, 0, Qt.AlignVCenter)
    list_layout.addWidget(master_row)
    list_layout.addWidget(divider(host))

    # ── The two moments of the day, side by side: they are one decision ───────
    when_row = QWidget()
    when_layout = QHBoxLayout(when_row)
    when_layout.setContentsMargins(0, 0, 0, 0)
    when_layout.setSpacing(0)
    host.schedule_on_time, host.schedule_on_label, on_cell = _time_cell(
        host, "sun", _ON_TINT, "schedule.row_on", "schedule.pick_on", QTime(19, 0)
    )
    host.schedule_off_time, host.schedule_off_label, off_cell = _time_cell(
        host, "moon", _OFF_TINT, "schedule.row_off", "schedule.pick_off", QTime(23, 0)
    )
    when_layout.addWidget(on_cell, 1)
    when_layout.addWidget(v_divider(host))
    when_layout.addWidget(off_cell, 1)
    list_layout.addWidget(when_row)
    list_layout.addWidget(divider(host))

    # ── Day-of-week chips — seven of them, so they get the full width ─────────
    days_row, days_controls, host.schedule_days_label, _, _ = list_row(
        host, "calendar", _NEUTRAL_TINT, host._tr("schedule.row_days"), with_status=False
    )
    host.schedule_day_buttons = []
    # One tight group with an even gap: Mon…Sun should read as a sequence, not
    # as seven separate objects scattered across the card.
    chips_box = QWidget()
    chips_box.setObjectName("settingsControls")
    chips = QHBoxLayout(chips_box)
    chips.setContentsMargins(0, 0, 0, 0)
    chips.setSpacing(host._sz(6))
    for index in range(7):
        chip = DayToggle(host._tr(f"schedule.day_{index}"), lambda: host._theme_tokens)
        chip.setFixedSize(host._sz(_DAY_W), host._sz(_DAY_H))
        host.schedule_day_buttons.append(chip)
        chips.addWidget(chip, 0, Qt.AlignVCenter)
    days_controls.addWidget(chips_box, 0, Qt.AlignVCenter)
    list_layout.addWidget(days_row)
    list_layout.addWidget(divider(host))

    # ── Windows autostart: the only row that outlives the running app ─────────
    startup_row, startup_controls, host.schedule_startup_label, host.schedule_startup_status, _ = list_row(
        host, "settings", _NEUTRAL_TINT, host._tr("schedule.row_startup")
    )
    host.schedule_startup_status.setText(host._tr("schedule.startup_hint"))
    host.schedule_startup_button = host._button(host._tr("schedule.startup_off"), "ghost")
    host.schedule_startup_button.setCheckable(True)
    host.schedule_startup_button.setFixedSize(host._sz(BTN_W), host._sz(BTN_H))
    host.schedule_startup_button.setToolTip(host._tr("schedule.startup_hint"))
    startup_controls.addWidget(host.schedule_startup_button, 0, Qt.AlignVCenter)
    list_layout.addWidget(startup_row)

    host.schedule_card.content_layout.addWidget(schedule_list)

    host.schedule_runtime_note = QLabel(host._tr("schedule.runtime_note"))
    host.schedule_runtime_note.setObjectName("scheduleNote")
    host.schedule_runtime_note.setWordWrap(True)
    host.schedule_runtime_note.hide()
    return host.schedule_card


def _time_cell(
    host: PanelHost,
    kind: str,
    tint: str,
    title_key: str,
    picker_key: str,
    default_time: QTime,
) -> tuple[TimeButton, QLabel, QWidget]:
    cell, layout, title_label = half_cell(host, kind, tint, host._tr(title_key))
    editor = TimeButton(default_time.toString("HH:mm"))
    editor.set_picker_title(host._tr(picker_key))
    editor.setFixedSize(host._sz(_TIME_W), host._sz(CHIP_H))
    layout.addWidget(editor, 0, Qt.AlignVCenter)
    layout.addStretch(1)
    return editor, title_label, cell
