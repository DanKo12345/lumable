from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.hotkeys import ACTIONS, SUGGESTED_HOTKEYS
from app.panels.list_rows import BTN_H, BTN_W, divider, list_container, list_row, plain_row
from app.panels.types import PanelHost
from app.widgets import GlassCard
from app.widgets.hotkey_capture_edit import HotkeyCaptureEdit


def build_hotkeys_section(host: PanelHost) -> GlassCard:
    host.hotkeys_card = host._card(
        host._tr("hotkeys.title"), host._tr("hotkeys.subtitle"), icon="keyboard"
    )
    host.hotkeys_card.setMinimumHeight(host._sz(250))

    hotkeys_list, list_layout = list_container(host)
    master_row, master_controls, _, _, _ = list_row(
        host, "keyboard", "#78a7ff", host._tr("hotkeys.title"), with_status=False
    )
    host.hotkeys_toggle_button = host._button(host._tr("hotkeys.toggle_off"), "ghost")
    host.hotkeys_toggle_button.setCheckable(True)
    host.hotkeys_toggle_button.setFixedSize(host._sz(BTN_W), host._sz(BTN_H))
    master_controls.addWidget(host.hotkeys_toggle_button, 0, Qt.AlignVCenter)
    list_layout.addWidget(master_row)
    list_layout.addWidget(divider(host))

    # One editable spec field per action; dims/disables while the feature is off.
    host.hotkeys_controls = QWidget()
    controls = QVBoxLayout(host.hotkeys_controls)
    controls.setContentsMargins(0, 0, 0, 0)
    controls.setSpacing(0)
    host.hotkey_inputs = {}
    host.hotkey_action_labels = {}
    host.hotkey_error_labels = {}
    for action in ACTIONS:
        row, row_layout, label = plain_row(host, host._tr(f"hotkeys.action.{action}"))
        field = HotkeyCaptureEdit()
        field.setObjectName("licenseKeyInput")
        field.setMinimumHeight(host._control_height)
        field.setMinimumWidth(host._sz(250))
        field.setMaximumWidth(host._sz(420))
        # A suggestion for an action that ships unassigned, shown the way every
        # placeholder is — greyed and gone the moment anything is typed, so it
        # cannot be mistaken for a combination the app has actually claimed.
        field.setPlaceholderText(
            SUGGESTED_HOTKEYS.get(action) or host._tr("hotkeys.capture_hint")
        )
        host.hotkey_inputs[action] = field

        # The message sits under its own field. A shared line, or a dialog,
        # would make one bad combination look like a problem with all of them —
        # and only this row changes height when something is wrong.
        error = QLabel()
        error.setObjectName("hotkeyError")
        error.setProperty("state", "error")
        error.setWordWrap(True)
        error.setMaximumWidth(host._sz(420))
        error.setVisible(False)
        host.hotkey_error_labels[action] = error

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(host._sz(4))
        column.addWidget(field)
        column.addWidget(error)

        host.hotkey_action_labels[action] = label
        row_layout.addLayout(column)
        controls.addWidget(row)
        if action != ACTIONS[-1]:
            controls.addWidget(divider(host))

    reset_row = QHBoxLayout()
    reset_row.setContentsMargins(0, host._sz(8), host._sz(14), host._sz(8))
    host.hotkeys_reset_button = host._button(host._tr("hotkeys.reset"), "ghost")
    reset_row.addStretch(1)
    reset_row.addWidget(host.hotkeys_reset_button)
    controls.addLayout(reset_row)

    list_layout.addWidget(host.hotkeys_controls)
    host.hotkeys_card.content_layout.addWidget(hotkeys_list)
    return host.hotkeys_card
