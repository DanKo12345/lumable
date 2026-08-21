"""The mode row has to fit, in every language and in a small window.

The row carries a title, a status line, a two-option control and a button. It is
the densest row on the card, the translations differ in length by a lot, and a
row that overflows does not fail loudly — it elides a word or pushes the button
past the edge.

Measured in a subprocess with the real platform plugin, because the suite runs
under ``offscreen`` and its font metrics are not the ones a person sees. Asking
Qt here directly gave "Screen capture needs 706px" for a row that really needs
554, which would have sent someone shrinking a layout that was already fine.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "measure_mode_row.py"


def decide_outcome(returncode: int, *, headless: bool) -> str:
    """What a failed measurement means: "skip" only where it is expected.

    A rule rather than a line inside a fixture, because a fixture that skips is
    invisible in a green run — and a guarantee that quietly stops being checked
    on the one machine where the layout is actually looked at is worse than no
    guarantee.
    """
    if returncode == 0:
        return "ok"
    return "skip" if headless else "fail"


@pytest.fixture(scope="module")
def measurements():
    """Run the measuring tool with the real platform plugin.

    A machine with no desktop is skipped, but only when it says so: an
    environment that cannot open a window sets ``LUMABLE_HEADLESS``. Anything
    else — a window that failed to open under load, a tool that raised — is a
    failure. Skipping on any error would let this guarantee quietly stop being
    checked on the one machine where the layout is actually seen, and a test
    that stops checking without saying so is worse than no test.
    """
    import os

    if not TOOL.exists():
        pytest.fail(f"the measuring tool is missing: {TOOL}")

    env = dict(os.environ)
    # The real plugin, whatever conftest set for the suite.
    env.pop("QT_QPA_PLATFORM", None)

    def measure():
        return subprocess.run(
            [sys.executable, str(TOOL)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(ROOT),
            timeout=300,
        )

    result = measure()
    if result.returncode != 0:
        # Opening a real window occasionally does not take — measured at about
        # one run in four while the machine is busy. One retry, and then it is a
        # failure: a second refusal is a fact about the layout or the tool, and
        # skipping on either would let this guarantee stop being checked on the
        # one machine where the layout is actually seen.
        result = measure()
    outcome = decide_outcome(result.returncode, headless=bool(os.environ.get("LUMABLE_HEADLESS")))
    if outcome != "ok":
        detail = (result.stderr or "").strip()[-400:]
        if outcome == "skip":
            pytest.skip(f"no desktop to measure on: {detail}")
        pytest.fail(
            "the row could not be measured with the real platform plugin. "
            "Set LUMABLE_HEADLESS=1 on a machine with no desktop. " + detail
        )
    return json.loads(result.stdout)


def test_the_row_fits_in_every_language_and_a_small_window(measurements) -> None:
    too_wide = [
        f"{row['language']} at {row['size']}: needs {row['row_needs']}px, has {row['row_has']}px"
        for row in measurements
        if row["row_needs"] > row["row_has"]
    ]
    assert not too_wide, "; ".join(too_wide)


def test_no_title_is_clipped(measurements) -> None:
    clipped = [
        f"{row['language']} at {row['size']}: \"{row['title']}\" needs "
        f"{row['title_needs']}px in {row['title_has']}px"
        for row in measurements
        if row["title_needs"] > row["title_has"]
    ]
    assert not clipped, "; ".join(clipped)


def test_the_mode_control_and_the_button_stay_inside_the_card(measurements) -> None:
    outside = [
        f"{row['language']} at {row['size']}: control ends at {row['segment_right']}px, "
        f"button at {row['button_right']}px, card is {row['card_width']}px"
        for row in measurements
        if row["button_right"] > row["card_width"] or row["segment_right"] > row["card_width"]
    ]
    assert not outside, "; ".join(outside)


def test_everything_in_the_row_really_is_translated(measurements) -> None:
    """One widget serves every language, so a missing retranslation shows up as
    identical text and nothing else — no error, no warning, just English in a
    Spanish window. The mode control needs its own check: it is a separate
    widget from the row title and is retranslated by a separate line.
    """
    titles = {row["language"]: row["title"] for row in measurements}
    assert len(set(titles.values())) == len(titles), f"a language was not applied: {titles}"

    labels = {row["language"]: tuple(row["segment_labels"]) for row in measurements}
    assert len(set(labels.values())) == len(labels), (
        f"the mode control kept one language's labels: {labels}"
    )

    # And every control in the compact panel, each checked on its own. Taken
    # together they stay unique as long as *any* of them is translated, so one
    # forgotten widget hides behind its neighbours — which is exactly the kind
    # of gap this is here to find.
    names = ("source: system", "source: microphone", "beat", "settings button")
    for index, name in enumerate(names):
        seen = {row["language"]: row["panel_labels"][index] for row in measurements}
        assert len(set(seen.values())) == len(seen), (
            f"{name} kept one language's text: {seen}"
        )


def test_a_window_that_merely_failed_to_open_is_a_failure() -> None:
    """On an ordinary desktop the tool not running means something is wrong,
    not that the check does not apply. Only an environment that declares itself
    headless may be excused."""
    assert decide_outcome(0, headless=False) == "ok"
    assert decide_outcome(0, headless=True) == "ok"
    assert decide_outcome(1, headless=False) == "fail"
    assert decide_outcome(1, headless=True) == "skip"


def test_the_settings_panel_costs_nothing_until_it_is_opened(measurements) -> None:
    """The whole reason it collapses. A permanently taller card would spend the
    height every day for something set once — and the guided tour frames the
    card, so a card that outgrows the viewport changes what the tour shows.
    """
    for row in measurements:
        assert row["tune_button_shown"] is True, row["language"]
        assert row["tune_row_shown"] is False, "the panel was open by default"
        assert row["card_height_open"] > row["card_height_collapsed"], (
            f"{row['language']} at {row['size']}: opening the panel took no room"
        )
