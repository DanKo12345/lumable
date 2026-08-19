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


@pytest.fixture(scope="module")
def measurements():
    if not TOOL.exists():
        pytest.skip("the measuring tool is not present")
    import os

    env = dict(os.environ)
    # The real plugin, whatever conftest set for the suite.
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, str(TOOL)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(ROOT),
        timeout=300,
    )
    if result.returncode != 0:
        pytest.skip(f"no display to measure on: {result.stderr.strip()[-200:]}")
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
