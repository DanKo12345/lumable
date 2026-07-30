"""The history card: what the journal looks like once it is on screen.

The journal itself is covered in test_automation_journal. What is left here is the
reading of it — codes turned into sentences, a rule that has since been deleted, a
collapsed skip's count, and the fact that a page left open notices new entries
without anything telling it to.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytest.importorskip("PySide6")

from automation_screen import make_rule
from PySide6.QtWidgets import QApplication, QLabel

from app.automation.journal import (
    KIND_CANCELLED,
    KIND_ERROR,
    KIND_SKIPPED,
    KIND_SUCCESS,
    JournalEntry,
)
from app.automation_ui_controller import (
    JOURNAL_LIMIT,
    entry_detail,
    entry_headline,
    entry_outcome,
    entry_when,
)
from app.localization import localization_manager


def _tr(key: str, **kwargs: object) -> str:
    return localization_manager.t(key, **kwargs)


@pytest.fixture(autouse=True)
def _english():
    previous = localization_manager.language
    localization_manager.set_language("en")
    yield
    localization_manager.set_language(previous)


def _entry(**overrides: object) -> JournalEntry:
    now = datetime(2026, 7, 30, 21, 0, 5)
    data = {
        "id": 1,
        "kind": KIND_SUCCESS,
        "rule_id": "rule-1",
        "message_code": "power_set",
        "first_seen": now,
        "last_seen": now,
        "uid": "u1",
    }
    data.update(overrides)
    return JournalEntry(**data)


# ── reading an entry ──────────────────────────────────────────────────
def test_an_entry_is_titled_by_the_rule_it_belongs_to() -> None:
    assert entry_headline(_entry(), _tr, "Evening") == "Evening"


def test_an_entry_for_a_deleted_rule_still_says_something() -> None:
    """A journal outlives the rules it describes — that is most of its value — so an
    entry whose rule is gone must not render as a blank line."""
    assert entry_headline(_entry(), _tr, "") == _tr("automations.journal_unknown_rule")


def test_every_code_the_engine_writes_reads_as_a_sentence() -> None:
    """The journal stores stable codes so it survives a language change. Every code
    any of the three writers can produce therefore needs a line."""
    from app.automation import dispatcher, headless, resolver, task_sync

    codes = [
        dispatcher.CODE_SCENE_APPLIED,
        dispatcher.CODE_POWER_SET,
        dispatcher.CODE_EXECUTION_FAILED,
        dispatcher.CODE_TIMEOUT,
        dispatcher.CODE_SHUTDOWN,
        dispatcher.CODE_CANCELLED,
        dispatcher.CODE_PARTIAL,
        resolver.SKIP_PAUSED,
        resolver.SKIP_COOLDOWN,
        resolver.SKIP_OUTRANKED,
        resolver.SKIP_MISSING_SCENE,
        resolver.SKIP_DISCONNECTED,
        headless.SKIP_AUTOMATIONS_DISABLED,
        headless.SKIP_NO_BACKGROUND_RULES,
        headless.SKIP_NOTHING_DUE,
        headless.SKIP_BUSY,
        headless.CODE_NO_ADDRESS,
        headless.CODE_CONNECT_FAILED,
        task_sync.CODE_TASK_SYNC_FAILED,
        task_sync.CODE_SETTINGS_UNREADABLE,
    ]
    for language in ("ru", "en", "es", "zh"):
        localization_manager.set_language(language)
        for code in codes:
            text = entry_outcome(_entry(message_code=code), localization_manager.t)
            assert text and text != code, f"{language} has nothing to say about {code}"


def test_a_skip_is_read_from_its_reason() -> None:
    """Skips carry a reason where the other kinds carry a message code."""
    entry = _entry(kind=KIND_SKIPPED, message_code="", reason="disconnected")

    assert entry_outcome(entry, _tr) == _tr("automations.journal_code_disconnected")


def test_a_code_from_a_newer_build_falls_back_to_its_kind() -> None:
    """Better a line that says "Failed" than a blank the user has to report to
    explain. The raw code is the last resort, and still says more than nothing."""
    unknown = _entry(kind=KIND_ERROR, message_code="something_new_broke")

    assert entry_outcome(unknown, _tr) == _tr("automations.journal_kind_error")

    nameless = _entry(kind="invented_kind", message_code="also_new")
    assert entry_outcome(nameless, _tr) == "also_new"


def test_the_time_carries_a_date_only_when_it_is_not_today() -> None:
    """A column of clocks reads at a glance; a date on every line does not."""
    now = datetime(2026, 7, 30, 22, 0)
    today = _entry(last_seen=datetime(2026, 7, 30, 21, 5))
    yesterday = _entry(last_seen=datetime(2026, 7, 29, 21, 5))

    assert entry_when(today, _tr, now=now) == "21:05"
    assert entry_when(yesterday, _tr, now=now) == "29.07 21:05"


def test_a_collapsed_skip_says_how_many_times_it_happened() -> None:
    """Repeats fold into one row on the way in, so the count is the only thing
    saying this went on all evening rather than happening once."""
    once = _entry(kind=KIND_SKIPPED, message_code="", reason="disconnected")
    many = _entry(kind=KIND_SKIPPED, message_code="", reason="disconnected", count=12)

    assert _tr("automations.journal_repeat", count=12) in entry_detail(many, _tr)
    assert "12" not in entry_detail(once, _tr)


def test_the_detail_line_says_when_and_what() -> None:
    now = datetime(2026, 7, 30, 22, 0)
    detail = entry_detail(_entry(), _tr, now=now)

    assert "21:00" in detail
    assert _tr("automations.journal_code_power_set") in detail


# ── the card ──────────────────────────────────────────────────────────
def _pump() -> None:
    app = QApplication.instance() or QApplication([])
    for _ in range(3):
        app.processEvents()


def _journal_rows(controller) -> list[str]:
    layout = controller._host.automations_journal_layout
    rows = []
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if widget is not None and widget.objectName() == "settingsRow":
            rows.append(widget.findChildren(QLabel)[0].text())
    return rows


def test_the_card_explains_itself_while_nothing_has_run(screen) -> None:
    host, controller = screen

    controller.sync_controls()

    assert host.automations_journal_empty.isHidden() is False
    assert host.automations_journal_list.isHidden() is True


def test_the_card_lists_the_entries_newest_first(screen) -> None:
    host, controller = screen
    host._automations.stored_rules = [make_rule(id="rule-1", name="Evening")]
    host._automations.entries = [
        _entry(uid="u2", rule_id="rule-1", last_seen=datetime(2026, 7, 30, 21, 0)),
        _entry(uid="u1", rule_id="gone", kind=KIND_ERROR, message_code="connect_failed"),
    ]

    controller.sync_controls()

    assert host.automations_journal_empty.isHidden() is True
    assert _journal_rows(controller) == ["Evening", _tr("automations.journal_unknown_rule")]


def test_the_card_asks_for_a_handful_rather_than_the_whole_file(screen) -> None:
    """The file keeps 300 entries. A card that listed them all would be a log
    viewer, and the question it answers is "what just happened"."""
    host, controller = screen
    host._automations.entries = [_entry(uid=f"u{index}") for index in range(50)]

    controller.sync_controls()

    assert ("journal", JOURNAL_LIMIT) in host._automations.calls
    assert len(_journal_rows(controller)) == JOURNAL_LIMIT


def test_a_page_left_open_notices_a_rule_that_ran(screen) -> None:
    """Nothing announces a journal write — a Windows task's process does it in
    another process entirely — so an open page has to look again."""
    host, controller = screen
    host.show()
    _pump()
    controller.sync_controls()
    assert _journal_rows(controller) == []

    host._automations.entries = [_entry(uid="u9", rule_id="rule-1")]
    controller._tick()

    assert len(_journal_rows(controller)) == 1


def test_an_unchanged_journal_is_not_redrawn(screen) -> None:
    """It is re-read every few seconds while the page is open. Rebuilding rows that
    have not changed would throw away the user's scroll position for nothing."""
    host, controller = screen
    host.show()
    _pump()
    host._automations.entries = [_entry(uid="u1")]
    controller.sync_controls()
    first = controller._host.automations_journal_layout.itemAt(0).widget()

    controller._tick()

    assert controller._host.automations_journal_layout.itemAt(0).widget() is first


def test_a_new_occurrence_of_the_same_skip_is_redrawn(screen) -> None:
    """The count is part of what the row says, so a repeat is a change even though
    the entry is the same one."""
    host, controller = screen
    host.show()
    _pump()
    entry = _entry(uid="u1", kind=KIND_SKIPPED, message_code="", reason="disconnected")
    host._automations.entries = [entry]
    controller.sync_controls()

    host._automations.entries = [
        _entry(
            uid="u1",
            kind=KIND_SKIPPED,
            message_code="",
            reason="disconnected",
            count=4,
            last_seen=datetime(2026, 7, 30, 21, 30),
        )
    ]
    controller._tick()

    detail = controller._host.automations_journal_layout.itemAt(0).widget().findChildren(QLabel)[1]
    assert _tr("automations.journal_repeat", count=4) in detail.text()


def test_the_journal_is_not_re_read_while_the_page_is_hidden(screen) -> None:
    host, controller = screen  # the host was never shown
    host._automations.calls.clear()

    controller._tick()

    assert [call for call in host._automations.calls if call[0] == "journal"] == []


def test_switching_language_redraws_the_history(screen) -> None:
    """The rows are generated from codes, so they have to be rebuilt — and the
    "nothing changed" guard must not keep the old language on screen."""
    host, controller = screen
    host._automations.entries = [_entry(uid="u1", rule_id="gone")]
    controller.sync_controls()
    english = controller._host.automations_journal_layout.itemAt(0).widget().findChildren(QLabel)[1].text()

    localization_manager.set_language("ru")
    controller.relocalize()

    russian = controller._host.automations_journal_layout.itemAt(0).widget().findChildren(QLabel)[1].text()
    assert russian != english


def test_a_cancelled_run_is_not_dressed_as_a_failure(screen) -> None:
    """The user taking over is not a fault. A journal that paints it red teaches
    them to ignore the real failures beside it."""
    from app.automation_ui_controller import _JOURNAL_TILES

    cancelled = _JOURNAL_TILES[KIND_CANCELLED]
    failed = _JOURNAL_TILES[KIND_ERROR]

    assert cancelled != failed
    assert cancelled[1] != failed[1], "cancelled and failed share a colour"
