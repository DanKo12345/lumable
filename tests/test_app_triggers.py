from __future__ import annotations

from app.app_triggers import AppRule, match_rule, normalize_process_name


def test_normalize_lowercases_and_strips() -> None:
    assert normalize_process_name("  Chrome.EXE ") == "chrome.exe"


def test_match_is_case_insensitive_substring() -> None:
    rules = [AppRule(app="chrome", scene="cool_white")]
    assert match_rule("Chrome.exe", rules).scene == "cool_white"
    assert match_rule("CHROME.EXE", rules).scene == "cool_white"


def test_first_matching_rule_wins() -> None:
    rules = [
        AppRule(app="game", scene="red"),
        AppRule(app="valorant", scene="blue"),
    ]
    # "valorant-game.exe" contains "game" first in the list.
    assert match_rule("valorant-game.exe", rules).scene == "red"


def test_no_match_returns_none() -> None:
    rules = [AppRule(app="spotify", scene="party")]
    assert match_rule("notepad.exe", rules) is None


def test_empty_inputs_return_none() -> None:
    assert match_rule("", [AppRule(app="x", scene="red")]) is None
    assert match_rule("anything.exe", []) is None
    # A rule with an empty app fragment never matches.
    assert match_rule("anything.exe", [AppRule(app="", scene="red")]) is None
