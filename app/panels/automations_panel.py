"""The automations screen: what runs by itself, and what is holding it off.

Three cards, because they answer three different questions. The overview says
whether automations run at all and whether something is currently keeping them
quiet; the rules card lists what would run; the bridge card only appears while the
0.3.5 schedule tasks are still the ones doing the waking, and goes away for good
once they are retired.

The pause row is the one piece of chrome with a rule attached to it. There are four
pause states, not two, and two of them mean this app and the machine disagree — so
the row carries its own tile and tint per state and never presents "we have not
been able to tell Windows yet" as an established pause. Everything variable here is
filled in by :class:`app.automation_ui_controller.AutomationUiController`; this
module only builds the shapes.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel

from app.panels.list_rows import BTN_H, BTN_W, divider, list_container, list_row
from app.panels.types import PanelHost
from app.widgets import GlassCard

# The master switch keeps the accent hue of the section itself; the pause row is
# tinted per state by the controller, so its starting colour is only a placeholder.
_MASTER_TINT = "#b58fff"
_RUNNING_TINT = "#72c7b7"


def build_automations_section(host: PanelHost) -> GlassCard:
    """The overview: the master switch, the pause, and what Windows knows."""
    host.automations_card = host._card(
        host._tr("automations.title"), host._tr("automations.subtitle"), icon="orbit"
    )

    overview, layout = list_container(host)

    master_row, master_controls, host.automations_master_label, _, _ = list_row(
        host, "orbit", _MASTER_TINT, host._tr("automations.row_master"), with_status=False
    )
    host.automations_toggle_button = host._button(host._tr("automations.toggle_off"), "ghost")
    host.automations_toggle_button.setCheckable(True)
    host.automations_toggle_button.setFixedSize(host._sz(BTN_W), host._sz(BTN_H))
    # "On"/"Off" read out on its own says nothing about what it switches, and the
    # row's label is a separate QLabel the control cannot be reached from.
    host.automations_master_label.setBuddy(host.automations_toggle_button)
    host.automations_toggle_button.setAccessibleName(host._tr("automations.row_master"))
    master_controls.addWidget(host.automations_toggle_button, 0, Qt.AlignVCenter)
    layout.addWidget(master_row)

    host.automations_pause_divider = divider(host)
    layout.addWidget(host.automations_pause_divider)

    (
        host.automations_pause_row,
        pause_controls,
        host.automations_pause_label,
        host.automations_pause_status,
        host.automations_pause_tile,
    ) = list_row(host, "orbit", _RUNNING_TINT, host._tr("automations.row_pause"))
    host.automations_pause_button = host._button(host._tr("automations.pause_button"), "ghost")
    # Minimum rather than fixed: this button's label is a sentence, and it is a
    # different length in every language.
    host.automations_pause_button.setFixedHeight(host._sz(BTN_H))
    host.automations_pause_button.setMinimumWidth(host._sz(BTN_W))
    pause_controls.addWidget(host.automations_pause_button, 0, Qt.AlignVCenter)
    layout.addWidget(host.automations_pause_row)

    host.automations_card.content_layout.addWidget(overview)

    # What Windows has been told. Quiet by design: it matters when it goes wrong,
    # and the rest of the time it is reassurance rather than a control.
    host.automations_tasks_note = QLabel("")
    host.automations_tasks_note.setObjectName("cardSubtitle")
    host.automations_tasks_note.setWordWrap(True)
    host.automations_card.content_layout.addWidget(host.automations_tasks_note)
    return host.automations_card


def build_automation_rules_section(host: PanelHost) -> GlassCard:
    """The list of rules. Rows are built by the controller, from the rules."""
    host.automations_rules_card = host._card(
        host._tr("automations.rules_title"), host._tr("automations.rules_subtitle"), icon="layers-3"
    )

    host.automations_empty_hint = QLabel(host._tr("automations.empty_hint"))
    host.automations_empty_hint.setObjectName("cardSubtitle")
    host.automations_empty_hint.setWordWrap(True)
    host.automations_rules_card.content_layout.addWidget(host.automations_empty_hint)

    host.automations_rules_list, host.automations_rules_layout = list_container(host)
    host.automations_rules_card.content_layout.addWidget(host.automations_rules_list)
    return host.automations_rules_card


def build_automation_bridge_section(host: PanelHost) -> GlassCard:
    """The 0.3.5 handoff, shown only while there is something to hand over.

    Hidden from the start: on the vast majority of machines the bridge is not up,
    and a card explaining a migration that already happened would be noise.
    """
    host.automations_bridge_card = host._card(host._tr("automations.bridge_title"), icon="combine")

    host.automations_bridge_hint = QLabel(host._tr("automations.bridge_hint"))
    host.automations_bridge_hint.setObjectName("cardSubtitle")
    host.automations_bridge_hint.setWordWrap(True)
    host.automations_bridge_card.content_layout.addWidget(host.automations_bridge_hint)

    host.automations_bridge_status = QLabel("")
    host.automations_bridge_status.setObjectName("cardSubtitle")
    host.automations_bridge_status.setWordWrap(True)
    host.automations_bridge_status.hide()
    host.automations_bridge_card.content_layout.addWidget(host.automations_bridge_status)

    host.automations_bridge_button = host._button(host._tr("automations.bridge_button"), "accent_soft")
    host.automations_bridge_button.setFixedHeight(host._sz(BTN_H))
    host.automations_bridge_button.setMinimumWidth(host._sz(BTN_W))
    action_row = QHBoxLayout()
    action_row.setContentsMargins(0, 0, 0, 0)
    action_row.addStretch(1)
    action_row.addWidget(host.automations_bridge_button)
    host.automations_bridge_card.content_layout.addLayout(action_row)

    host.automations_bridge_card.hide()
    return host.automations_bridge_card
