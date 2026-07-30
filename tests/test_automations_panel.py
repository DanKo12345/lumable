"""The automations screen: the overview, the rule list, the pause and the handoff.

Two halves. The describers are pure functions of a rule and a translator, tested on
their own because what a row *says* is the part users read. The rest is the wiring,
tested against a fake facade rather than a real engine: the point of the facade is
that a screen cannot tell the difference, and a test that needed a Windows task
scheduler to check a button's label would be testing the wrong thing.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

pytest.importorskip("PySide6")

from automation_screen import make_rule
from PySide6.QtWidgets import QApplication, QLabel

from app.automation.controller import (
    PAUSE_ACTIVE,
    PAUSE_ENDING,
    PAUSE_OFF,
    PAUSE_PENDING,
)
from app.automation.rules import ALL_DAYS
from app.automation.windows_tasks import TaskSyncResult
from app.automation_ui_controller import (
    action_text,
    days_text,
    pause_text,
    rule_detail,
    rule_headline,
    tasks_text,
    trigger_text,
)
from app.localization import localization_manager
from app.widgets import LiquidButton


def _tr(key: str, **kwargs: object) -> str:
    return localization_manager.t(key, **kwargs)


@pytest.fixture(autouse=True)
def _english():
    """The assertions read the visible strings, so pin the language."""
    previous = localization_manager.language
    localization_manager.set_language("en")
    yield
    localization_manager.set_language(previous)


# ── describers ────────────────────────────────────────────────────────
def test_a_time_trigger_reads_as_a_time_and_its_days() -> None:
    rule = make_rule(trigger={"kind": "time", "time_at": "21:05", "days": [0, 2]})

    text = trigger_text(rule, _tr)

    assert "21:05" in text
    assert _tr("schedule.day_0") in text
    assert _tr("schedule.day_2") in text
    assert _tr("schedule.day_1") not in text


def test_all_seven_days_read_as_every_day_rather_than_a_list() -> None:
    assert days_text(ALL_DAYS, _tr) == _tr("automations.days_every")
    assert days_text((5, 6), _tr) == f"{_tr('schedule.day_5')}, {_tr('schedule.day_6')}"


def test_no_days_at_all_names_none_of_them() -> None:
    """An empty day list means no days — the schema is explicit that it is never a
    shorthand for daily — so the row must not claim "every day"."""
    assert days_text((), _tr) == ""


def test_every_trigger_kind_has_something_to_say() -> None:
    kinds = (
        {"kind": "time", "time_at": "07:00"},
        {"kind": "app_foreground", "app": "code.exe"},
        {"kind": "no_input", "minutes": 15},
        {"kind": "lumable_start"},
        {"kind": "strip_connected"},
        {"kind": "always"},
    )
    texts = [trigger_text(make_rule(trigger=kind), _tr) for kind in kinds]

    assert all(text and not text.startswith("automations.") for text in texts)
    assert len(set(texts)) == len(texts), "two triggers read the same"
    assert "code.exe" in texts[1]
    assert "15" in texts[2]


def test_a_scene_action_names_the_scene_and_says_when_it_is_gone() -> None:
    rule = make_rule(action={"type": "apply_scene", "scene_id": "s1"})

    assert "Evening" in action_text(rule, _tr, "Evening")
    # A rule pointing at a deleted scene must say so rather than render a blank
    # pair of quotes: it is the likeliest reason a rule stopped working.
    assert action_text(rule, _tr, "") == _tr("automations.action_scene_missing")


def test_a_power_action_says_which_way() -> None:
    on = action_text(make_rule(action={"type": "set_power", "power": True}), _tr)
    off = action_text(make_rule(action={"type": "set_power", "power": False}), _tr)

    assert on == _tr("automations.action_power_on")
    assert off == _tr("automations.action_power_off")
    assert on != off


def test_an_unnamed_rule_is_titled_by_what_it_does_and_not_repeated_below() -> None:
    rule = make_rule(name="")

    headline = rule_headline(rule, _tr)
    detail = rule_detail(rule, _tr)

    assert headline.startswith(_tr("automations.action_power_on"))
    assert headline not in detail, "the row said the same thing twice"
    assert "21:00" in detail


def test_two_unnamed_rules_with_the_same_command_are_told_apart_by_their_titles() -> None:
    """Migrated rules have no name — 0.3.5 never asked for one — and the schedule it
    came from is a pair of rules carrying the same command at two different times. A
    title of just the action would put "Switch the light off" in the list twice."""
    evening = make_rule(id="a", action={"type": "set_power", "power": False}, trigger={"kind": "time", "time_at": "23:30"})
    morning = make_rule(id="b", action={"type": "set_power", "power": False}, trigger={"kind": "time", "time_at": "07:15"})

    first, second = rule_headline(evening, _tr), rule_headline(morning, _tr)

    assert first != second
    assert "23:30" in first and "07:15" in second
    assert _tr("automations.action_power_off") in first


def test_a_rule_the_user_named_keeps_only_that_name() -> None:
    """They have already said what it is; a qualifier would be the app second-guessing
    the label its own user chose."""
    named = make_rule(name="Bedtime", trigger={"kind": "time", "time_at": "23:30"})

    assert rule_headline(named, _tr) == "Bedtime"


def test_an_app_or_idle_rule_is_qualified_by_what_makes_it_different() -> None:
    on_app = make_rule(trigger={"kind": "app_foreground", "app": "code.exe"})
    on_idle = make_rule(trigger={"kind": "no_input", "minutes": 20})
    # A trigger with nothing shorter than its own sentence is left alone: two rules
    # with the same action and this trigger are the same rule twice, not two.
    on_start = make_rule(trigger={"kind": "lumable_start"})

    assert "code.exe" in rule_headline(on_app, _tr)
    assert "20" in rule_headline(on_idle, _tr)
    assert rule_headline(on_start, _tr) == _tr("automations.action_power_on")


def test_a_named_rule_keeps_its_name_and_the_action_moves_below() -> None:
    rule = make_rule(name="Evening", action={"type": "apply_scene", "scene_id": "s1"})

    assert rule_headline(rule, _tr, "Warm") == "Evening"
    assert "Warm" in rule_detail(rule, _tr, "Warm")


def test_the_detail_line_says_whether_the_rule_needs_the_app_open() -> None:
    """The one thing about a rule that is not visible from its trigger, and the one
    users ask about: does this still happen when LumaBLE is closed?"""
    background = make_rule(execution="background")
    runtime = make_rule(execution="runtime")

    assert _tr("automations.runs_background") in rule_detail(background, _tr)
    assert _tr("automations.runs_runtime") in rule_detail(runtime, _tr)


# ── the four pause states ─────────────────────────────────────────────
def test_the_four_pause_states_say_four_different_things() -> None:
    ends_at = datetime(2026, 7, 30, 21, 30)
    texts = {
        status: pause_text(status, ends_at, _tr)
        for status in (PAUSE_OFF, PAUSE_ACTIVE, PAUSE_PENDING, PAUSE_ENDING)
    }

    headlines = [headline for headline, _hint in texts.values()]
    assert len(set(headlines)) == 4, "two pause states are indistinguishable"
    assert "21:30" in texts[PAUSE_ACTIVE][0]


def test_a_pause_the_machine_has_not_heard_about_is_not_shown_as_a_pause() -> None:
    """``pending`` means a Windows task could still switch the light. Showing it as
    an established pause — or naming the hour it ends — would be a promise the app
    cannot keep."""
    ends_at = datetime(2026, 7, 30, 21, 30)

    headline, hint = pause_text(PAUSE_PENDING, ends_at, _tr)

    assert headline != pause_text(PAUSE_ACTIVE, ends_at, _tr)[0]
    assert "21:30" not in headline
    assert hint, "the caveat has to be said, not implied by a colour"
    assert hint != headline


def test_resuming_while_the_machine_still_holds_the_pause_says_so() -> None:
    headline, hint = pause_text(PAUSE_ENDING, None, _tr)

    assert headline == _tr("automations.state_resume_pending")
    assert hint == _tr("automations.state_resume_pending_hint")


# ── the Windows task line ─────────────────────────────────────────────
def test_the_task_line_stays_quiet_until_something_has_been_attempted() -> None:
    assert tasks_text(None, _tr) == ""


def test_the_task_line_reports_what_windows_said() -> None:
    assert tasks_text(TaskSyncResult(available=False), _tr) == _tr("automations.tasks_unavailable")
    assert tasks_text(TaskSyncResult(), _tr) == _tr("automations.tasks_none")
    assert tasks_text(TaskSyncResult(unchanged=("rule-1",)), _tr) == _tr("automations.tasks_ok")

    failed = tasks_text(TaskSyncResult(errors=(("rule-1", "Access is denied"),)), _tr)
    assert "Access is denied" in failed


def test_a_result_that_is_being_replaced_is_never_shown_as_the_final_state() -> None:
    """"Windows is set up" and "Windows was set up for the rule you just replaced"
    are different claims, and the second must not be made in the first one's words."""
    settled = TaskSyncResult(unchanged=("rule-1",))

    assert tasks_text(settled, _tr) == _tr("automations.tasks_ok")
    assert tasks_text(settled, _tr, syncing=True) == _tr("automations.tasks_syncing")
    # Even a failure is superseded by a retry that is already under way.
    stale_error = TaskSyncResult(errors=(("rule-1", "Access is denied"),))
    assert tasks_text(stale_error, _tr, syncing=True) == _tr("automations.tasks_syncing")


# ── the wiring ────────────────────────────────────────────────────────
# ── the wiring ────────────────────────────────────────────────────────
def test_the_master_switch_shows_and_stores_the_stored_state(screen) -> None:
    host, _controller = screen
    assert host.automations_toggle_button.isChecked() is True

    host.automations_toggle_button.click()

    assert ("set_enabled", False) in host._automations.calls
    assert host.automations_toggle_button.isChecked() is False
    assert host.automations_toggle_button.text() == _tr("automations.toggle_off")


def test_a_master_switch_that_could_not_be_saved_goes_back(screen) -> None:
    """A settings write is a transaction that can fail. A toggle left where the user
    put it would show a state that is not stored anywhere."""
    host, _controller = screen
    host._automations.writes_land = False

    host.automations_toggle_button.click()

    assert host.automations_toggle_button.isChecked() is True


def test_each_pause_state_is_drawn_differently(screen) -> None:
    host, controller = screen
    host._automations.ends_at = datetime.now() + timedelta(minutes=42)

    looks: dict[str, tuple] = {}
    for status in (PAUSE_OFF, PAUSE_ACTIVE, PAUSE_PENDING, PAUSE_ENDING):
        host._automations.status = status
        controller.sync_controls()
        looks[status] = (
            host.automations_pause_tile.kind,
            host.automations_pause_tile._tint.name(),
            host.automations_pause_status.text(),
            host.automations_pause_button.text(),
        )

    assert len(set(looks.values())) == 4, "two pause states look the same"
    # The two states where the app and the machine disagree carry their caveat in
    # the row itself, not only in a colour.
    for status in (PAUSE_PENDING, PAUSE_ENDING):
        assert "\n" in looks[status][2]
    assert "\n" not in looks[PAUSE_ACTIVE][2]
    # A pending pause offers to lift it, an established one too; a resume that has
    # not landed still reads as running here, so the offer is to pause.
    assert looks[PAUSE_PENDING][3] == _tr("automations.resume_button")
    assert looks[PAUSE_ENDING][3] == _tr("automations.pause_button")


def test_the_pause_row_is_gone_when_there_is_nothing_to_pause(screen) -> None:
    host, controller = screen
    assert host.automations_pause_row.isHidden() is False

    host._automations.enabled = False
    controller.sync_controls()
    assert host.automations_pause_row.isHidden() is True
    assert host.automations_pause_divider.isHidden() is True

    host._automations.enabled = True
    host._automations.running = False  # the engine never came up
    controller.sync_controls()
    assert host.automations_pause_row.isHidden() is True


def test_a_pause_in_force_stays_liftable_with_automations_switched_off(screen) -> None:
    """The pause is machine-wide and outlives the session. Hiding the row with the
    master switch would leave the user holding a pause they cannot end — and finding
    it again, unexplained, the moment they switch automations back on."""
    host, controller = screen
    host._automations.status = PAUSE_ACTIVE
    host._automations.ends_at = datetime.now() + timedelta(minutes=30)
    host._automations.enabled = False
    controller.sync_controls()

    assert host.automations_pause_row.isHidden() is False
    assert host.automations_pause_button.text() == _tr("automations.resume_button")

    host.automations_pause_button.click()

    assert host._automations.calls[-1] == ("resume",)
    # Lifted, there is nothing left to pause and the row goes.
    assert host.automations_pause_row.isHidden() is True


def test_a_pause_survives_an_engine_that_never_came_up(screen) -> None:
    """Same case from the other side: the facade reads the durable pause state, so a
    window whose engine failed to start still shows it and still offers Resume."""
    host, controller = screen
    host._automations.running = False
    host._automations.status = PAUSE_ACTIVE
    host._automations.ends_at = datetime.now() + timedelta(minutes=30)
    controller.sync_controls()

    assert host.automations_pause_row.isHidden() is False
    assert host.automations_pause_button.text() == _tr("automations.resume_button")


def test_the_pause_button_asks_the_facade_and_reads_the_answer_back(screen) -> None:
    host, _controller = screen

    host.automations_pause_button.click()
    assert host._automations.calls[-1][0] == "pause"
    assert host.automations_pause_status.text() == pause_text(
        PAUSE_ACTIVE, host._automations.ends_at, _tr
    )[0]

    host.automations_pause_button.click()
    assert host._automations.calls[-1] == ("resume",)
    assert host.automations_pause_status.text() == _tr("automations.state_running")


def test_a_pause_that_only_reached_this_app_is_not_reported_as_paused(screen) -> None:
    """The facade answers "pending" when the machine could not be told. The row must
    follow the status it reads back, not the fact that a pause was asked for."""
    host, _controller = screen

    def pause(seconds: int = 3600) -> bool:
        host._automations.status = PAUSE_PENDING
        return False

    host._automations.pause = pause
    host.automations_pause_button.click()

    headline, hint = pause_text(PAUSE_PENDING, None, _tr)
    assert host.automations_pause_status.text() == f"{headline}\n{hint}"


def test_the_rule_list_draws_a_row_per_rule(screen) -> None:
    host, controller = screen
    host._automations.stored_rules = [
        make_rule(id="rule-1", name="Evening"),
        make_rule(id="rule-2", trigger={"kind": "app_foreground", "app": "code.exe"}),
    ]

    controller.sync_controls()

    assert host.automations_empty_hint.isHidden() is True
    titles = [row.findChildren(QLabel)[0].text() for row in controller._rows]
    assert titles == ["Evening", rule_headline(host._automations.rules()[1], _tr)]
    assert titles[1].startswith(_tr("automations.action_power_on"))


def test_an_empty_rule_list_explains_itself(screen) -> None:
    host, controller = screen
    host._automations.stored_rules = []

    controller.sync_controls()

    assert controller._rows == []
    assert host.automations_empty_hint.isHidden() is False
    assert host.automations_rules_list.isHidden() is True


def _row_toggle(controller, index: int) -> LiquidButton:
    """The on/off switch in a row — the checkable one; Edit sits beside it."""
    buttons = [
        button for button in controller._rows[index].findChildren(LiquidButton) if button.isCheckable()
    ]
    assert len(buttons) == 1
    return buttons[0]


def test_a_row_toggle_switches_that_rule(screen) -> None:
    host, controller = screen
    host._automations.stored_rules = [make_rule(id="rule-1"), make_rule(id="rule-2")]
    controller.sync_controls()

    _row_toggle(controller, 1).click()

    assert ("set_rule_enabled", "rule-2", False) in host._automations.calls
    # The write landed, so the list was rebuilt from it: the row now shows Off.
    rebuilt = _row_toggle(controller, 1)
    assert rebuilt.isChecked() is False
    assert rebuilt.text() == _tr("automations.toggle_off")


def test_a_row_toggle_that_could_not_be_saved_goes_back(screen) -> None:
    host, controller = screen
    host._automations.stored_rules = [make_rule(id="rule-1")]
    controller.sync_controls()
    host._automations.writes_land = False

    _row_toggle(controller, 0).click()

    assert _row_toggle(controller, 0).isChecked() is True


def test_the_task_note_follows_the_last_synchronisation(screen) -> None:
    host, _controller = screen
    assert host.automations_tasks_note.isHidden() is True  # nothing attempted yet

    host._automations.task_result = TaskSyncResult(errors=(("rule-1", "Access is denied"),))
    host._automations.tasks_synced.emit(host._automations.task_result)

    assert host.automations_tasks_note.isHidden() is False
    assert "Access is denied" in host.automations_tasks_note.text()


def test_the_note_says_it_is_working_from_the_moment_a_sync_is_asked_for(screen) -> None:
    """A rule edited while a reconciliation is out is not covered by the result that
    comes back from it. Between the edit and the second result the screen must say it
    is working — otherwise it claims Windows is set up for a rule whose task has not
    been written yet, and may still fail."""
    host, _controller = screen
    host._automations.task_result = TaskSyncResult(unchanged=("rule-1",))
    host._automations.tasks_synced.emit(host._automations.task_result)
    assert host.automations_tasks_note.text() == _tr("automations.tasks_ok")

    # The user edits a rule: a reconciliation is asked for and now one is owed.
    host._automations.syncing = True
    host._automations.tasks_sync_started.emit()
    assert host.automations_tasks_note.text() == _tr("automations.tasks_syncing")

    # The first (stale) result arrives while the rerun is still out — still working.
    host._automations.tasks_synced.emit(host._automations.task_result)
    assert host.automations_tasks_note.text() == _tr("automations.tasks_syncing")

    # Only the settled answer speaks for the machine.
    host._automations.syncing = False
    host._automations.task_result = TaskSyncResult(created=("rule-1",))
    host._automations.tasks_synced.emit(host._automations.task_result)
    assert host.automations_tasks_note.text() == _tr("automations.tasks_ok")


# ── the 0.3.5 bridge ──────────────────────────────────────────────────
def test_the_bridge_card_only_appears_while_there_is_something_to_hand_over(screen) -> None:
    host, controller = screen
    assert host.automations_bridge_card.isHidden() is True

    host._automations.bridge = True
    controller.sync_controls()
    assert host.automations_bridge_card.isHidden() is False


def test_the_handoff_button_says_it_is_working_and_declines_a_second_press(screen) -> None:
    """The work is several ``schtasks`` processes deep. A button that cannot say so
    looks broken at the moment it is busiest."""
    host, controller = screen
    host._automations.bridge = True
    controller.sync_controls()

    host.automations_bridge_button.click()

    assert host._automations.calls[-1] == ("complete_handoff",)
    assert host.automations_bridge_button.text() == _tr("automations.bridge_working")
    assert host.automations_bridge_button.isEnabled() is False


def test_a_failed_handoff_says_what_went_wrong_and_offers_to_try_again(screen) -> None:
    from app.automation.migration import HandoffResult

    host, controller = screen
    host._automations.bridge = True
    controller.sync_controls()
    host.automations_bridge_button.click()

    host._automations.handoff_running = False
    host._automations.handoff_finished.emit(HandoffResult(errors=(("handoff", "task in use"),)))

    assert host.automations_bridge_status.isHidden() is False
    assert "task in use" in host.automations_bridge_status.text()
    assert host.automations_bridge_button.isEnabled() is True
    assert host.automations_bridge_button.text() == _tr("automations.bridge_button")


def test_a_finished_handoff_is_said_out_loud_before_the_card_goes(screen) -> None:
    """The card disappears with the bridge, so the only place left to report success
    is the window's own status line."""
    from app.automation.migration import HandoffResult

    host, controller = screen
    host._automations.bridge = True
    controller.sync_controls()
    host.automations_bridge_button.click()

    host._automations.handoff_running = False
    host._automations.bridge = False  # the facade adopted the committed settings
    host._automations.handoff_finished.emit(HandoffResult(done=True))

    assert host.logged == [_tr("automations.bridge_done")]
    assert host.automations_bridge_card.isHidden() is True


# ── the refresh ───────────────────────────────────────────────────────
def test_the_pause_is_only_re_read_while_the_page_is_on_screen(screen) -> None:
    """A pause runs out on its own and a pending one lands on a later engine tick,
    neither of which announces itself — but both are read off disk, so the poll must
    stop when nobody is looking."""
    host, controller = screen
    reads: list[int] = []
    host._automations.pause_status = lambda: reads.append(1) or PAUSE_OFF

    controller._tick()  # the host was never shown
    assert reads == []

    host.show()
    QApplication.instance().processEvents()
    controller._tick()
    assert reads == [1]


def test_every_string_this_screen_shows_exists_in_every_language() -> None:
    """A missing key renders as the key itself, and the fallback would hide that in
    every language but Russian."""
    keys = [
        "nav.automations",
        "automations.title",
        "automations.subtitle",
        "automations.row_master",
        "automations.row_pause",
        "automations.toggle_on",
        "automations.toggle_off",
        "automations.state_running",
        "automations.state_paused",
        "automations.state_pause_pending",
        "automations.state_pause_pending_hint",
        "automations.state_resume_pending",
        "automations.state_resume_pending_hint",
        "automations.pause_button",
        "automations.resume_button",
        "automations.rules_title",
        "automations.rules_subtitle",
        "automations.empty_hint",
        "automations.runs_background",
        "automations.runs_runtime",
        "automations.trigger_time",
        "automations.trigger_app",
        "automations.trigger_idle",
        "automations.trigger_start",
        "automations.trigger_connected",
        "automations.trigger_always",
        "automations.days_every",
        "automations.action_power_on",
        "automations.action_power_off",
        "automations.action_scene",
        "automations.action_scene_missing",
        "automations.short_idle",
        "automations.tasks_syncing",
        "automations.tasks_ok",
        "automations.tasks_none",
        "automations.tasks_error",
        "automations.tasks_unavailable",
        "automations.bridge_title",
        "automations.bridge_hint",
        "automations.bridge_button",
        "automations.bridge_working",
        "automations.bridge_failed",
        "automations.bridge_done",
        # The editor.
        "automations.add_rule",
        "automations.edit_rule",
        "automations.editor_new",
        "automations.editor_edit",
        "automations.editor_close",
        "automations.field_name",
        "automations.name_placeholder",
        "automations.field_trigger",
        "automations.field_time",
        "automations.field_days",
        "automations.field_app",
        "automations.app_placeholder",
        "automations.field_idle",
        "automations.idle_minutes",
        "automations.field_action",
        "automations.field_scene",
        "automations.scene_none",
        "automations.field_background",
        "automations.background_hint",
        "automations.advanced",
        "automations.field_priority",
        "automations.field_cooldown",
        "automations.save",
        "automations.save_failed",
        "automations.delete",
        "automations.delete_failed",
        "automations.delete_title",
        "automations.delete_message",
        "automations.delete_confirm",
        "automations.choice_time",
        "automations.choice_app",
        "automations.choice_idle",
        "automations.choice_start",
        "automations.choice_connected",
        "automations.choice_always",
        "automations.choice_scene",
        "automations.problem_name",
        "automations.problem_time",
        "automations.problem_days",
        "automations.problem_app",
        "automations.problem_scene",
        "automations.problem_scene_missing",
        "automations.priority_low",
        "automations.priority_normal",
        "automations.priority_high",
        "automations.cooldown_none",
        "automations.cooldown_minutes",
        "automations.cooldown_seconds",
    ]
    for language in ("ru", "en", "es", "zh"):
        localization_manager.set_language(language)
        for key in keys:
            assert localization_manager.t(key) != key, f"{language} is missing {key}"


def test_switching_language_redraws_the_rows(screen) -> None:
    host, controller = screen
    host._automations.stored_rules = [make_rule(id="rule-1")]
    controller.sync_controls()
    english = host.automations_pause_status.text()

    localization_manager.set_language("ru")
    controller.relocalize()

    assert host.automations_pause_status.text() != english
    assert host.automations_toggle_button.text() == localization_manager.t("automations.toggle_on")
