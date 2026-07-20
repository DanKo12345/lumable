from __future__ import annotations

from PySide6.QtCore import Qt

from app.panels.list_rows import (
    BTN_H,
    BTN_W,
    CHIP_H,
    caption,
    control_group,
    divider,
    list_container,
    list_row,
)
from app.panels.types import PanelHost
from app.widgets import ColorSwatch, GlassCard, TimeButton

_TIME_W = 88       # HH:MM chip
_PILL_W = 84       # "30 мин" chip
_SWATCH = 24       # sunrise colour dot
_CTRL_W = 300      # caption + chips cluster, shared with the schedule card

# Each row is colour-coded by meaning, not by the current strip colour: a moon
# that turned amber with the LEDs would be noise instead of a signal.
_SLEEP_TINT = "#8f9bff"
_SUNRISE_TINT = "#ffb066"


def build_timers_section(host: PanelHost) -> GlassCard:
    host.timers_card = host._card(host._tr("timers.title"), host._tr("timers.subtitle"), icon="schedule")
    host.timers_card.setMinimumHeight(host._sz(176))
    timer_list, list_layout = list_container(host)

    # ── Sleep: fade the current colour to off over N minutes, then power off ──
    sleep_row, sleep_controls, host.timer_sleep_label, host.timer_sleep_status, sleep_tile = list_row(
        host, "moon", _SLEEP_TINT, host._tr("timers.sleep")
    )
    host.timer_sleep_row = sleep_row
    host.timer_sleep_tile = sleep_tile
    host.timer_sleep_after = caption(host._tr("timers.sleep_after"))
    host.timer_sleep_pill = host._pill("30")
    host.timer_sleep_pill.setFixedSize(host._sz(_PILL_W), host._sz(CHIP_H))
    host.timer_sleep_button = host._button(host._tr("timers.start"), "ghost")
    host.timer_sleep_button.setCheckable(True)
    host.timer_sleep_button.setFixedSize(host._sz(BTN_W), host._sz(BTN_H))
    sleep_box, sleep_box_layout = control_group(host, _CTRL_W, host.timer_sleep_after)
    sleep_box_layout.addWidget(host.timer_sleep_pill, 0, Qt.AlignVCenter)
    sleep_controls.addWidget(sleep_box, 0, Qt.AlignVCenter)
    sleep_controls.addWidget(host.timer_sleep_button, 0, Qt.AlignVCenter)
    list_layout.addWidget(sleep_row)
    list_layout.addWidget(divider(host))

    # ── Sunrise: one-shot alarm — ramp the target colour up to full at HH:MM ──
    sun_row, sun_controls, host.timer_sunrise_label, host.timer_sunrise_status, sun_tile = list_row(
        host, "sunrise", _SUNRISE_TINT, host._tr("timers.sunrise")
    )
    host.timer_sunrise_row = sun_row
    host.timer_sunrise_tile = sun_tile
    host.timer_sunrise_at = caption(host._tr("timers.sunrise_at"))
    host.timer_sunrise_time = TimeButton("07:00")
    host.timer_sunrise_time.set_picker_title(host._tr("timers.sunrise"))
    host.timer_sunrise_time.setFixedSize(host._sz(_TIME_W), host._sz(CHIP_H))
    host.timer_sunrise_pill = host._pill("20")
    host.timer_sunrise_pill.setFixedSize(host._sz(_PILL_W), host._sz(CHIP_H))
    host.timer_sunrise_swatch = ColorSwatch(lambda: host._theme_tokens)
    host.timer_sunrise_swatch.setFixedSize(_SWATCH, _SWATCH)
    host.timer_sunrise_swatch.setToolTip(host._tr("timers.pick_color"))
    host.timer_sunrise_button = host._button(host._tr("timers.arm"), "ghost")
    host.timer_sunrise_button.setCheckable(True)
    host.timer_sunrise_button.setFixedSize(host._sz(BTN_W), host._sz(BTN_H))
    sun_box, sun_box_layout = control_group(host, _CTRL_W, host.timer_sunrise_at)
    sun_box_layout.addWidget(host.timer_sunrise_time, 0, Qt.AlignVCenter)
    sun_box_layout.addWidget(host.timer_sunrise_pill, 0, Qt.AlignVCenter)
    sun_box_layout.addWidget(host.timer_sunrise_swatch, 0, Qt.AlignVCenter)
    sun_controls.addWidget(sun_box, 0, Qt.AlignVCenter)
    sun_controls.addWidget(host.timer_sunrise_button, 0, Qt.AlignVCenter)
    list_layout.addWidget(sun_row)

    host.timers_card.content_layout.addWidget(timer_list)
    return host.timers_card
