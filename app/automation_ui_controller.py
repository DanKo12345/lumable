"""The automations screen, wired to the facade and nothing else.

Everything this screen knows about automations comes through
:class:`app.automation.controller.AutomationController`. That is deliberate, and it
is enforced by a test: behind the facade are five subsystems with their own locks
and files, and a screen that reached past it would end up re-deciding what they have
already decided.

Two things are worth stating outright, because they are what the code is shaped
around:

* **The four pause states are four states.** ``pending`` means this app is holding
  automations off but the machine has not been told, so a Windows task could still
  switch the light; ``ending`` is the mirror. Both get their own tile, tint and
  wording, and neither is ever drawn as an established pause. Presenting them as one
  would be a promise the app cannot keep.
* **A control that could not be saved goes back where it was.** Every write here is
  a transaction that can fail — a busy settings lock, a read-only file — and the
  facade says so by returning False. A toggle left where the user put it after a
  failed write is the more comfortable lie and the one that costs them an evening.

The describers at the top are pure functions of a rule and a translator, so what a
row says can be tested without building a window.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget

from app import scene_store
from app.automation.controller import (
    ACTION_APPLY_SCENE,
    ALL_DAYS,
    PAUSE_ACTIVE,
    PAUSE_ENDING,
    PAUSE_OFF,
    PAUSE_PENDING,
    TRIGGER_ALWAYS,
    TRIGGER_APP_FOREGROUND,
    TRIGGER_LUMABLE_START,
    TRIGGER_NO_INPUT,
    TRIGGER_STRIP_CONNECTED,
    TRIGGER_TIME,
    Rule,
)
from app.panels.list_rows import BTN_H, BTN_W, divider, list_row

# How often the pause row re-reads the shared state while the page is on screen. A
# pause runs out on its own and a pending one lands on a later tick of the engine,
# neither of which announces itself — but both are read off disk, so this only runs
# while there is somebody looking at it.
REFRESH_MS = 5000

# One tile per trigger kind: the row reads before the text does. Any kind added to
# the schema later falls back rather than crashing on a missing glyph.
_TRIGGER_TILES = {
    TRIGGER_TIME: ("schedule", "#8fbfff"),
    TRIGGER_APP_FOREGROUND: ("app-window", "#78a7ff"),
    TRIGGER_NO_INPUT: ("moon", "#8f9bff"),
    TRIGGER_LUMABLE_START: ("power", "#72c7b7"),
    TRIGGER_STRIP_CONNECTED: ("device", "#72c7b7"),
    TRIGGER_ALWAYS: ("combine", "#a9b0bd"),
}
_FALLBACK_TILE = ("orbit", "#a9b0bd")

# The four pause states, drawn four ways. The two amber ones are the states where
# this app and the machine disagree; they share the colour of "not settled yet" and
# differ in glyph and wording.
_PAUSE_TILES = {
    PAUSE_OFF: ("orbit", "#72c7b7"),
    PAUSE_ACTIVE: ("moon", "#b58fff"),
    PAUSE_PENDING: ("moon", "#ffb066"),
    PAUSE_ENDING: ("sunrise", "#ffb066"),
}


# ── describers ────────────────────────────────────────────────────────────
def trigger_text(rule: Rule, tr: Any) -> str:
    """When this rule fires, in one phrase."""
    trigger = rule.trigger
    if trigger.kind == TRIGGER_TIME:
        return tr("automations.trigger_time", time=trigger.time_at, days=days_text(trigger.days, tr))
    if trigger.kind == TRIGGER_APP_FOREGROUND:
        return tr("automations.trigger_app", app=trigger.app)
    if trigger.kind == TRIGGER_NO_INPUT:
        return tr("automations.trigger_idle", minutes=trigger.minutes)
    if trigger.kind == TRIGGER_LUMABLE_START:
        return tr("automations.trigger_start")
    if trigger.kind == TRIGGER_STRIP_CONNECTED:
        return tr("automations.trigger_connected")
    return tr("automations.trigger_always")


def days_text(days: tuple[int, ...], tr: Any) -> str:
    """"every day", or the weekdays it actually runs on.

    All seven is spelled as "every day"; no days at all says so by naming none,
    which is the truth — the schema treats an empty list as no days, never as a
    shorthand for daily.
    """
    if tuple(days) == ALL_DAYS:
        return tr("automations.days_every")
    return ", ".join(tr(f"schedule.day_{day}") for day in days)


def action_text(rule: Rule, tr: Any, scene_name: str = "") -> str:
    """What this rule does. A missing scene is named as missing, not as blank."""
    if rule.action.type == ACTION_APPLY_SCENE:
        if not scene_name:
            return tr("automations.action_scene_missing")
        return tr("automations.action_scene", scene=scene_name)
    return tr("automations.action_power_on" if rule.action.power else "automations.action_power_off")


def trigger_hint(rule: Rule, tr: Any) -> str:
    """The shortest thing that tells two rules doing the same job apart.

    "" when the trigger has nothing to offer that is shorter than its own sentence —
    and for those kinds two rules with the same action are genuinely the same rule
    twice, so there would be nothing to disambiguate with anyway.
    """
    trigger = rule.trigger
    if trigger.kind == TRIGGER_TIME:
        return trigger.time_at
    if trigger.kind == TRIGGER_APP_FOREGROUND:
        return trigger.app
    if trigger.kind == TRIGGER_NO_INPUT:
        return tr("automations.short_idle", minutes=trigger.minutes)
    return ""


def rule_headline(rule: Rule, tr: Any, scene_name: str = "") -> str:
    """The row's title: the user's name for the rule, or what it does and when.

    Migrated rules have no name — the 0.3.5 schedule never asked for one — and two of
    them can carry the same command at different times. Titled by the action alone,
    "Switch the light off" would appear twice with nothing to choose between them but
    the small print. The qualifier is not added to a rule the user named: they have
    already said what it is.
    """
    if rule.name:
        return rule.name
    action = action_text(rule, tr, scene_name)
    hint = trigger_hint(rule, tr)
    return f"{action} · {hint}" if hint else action


def rule_detail(rule: Rule, tr: Any, scene_name: str = "") -> str:
    """The line under it: when it fires, what it does, and where it can run.

    The action is repeated here only when the title is the user's own name for the
    rule — otherwise the row would say the same thing twice.
    """
    parts = [trigger_text(rule, tr)]
    if rule.name:
        parts.append(action_text(rule, tr, scene_name))
    parts.append(
        tr("automations.runs_background" if rule.runs_in_background else "automations.runs_runtime")
    )
    return " · ".join(parts)


def pause_text(status: str, ends_at: datetime | None, tr: Any) -> tuple[str, str]:
    """Headline and, where one is owed, the caveat under it.

    ``pending`` and ``ending`` carry no time: naming an hour would read as a pause
    that has been established, which is exactly what those two states are not.
    """
    if status == PAUSE_ACTIVE:
        when = ends_at.strftime("%H:%M") if isinstance(ends_at, datetime) else ""
        return tr("automations.state_paused", time=when), ""
    if status == PAUSE_PENDING:
        return (
            tr("automations.state_pause_pending"),
            tr("automations.state_pause_pending_hint"),
        )
    if status == PAUSE_ENDING:
        return (
            tr("automations.state_resume_pending"),
            tr("automations.state_resume_pending_hint"),
        )
    return tr("automations.state_running"), ""


def tasks_text(result: Any, tr: Any, *, syncing: bool = False) -> str:
    """What Windows has been told, or "" while nothing has been attempted yet.

    ``syncing`` wins over whatever result is on hand. A reconciliation that is still
    owed means the result describes the rules as they were, and the difference is the
    whole point of the line: "set up" and "set up for the rule you just replaced" are
    not the same claim, and the second one must never be made in the first one's words.
    """
    if syncing:
        return tr("automations.tasks_syncing")
    if result is None:
        return ""
    if not getattr(result, "available", True):
        return tr("automations.tasks_unavailable")
    errors = tuple(getattr(result, "errors", ()))
    if errors:
        subject, detail = errors[0]
        return tr("automations.tasks_error", detail=detail or subject)
    if not (result.created or result.updated or result.unchanged or result.removed):
        return tr("automations.tasks_none")
    return tr("automations.tasks_ok")


class AutomationUiController:
    """Wires the automations screen: master switch, pause, rules, 0.3.5 handoff."""

    def __init__(self, host: Any) -> None:
        self._host = host
        self._rows: list[QWidget] = []
        # Parented to the window so it stops when the window is gone rather than
        # ticking against half-destroyed widgets.
        self._timer = QTimer(host)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._handoff_message = ""

    def wire(self) -> None:
        host = self._host
        automations = host._automations
        host.automations_toggle_button.clicked.connect(self._toggle_enabled)
        host.automations_pause_button.clicked.connect(self._toggle_pause)
        host.automations_bridge_button.clicked.connect(self._start_handoff)
        automations.changed.connect(self.sync_controls)
        automations.tasks_synced.connect(self._on_tasks_synced)
        # Both edges. Without the start, a rule edit would leave the previous result
        # on screen — as an answer about the rule it no longer describes.
        automations.tasks_sync_started.connect(self._sync_tasks_note)
        automations.handoff_started.connect(self._sync_bridge)
        automations.handoff_finished.connect(self._on_handoff_finished)
        # Opening the page must not wait for the next timer tick to show the truth.
        nav_button = getattr(host, "_nav_buttons", {}).get("automations")
        if nav_button is not None:
            nav_button.clicked.connect(self.sync_controls)
        self.sync_controls()
        self._timer.start()

    def stop(self) -> None:
        """Stop polling. Called when the window is going away."""
        self._timer.stop()

    def sync_controls(self) -> None:
        self._sync_master()
        self._sync_pause()
        self._sync_tasks_note()
        self._rebuild_rules()
        self._sync_bridge()

    def relocalize(self) -> None:
        # Row text is generated from the rules, so the rows are rebuilt rather than
        # patched; the rest of the card is static text the localisation pass owns.
        self.sync_controls()

    def _tick(self) -> None:
        card = getattr(self._host, "automations_card", None)
        if card is None or not card.isVisible():
            # Nobody is looking, and the pause state lives in files on disk.
            return
        self._sync_pause()

    # ── the master switch ─────────────────────────────────────────────
    def _toggle_enabled(self) -> None:
        wanted = self._host.automations_toggle_button.isChecked()
        if not self._host._automations.set_enabled(wanted):
            # The write did not land, so nothing changed. A successful write emits
            # ``changed`` and syncs by itself.
            self.sync_controls()

    def _sync_master(self) -> None:
        host = self._host
        enabled = host._automations.is_enabled()
        button = host.automations_toggle_button
        button.setChecked(enabled)
        button.setText(
            host._tr("automations.toggle_on" if enabled else "automations.toggle_off")
        )
        button.set_role("accent_soft" if enabled else "ghost")

    # ── the pause ─────────────────────────────────────────────────────
    def _toggle_pause(self) -> None:
        automations = self._host._automations
        if automations.pause_status() in (PAUSE_ACTIVE, PAUSE_PENDING):
            automations.resume()
        else:
            automations.pause()
        # Whether the machine was told is in the status, which is read back rather
        # than assumed from the return value.
        self._sync_pause()

    def _sync_pause(self) -> None:
        host = self._host
        automations = host._automations
        row = getattr(host, "automations_pause_row", None)
        if row is None:
            return
        status = automations.pause_status()
        # Two reasons to show the row, and the second one is the important one. With
        # the engine up there is something to pause. With it down — automations
        # switched off, or an engine that never came up — there is nothing to pause,
        # but a pause outlives the session it was set in, so as long as one is in
        # force the row stays and offers to lift it. Hiding it would leave the user
        # with a pause they cannot end without switching automations back on, only to
        # find the old pause waiting for them.
        visible = (automations.is_enabled() and automations.is_running()) or status != PAUSE_OFF
        row.setVisible(visible)
        host.automations_pause_divider.setVisible(visible)
        if not visible:
            return

        headline, hint = pause_text(status, automations.paused_until(), host._tr)
        kind, tint = _PAUSE_TILES.get(status, _FALLBACK_TILE)
        host.automations_pause_tile.set_kind(kind)
        host.automations_pause_tile.set_tint(tint)
        host.automations_pause_status.setText(f"{headline}\n{hint}" if hint else headline)

        paused = status in (PAUSE_ACTIVE, PAUSE_PENDING)
        button = host.automations_pause_button
        button.setText(
            host._tr("automations.resume_button" if paused else "automations.pause_button")
        )
        button.set_role("accent_soft" if paused else "ghost")
        button.setAccessibleName(f"{host._tr('automations.row_pause')}: {headline}")

    # ── the Windows tasks ─────────────────────────────────────────────
    def _on_tasks_synced(self, _result: Any = None) -> None:
        self._sync_tasks_note()

    def _sync_tasks_note(self) -> None:
        host = self._host
        note = getattr(host, "automations_tasks_note", None)
        if note is None:
            return
        text = tasks_text(
            host._automations.last_task_result(),
            host._tr,
            syncing=host._automations.tasks_syncing(),
        )
        note.setText(text)
        note.setVisible(bool(text))

    # ── the rules ─────────────────────────────────────────────────────
    def _rebuild_rules(self) -> None:
        host = self._host
        layout = getattr(host, "automations_rules_layout", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                # Deferred: this can run from the very toggle that was clicked.
                widget.deleteLater()
        self._rows = []

        rules = host._automations.rules()
        host.automations_empty_hint.setVisible(not rules)
        host.automations_rules_list.setVisible(bool(rules))
        for index, rule in enumerate(rules):
            if index:
                layout.addWidget(divider(host))
            layout.addWidget(self._build_row(rule))

    def _build_row(self, rule: Rule) -> QWidget:
        host = self._host
        scene_name = self._scene_name(rule)
        kind, tint = _TRIGGER_TILES.get(rule.trigger.kind, _FALLBACK_TILE)
        headline = rule_headline(rule, host._tr, scene_name)
        row, controls, title, status, _tile = list_row(host, kind, tint, headline)
        status.setText(rule_detail(rule, host._tr, scene_name))

        toggle = host._button(
            host._tr("automations.toggle_on" if rule.enabled else "automations.toggle_off"),
            "accent_soft" if rule.enabled else "ghost",
        )
        toggle.setCheckable(True)
        toggle.setChecked(rule.enabled)
        toggle.setFixedSize(host._sz(BTN_W), host._sz(BTN_H))
        # Same reason as the master switch: "On" alone names nothing.
        title.setBuddy(toggle)
        toggle.setAccessibleName(headline)
        toggle.clicked.connect(
            lambda _checked=False, rule_id=rule.id, button=toggle: self._toggle_rule(rule_id, button)
        )
        controls.addWidget(toggle, 0, Qt.AlignVCenter)
        self._rows.append(row)
        return row

    def _toggle_rule(self, rule_id: str, button: Any) -> None:
        if not self._host._automations.set_rule_enabled(rule_id, button.isChecked()):
            self.sync_controls()

    def _scene_name(self, rule: Rule) -> str:
        if rule.action.type != ACTION_APPLY_SCENE:
            return ""
        settings = getattr(self._host, "_settings", None)
        if not isinstance(settings, dict):
            return ""
        scene = scene_store.get_scene(settings, rule.action.scene_id)
        return str(scene.get("name", "")) if isinstance(scene, dict) else ""

    # ── the 0.3.5 bridge ──────────────────────────────────────────────
    def _start_handoff(self) -> None:
        self._handoff_message = ""
        # Answers on ``handoff_finished``; the card only has to stop inviting a
        # second one in the meantime.
        self._host._automations.complete_handoff()
        self._sync_bridge()

    def _on_handoff_finished(self, result: Any) -> None:
        if getattr(result, "done", False):
            # The card is about to disappear with the bridge, so the only place left
            # to say it worked is the status line.
            self._handoff_message = ""
            log = getattr(self._host, "_log", None)
            if callable(log):
                log(self._host._tr("automations.bridge_done"))
        else:
            errors = tuple(getattr(result, "errors", ()))
            detail = errors[0][1] if errors else ""
            self._handoff_message = self._host._tr("automations.bridge_failed", detail=detail)
        self._sync_bridge()

    def _sync_bridge(self) -> None:
        host = self._host
        card = getattr(host, "automations_bridge_card", None)
        if card is None:
            return
        active = host._automations.bridge_active()
        card.setVisible(active)
        if not active:
            return
        running = host._automations.handoff_in_progress()
        button = host.automations_bridge_button
        button.setEnabled(not running)
        button.setText(
            host._tr("automations.bridge_working" if running else "automations.bridge_button")
        )
        host.automations_bridge_hint.setText(host._tr("automations.bridge_hint"))
        host.automations_bridge_status.setText(self._handoff_message)
        host.automations_bridge_status.setVisible(bool(self._handoff_message))
