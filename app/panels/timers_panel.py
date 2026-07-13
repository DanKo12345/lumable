from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.panels.types import PanelHost
from app.widgets import ColorSwatch, GlassCard, TimeButton

_MODE_W = 82      # left column: mode name
_DESC_W = 168     # middle column: short description (fixed so controls share one X)
_BTN_W = 128      # right column: action button
_CHIP_H = 38      # duration / time chips — same height


def _mode_label(host: PanelHost, text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sliderLabel")
    label.setFixedWidth(host._sz(_MODE_W))
    return label


def _desc_label(host: PanelHost, text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("timerConnect")
    label.setFixedWidth(host._sz(_DESC_W))
    return label


def _block(host: PanelHost) -> tuple[QFrame, QHBoxLayout, QLabel]:
    """One rounded row block: a single controls row (mode / description / values /
    action button, all on one vertically-centred line) with a muted status line
    below it."""
    frame = QFrame()
    frame.setObjectName("timerBlock")
    frame.setAttribute(Qt.WA_StyledBackground, True)
    outer = QVBoxLayout(frame)
    outer.setContentsMargins(host._sz(14), host._sz(9), host._sz(14), host._sz(9))
    outer.setSpacing(host._sz(4))
    controls = QHBoxLayout()
    controls.setSpacing(host._sz(8))
    controls.setAlignment(Qt.AlignVCenter)
    status = QLabel("")
    status.setObjectName("timerStatus")
    outer.addLayout(controls)
    outer.addWidget(status)
    return frame, controls, status


def build_timers_section(host: PanelHost) -> GlassCard:
    host.timers_card = host._card(host._tr("timers.title"), host._tr("timers.subtitle"), icon="schedule")
    host.timers_card.setMinimumHeight(host._sz(180))

    # ── Sleep: fade the current colour to off over N minutes, then power off ──
    sleep_block, sleep_controls, host.timer_sleep_status = _block(host)
    host.timer_sleep_label = _mode_label(host, host._tr("timers.sleep"))
    host.timer_sleep_after = _desc_label(host, host._tr("timers.sleep_after"))
    host.timer_sleep_pill = host._pill("30")
    host.timer_sleep_pill.setFixedHeight(host._sz(_CHIP_H))
    host.timer_sleep_button = host._button(host._tr("timers.start"), "ghost")
    host.timer_sleep_button.setCheckable(True)
    host.timer_sleep_button.setFixedSize(host._sz(_BTN_W), host._sz(40))
    sleep_controls.addWidget(host.timer_sleep_label, 0, Qt.AlignVCenter)
    sleep_controls.addWidget(host.timer_sleep_after, 0, Qt.AlignVCenter)
    sleep_controls.addWidget(host.timer_sleep_pill, 0, Qt.AlignVCenter)
    sleep_controls.addStretch(1)
    sleep_controls.addWidget(host.timer_sleep_button, 0, Qt.AlignVCenter)
    host.timers_card.content_layout.addWidget(sleep_block)

    # ── Sunrise: one-shot alarm — ramp the target colour up to full at HH:MM ──
    sun_block, sun_controls, host.timer_sunrise_status = _block(host)
    host.timer_sunrise_label = _mode_label(host, host._tr("timers.sunrise"))
    host.timer_sunrise_at = _desc_label(host, host._tr("timers.sunrise_at"))
    host.timer_sunrise_time = TimeButton("07:00")
    host.timer_sunrise_time.set_picker_title(host._tr("timers.sunrise"))
    host.timer_sunrise_time.setFixedHeight(host._sz(_CHIP_H))
    host.timer_sunrise_pill = host._pill("20")
    host.timer_sunrise_pill.setFixedHeight(host._sz(_CHIP_H))
    host.timer_sunrise_swatch = ColorSwatch(lambda: host._theme_tokens)
    host.timer_sunrise_swatch.setFixedSize(26, 26)
    host.timer_sunrise_swatch.setToolTip(host._tr("timers.pick_color"))
    host.timer_sunrise_button = host._button(host._tr("timers.arm"), "ghost")
    host.timer_sunrise_button.setCheckable(True)
    host.timer_sunrise_button.setFixedSize(host._sz(_BTN_W), host._sz(40))
    sun_controls.addWidget(host.timer_sunrise_label, 0, Qt.AlignVCenter)
    sun_controls.addWidget(host.timer_sunrise_at, 0, Qt.AlignVCenter)
    sun_controls.addWidget(host.timer_sunrise_time, 0, Qt.AlignVCenter)
    # Keep the duration chip and its colour swatch tight together as one unit.
    chip_group = QHBoxLayout()
    chip_group.setSpacing(host._sz(5))
    chip_group.setAlignment(Qt.AlignVCenter)
    chip_group.addWidget(host.timer_sunrise_pill, 0, Qt.AlignVCenter)
    chip_group.addWidget(host.timer_sunrise_swatch, 0, Qt.AlignVCenter)
    sun_controls.addLayout(chip_group)
    sun_controls.addStretch(1)
    sun_controls.addWidget(host.timer_sunrise_button, 0, Qt.AlignVCenter)
    host.timers_card.content_layout.addWidget(sun_block)
    return host.timers_card
