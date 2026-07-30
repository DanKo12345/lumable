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

from collections.abc import Callable
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
from app.automation_rule_form import (
    CHOICE_POWER_OFF,
    CHOICE_POWER_ON,
    CHOICE_SCENE,
    PROBLEM_CODES,
    blank_form,
    form_to_rule,
    new_rule_id,
    rule_to_form,
)
from app.feature_gate import can_use
from app.panels.list_rows import BTN_H, BTN_W, divider, list_row
from app.widgets.profile_action_overlay import ProfileConfirmOverlay
from app.widgets.rule_editor_overlay import RuleEditorOverlay

# How often the pause row re-reads the shared state while the page is on screen. A
# pause runs out on its own and a pending one lands on a later tick of the engine,
# neither of which announces itself — but both are read off disk, so this only runs
# while there is somebody looking at it.
REFRESH_MS = 5000

# The per-row edit button. Narrower than the on/off column: it carries one short
# word, and the row still has to fit the smallest window the app supports.
EDIT_W = 88

# Trigger kinds and the short label each is offered under in the editor. The full
# sentences (``automations.trigger_*``) describe a rule that exists; a combo item
# has to read as a choice.
_TRIGGER_CHOICE_KEYS = (
    (TRIGGER_TIME, "time"),
    (TRIGGER_APP_FOREGROUND, "app"),
    (TRIGGER_NO_INPUT, "idle"),
    (TRIGGER_LUMABLE_START, "start"),
    (TRIGGER_STRIP_CONNECTED, "connected"),
    (TRIGGER_ALWAYS, "always"),
)

# One tile per trigger kind: the row reads before the text does. Any kind added to
# the schema later falls back rather than crashing on a missing glyph.
_TRIGGER_TILES = {
    TRIGGER_TIME: ("schedule", "#8fbfff"),
    TRIGGER_APP_FOREGROUND: ("app-window", "#78a7ff"),
    TRIGGER_NO_INPUT: ("moon", "#8f9bff"),
    TRIGGER_LUMABLE_START: ("power", "#72c7b7"),
    TRIGGER_STRIP_CONNECTED: ("device", "#72c7b7"),
    TRIGGER_ALWAYS: ("circle-dot", "#a9b0bd"),
}
_FALLBACK_TILE = ("workflow", "#a9b0bd")

# How many journal entries the card shows. The file keeps 300; a screen that listed
# them all would be a log viewer, and the question this card answers — "what did it
# just do, and why not" — is answered by the most recent handful.
JOURNAL_LIMIT = 20

# One tile per outcome. Cancelled is deliberately not red: the user taking over is
# not a fault, and a journal that paints it as one teaches them to ignore the real
# failures next to it.
_JOURNAL_TILES = {
    "success": ("circle-play", "#72c7b7"),
    "skipped": ("circle-dot", "#a9b0bd"),
    "error": ("power", "#ff8f8f"),
    "cancelled": ("moon", "#8fbfff"),
}

# The four pause states, drawn four ways. The two amber ones are the states where
# this app and the machine disagree; they share the colour of "not settled yet" and
# differ in glyph and wording.
_PAUSE_TILES = {
    PAUSE_OFF: ("circle-play", "#72c7b7"),
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


def entry_headline(entry: Any, tr: Any, rule_name: str = "") -> str:
    """Whose line this is: the rule's current name, or that it is gone.

    A journal outlives the rules it describes — that is most of its value — so an
    entry for a deleted rule has to say something rather than render blank.
    """
    if rule_name:
        return rule_name
    return tr("automations.journal_unknown_rule")


def entry_outcome(entry: Any, tr: Any) -> str:
    """What happened, from the stored code.

    Codes are stable and untranslated on disk, which is what lets the journal
    survive a language change. An unknown one — written by a newer build, or by a
    path added since — falls back to its kind rather than to nothing: "Skipped" with
    no reason is poor, and a blank line is a bug the user has to report to explain.
    """
    code = str(getattr(entry, "message_code", "") or getattr(entry, "reason", "") or "")
    if code:
        text = tr(f"automations.journal_code_{code}")
        if not text.startswith("automations.journal_code_"):
            return text
    kind = str(getattr(entry, "kind", ""))
    fallback = tr(f"automations.journal_kind_{kind}")
    if fallback.startswith("automations.journal_kind_"):
        # Neither the code nor the kind is known. The raw code is ugly and it is
        # also the only true thing left to say.
        return code or kind
    return fallback


def entry_when(entry: Any, tr: Any, *, now: datetime | None = None) -> str:
    """The time, and the date as well when it was not today.

    Numeric, not a month name: this line is read next to a rule's own times, and a
    localised month would be the only prose in a column of clocks.
    """
    moment = getattr(entry, "last_seen", None) or getattr(entry, "first_seen", None)
    if not isinstance(moment, datetime):
        return ""
    today = (now or datetime.now()).date()
    if moment.date() == today:
        return moment.strftime("%H:%M")
    return moment.strftime("%d.%m %H:%M")


def entry_detail(entry: Any, tr: Any, *, now: datetime | None = None) -> str:
    """When, what, and how many times — one line under the rule's name."""
    parts = [part for part in (entry_when(entry, tr, now=now), entry_outcome(entry, tr)) if part]
    count = int(getattr(entry, "count", 1) or 1)
    if count > 1:
        # Repeats of one skip are collapsed on the way in, so the count is the only
        # thing saying this happened all evening rather than once.
        parts.append(tr("automations.journal_repeat", count=count))
    return " · ".join(parts)


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

    def __init__(self, host: Any, *, clock: Callable[[], datetime] = datetime.now) -> None:
        self._host = host
        # Injectable so a test can walk the screen past midnight, which is the one
        # moment the history's own text changes with nothing else having happened.
        self._clock = clock
        self._rows: list[QWidget] = []
        # Parented to the window so it stops when the window is gone rather than
        # ticking against half-destroyed widgets.
        self._timer = QTimer(host)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._handoff_message = ""
        # One editor at a time, and the rule it is editing ("" for a new one).
        self._editor: RuleEditorOverlay | None = None
        self._editing_id = ""
        # What the journal looked like last time it was drawn, so a re-read that
        # found nothing new does not rebuild the rows underneath the user. None, not
        # (): an empty journal has an empty signature, and starting them equal would
        # skip the first draw — the one that hides the list and shows the hint.
        self._journal_signature: tuple | None = None

    def wire(self) -> None:
        host = self._host
        automations = host._automations
        host.automations_toggle_button.clicked.connect(self._toggle_enabled)
        host.automations_pause_button.clicked.connect(self._toggle_pause)
        host.automations_bridge_button.clicked.connect(self._start_handoff)
        host.automations_add_button.clicked.connect(self._add_rule)
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
        if self._editor is not None:
            self._editor.close_overlay()

    def sync_controls(self) -> None:
        self._sync_master()
        self._sync_pause()
        self._sync_tasks_note()
        self._rebuild_rules()
        self._rebuild_journal()
        self._sync_bridge()

    def relocalize(self) -> None:
        # Row text is generated from the rules, so the rows are rebuilt rather than
        # patched; the rest of the card is static text the localisation pass owns.
        # The journal is redrawn from the same entries, so its "nothing changed"
        # guard has to be cleared or the old language would stay on screen.
        self._journal_signature = None
        self.sync_controls()

    def _tick(self) -> None:
        card = getattr(self._host, "automations_card", None)
        if card is None or not card.isVisible():
            # Nobody is looking, and both of these live in files on disk.
            return
        self._sync_pause()
        # A rule carried out by a Windows task, or by this app while the page sat
        # open, writes to the journal without anything telling the screen. Nothing
        # announces it, so while the page is on screen it is re-read.
        self._rebuild_journal()

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

        # A button rather than a clickable row: a row is not a control, and a screen
        # reader has no way to be told otherwise without turning it into one.
        edit = host._button(host._tr("automations.edit_rule"), "ghost")
        edit.setFixedHeight(host._sz(BTN_H))
        edit.setMinimumWidth(host._sz(EDIT_W))
        edit.setAccessibleName(f"{host._tr('automations.edit_rule')}: {headline}")
        edit.clicked.connect(lambda _checked=False, rule_id=rule.id: self._edit_rule(rule_id))

        controls.addWidget(edit, 0, Qt.AlignVCenter)
        controls.addWidget(toggle, 0, Qt.AlignVCenter)
        self._rows.append(row)
        return row

    def _toggle_rule(self, rule_id: str, button: Any) -> None:
        if not self._host._automations.set_rule_enabled(rule_id, button.isChecked()):
            self.sync_controls()

    # ── the journal ───────────────────────────────────────────────────
    def _rebuild_journal(self) -> None:
        host = self._host
        layout = getattr(host, "automations_journal_layout", None)
        if layout is None:
            return
        entries = host._automations.journal(JOURNAL_LIMIT)
        now = self._clock()
        names = {rule.id: rule_headline(rule, host._tr, self._scene_name(rule)) for rule in host._automations.rules()}
        # Everything a row is drawn from, not just the entries. A rule renamed or
        # deleted leaves the journal untouched, so a signature made of entries alone
        # would keep the old name on screen until something else happened to run —
        # and the date, because at midnight every time in this list has to grow one.
        signature = (
            now.date(),
            tuple((entry.uid, entry.count, entry.last_seen) for entry in entries),
            tuple(sorted({(entry.rule_id, names.get(entry.rule_id, "")) for entry in entries})),
        )
        if signature == self._journal_signature:
            # Read every few seconds while the page is open: rebuilding an unchanged
            # list would throw away the user's scroll position for nothing.
            return
        self._journal_signature = signature

        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        host.automations_journal_empty.setVisible(not entries)
        host.automations_journal_list.setVisible(bool(entries))
        for index, entry in enumerate(entries):
            if index:
                layout.addWidget(divider(host))
            layout.addWidget(
                self._build_journal_row(entry, names.get(entry.rule_id, ""), now=now)
            )

    def _build_journal_row(self, entry: Any, rule_name: str, *, now: datetime) -> QWidget:
        host = self._host
        kind, tint = _JOURNAL_TILES.get(str(entry.kind), _FALLBACK_TILE)
        row, _controls, _title, status, _tile = list_row(
            host, kind, tint, entry_headline(entry, host._tr, rule_name)
        )
        status.setText(entry_detail(entry, host._tr, now=now))
        return row

    # ── the editor ────────────────────────────────────────────────────
    def _add_rule(self) -> None:
        self._open_editor(None)

    def _edit_rule(self, rule_id: str) -> None:
        rule = self._host._automations.rule(str(rule_id))
        if rule is None:
            # Deleted from under us — by another window, or by an edit that landed
            # while this row was on screen. Redrawing says so better than an editor
            # for something that is not there.
            self.sync_controls()
            return
        self._open_editor(rule)

    def _open_editor(self, rule: Rule | None) -> None:
        host = self._host
        if self._editor is not None:
            return  # one at a time: two editors would each save over the other
        form = blank_form() if rule is None else rule_to_form(rule)
        if rule is None:
            form["name"] = ""
        editor = RuleEditorOverlay(
            self._editor_labels(is_new=rule is None),
            form,
            scene_options=self._scene_options(),
            can_delete=rule is not None,
            background_unlocked=can_use("schedule"),
            parent=host,
        )
        self._editor = editor
        self._editing_id = "" if rule is None else rule.id
        editor.saved.connect(self._save_form)
        editor.delete_requested.connect(self._confirm_delete)
        editor.closed.connect(self._on_editor_closed)
        editor.open()

    def _on_editor_closed(self) -> None:
        self._editor = None
        self._editing_id = ""

    def _save_form(self, form: dict[str, Any]) -> None:
        """Hand the form to the facade, which is the only thing that may store it."""
        host = self._host
        editor = self._editor
        rule_id = self._editing_id or new_rule_id(rule.id for rule in host._automations.rules())
        saved = host._automations.save_rule(form_to_rule(form, rule_id=rule_id))
        if saved is None:
            # Either the schema refused it or the write failed. Nothing was stored, so
            # the editor stays open and says so: closing it would leave the user
            # believing they have a rule they do not.
            if editor is not None:
                editor.show_problem(host._tr("automations.save_failed"))
            return
        if editor is not None:
            editor.close_overlay()
        self.sync_controls()

    def _confirm_delete(self) -> None:
        """Ask before deleting. A rule is a thing the user built, not a selection."""
        host = self._host
        rule = host._automations.rule(self._editing_id)
        if rule is None:
            return
        name = rule_headline(rule, host._tr, self._scene_name(rule))
        confirm = ProfileConfirmOverlay(
            {
                "title": host._tr("automations.delete_title"),
                "message": host._tr("automations.delete_message", name=name),
                "cancel": host._tr("dialog.cancel"),
                "confirm": host._tr("automations.delete_confirm"),
            },
            host,
            confirm_role="danger",
        )
        confirm.confirmed.connect(lambda rule_id=rule.id: self._delete_rule(rule_id))
        confirm.open()

    def _delete_rule(self, rule_id: str) -> None:
        """Delete first, close after. The order is the whole point.

        Deleting is a settings write like any other and can fail — a busy lock, a
        file that will not take it. Closed first, a failure left the rule in place
        and the window gone: the user has confirmed a deletion, watched the editor
        disappear, and still has the rule. So the editor only goes once the rule
        has, and stays to say so when it has not.
        """
        editor = self._editor
        if self._host._automations.delete_rule(str(rule_id)):
            if editor is not None:
                editor.close_overlay()
            self.sync_controls()
            return
        if editor is not None:
            editor.show_problem(self._host._tr("automations.delete_failed"))
        self.sync_controls()

    def _scene_options(self) -> list[tuple[str, str]]:
        settings = getattr(self._host, "_settings", None)
        if not isinstance(settings, dict):
            return []
        return [
            (str(scene.get("scene_id", "")), str(scene.get("name", "")))
            for scene in scene_store.list_scenes(settings)
        ]

    def _editor_labels(self, *, is_new: bool) -> dict[str, str]:
        """Every string the editor shows, resolved here.

        The overlay takes wording rather than reaching for the localisation manager,
        the way the other overlays in this app do — which is what lets it be built in
        a test with a handful of strings and no i18n at all.
        """
        tr = self._host._tr
        labels = {
            "title": tr("automations.editor_new" if is_new else "automations.editor_edit"),
            "close": tr("automations.editor_close"),
            "name": tr("automations.field_name"),
            "name_placeholder": tr("automations.name_placeholder"),
            "trigger": tr("automations.field_trigger"),
            "time": tr("automations.field_time"),
            "days": tr("automations.field_days"),
            "app": tr("automations.field_app"),
            "app_placeholder": tr("automations.app_placeholder"),
            "idle": tr("automations.field_idle"),
            "idle_minutes": tr("automations.idle_minutes"),
            "action": tr("automations.field_action"),
            "scene": tr("automations.field_scene"),
            "scene_none": tr("automations.scene_none"),
            "background": tr("automations.field_background"),
            "background_hint": tr("automations.background_hint"),
            "background_pro_hint": tr("automations.background_pro_hint"),
            "pro": tr("common.pro_badge"),
            "advanced": tr("automations.advanced"),
            "priority": tr("automations.field_priority"),
            "cooldown": tr("automations.field_cooldown"),
            "on": tr("automations.toggle_on"),
            "off": tr("automations.toggle_off"),
            "save": tr("automations.save"),
            "cancel": tr("dialog.cancel"),
            "delete": tr("automations.delete"),
            "picker_hours": tr("time_picker.hours"),
            "picker_minutes": tr("time_picker.minutes"),
            "picker_ok": tr("dialog.ok"),
        }
        labels.update({f"day_{index}": tr(f"schedule.day_{index}") for index in range(7)})
        labels.update({f"trigger_{kind}": tr(f"automations.choice_{name}") for kind, name in _TRIGGER_CHOICE_KEYS})
        labels.update(
            {
                f"action_{CHOICE_SCENE}": tr("automations.choice_scene"),
                f"action_{CHOICE_POWER_ON}": tr("automations.action_power_on"),
                f"action_{CHOICE_POWER_OFF}": tr("automations.action_power_off"),
            }
        )
        labels.update({f"problem_{code}": tr(f"automations.problem_{code}") for code in PROBLEM_CODES})
        labels.update(
            {
                key: tr(key)
                for key in (
                    "automations.priority_low",
                    "automations.priority_normal",
                    "automations.priority_high",
                    "automations.priority_custom",
                    "automations.cooldown_none",
                    "automations.cooldown_minutes",
                    "automations.cooldown_seconds",
                )
            }
        )
        return labels

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
