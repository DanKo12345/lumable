from __future__ import annotations

from app.hotkeys import (
    ACTIONS,
    DEFAULT_HOTKEYS,
    SUGGESTED_HOTKEYS,
    Hotkey,
    format_hotkey,
    key_to_vk,
    parse_hotkey,
    registrable,
    resolve_binding,
    to_win_modifiers,
)


def test_parse_basic() -> None:
    hk = parse_hotkey("Ctrl+Alt+L")
    assert hk == Hotkey(frozenset({"ctrl", "alt"}), "L")


def test_parse_is_case_and_space_insensitive() -> None:
    assert parse_hotkey("  control + ALT + l ") == Hotkey(frozenset({"ctrl", "alt"}), "L")


def test_parse_aliases_map_to_win() -> None:
    assert parse_hotkey("Win+Up").mods == frozenset({"win"})
    assert parse_hotkey("Super+Up") == parse_hotkey("Meta+Up")


def test_parse_rejects_invalid() -> None:
    assert parse_hotkey("") is None
    assert parse_hotkey("Ctrl+Alt") is None  # modifiers only, no key
    assert parse_hotkey("Ctrl+Alt+L+K") is None  # two real keys
    assert parse_hotkey("Ctrl+Foo") is None  # unknown key
    assert parse_hotkey("F13") is None  # out of F1..F12


def test_parse_allows_named_and_function_keys() -> None:
    assert parse_hotkey("Ctrl+Alt+Right").key == "RIGHT"
    assert parse_hotkey("Alt+F4").key == "F4"


def test_key_to_vk() -> None:
    assert key_to_vk("A") == 0x41
    assert key_to_vk("Z") == 0x5A
    assert key_to_vk("0") == 0x30
    assert key_to_vk("F1") == 0x70
    assert key_to_vk("F12") == 0x7B
    assert key_to_vk("RIGHT") == 0x27
    assert key_to_vk("UNKNOWN") is None


def test_to_win_modifiers() -> None:
    assert to_win_modifiers(frozenset({"ctrl", "alt"})) == 0x0003
    assert to_win_modifiers(frozenset({"shift"})) == 0x0004
    assert to_win_modifiers(frozenset({"win"})) == 0x0008
    assert to_win_modifiers(frozenset()) == 0


def test_format_round_trip() -> None:
    for spec in ("Ctrl+Alt+L", "Ctrl+Alt+Right", "Alt+F4"):
        assert parse_hotkey(format_hotkey(parse_hotkey(spec))) == parse_hotkey(spec)


def test_every_action_has_a_default_even_if_it_is_no_default() -> None:
    assert set(DEFAULT_HOTKEYS) == set(ACTIONS)
    for spec in DEFAULT_HOTKEYS.values():
        if not spec:
            continue  # deliberately unassigned — see the test below
        hk = parse_hotkey(spec)
        assert hk is not None
        assert key_to_vk(hk.key) is not None
        assert to_win_modifiers(hk.mods) != 0  # a default always carries a modifier


def test_the_modes_claim_no_global_key_until_asked() -> None:
    """A global hotkey is taken from the whole system. Shipping a default for
    these would seize a common combination from whatever the user already uses
    it for — silently, on upgrade, with no way to see what changed."""
    assert DEFAULT_HOTKEYS["toggle_screen_sync"] == ""
    assert DEFAULT_HOTKEYS["toggle_music"] == ""
    assert registrable(DEFAULT_HOTKEYS) != []
    assert {action for action, *_ in registrable(DEFAULT_HOTKEYS)} == {
        action for action, spec in DEFAULT_HOTKEYS.items() if spec
    }


def test_an_unassigned_action_never_reaches_the_registration_call() -> None:
    plan = registrable({"toggle_power": "Alt+L", "toggle_music": "", "toggle_screen_sync": "   "})

    assert [action for action, *_ in plan] == ["toggle_power"]


def test_an_unparseable_spec_is_dropped_rather_than_guessed() -> None:
    plan = registrable({"toggle_power": "Alt+Alt", "toggle_music": "Ctrl+Alt+M"})

    assert [action for action, *_ in plan] == ["toggle_music"]


def test_one_bad_binding_does_not_take_the_others_with_it() -> None:
    plan = registrable(
        {"toggle_power": "Alt+L", "next_scene": "nonsense", "toggle_music": "Ctrl+Alt+M"}
    )

    assert [action for action, *_ in plan] == ["toggle_power", "toggle_music"]


def test_a_plan_carries_what_the_windows_call_needs() -> None:
    (action, spec, mods, vk), = registrable({"toggle_music": "Ctrl+Alt+M"})

    assert (action, spec) == ("toggle_music", "Ctrl+Alt+M")
    assert mods == to_win_modifiers(parse_hotkey(spec).mods)
    assert vk == key_to_vk("m")


def test_an_action_missing_from_an_older_file_takes_its_default() -> None:
    """What an upgrade looks like: the file predates the action entirely."""
    saved = {"toggle_power": "Alt+L"}

    assert resolve_binding(saved, "next_scene") == DEFAULT_HOTKEYS["next_scene"]
    assert resolve_binding(saved, "toggle_music") == ""


def test_an_action_switched_off_stays_off() -> None:
    """The difference between this and the case above is the difference between
    a preference and a bug: restoring the default would hand a global
    combination back to an app that was told to let go of it — and the next
    migration would do it again."""
    saved = {"toggle_power": "", "toggle_music": ""}

    assert resolve_binding(saved, "toggle_power") == ""
    assert resolve_binding(saved, "toggle_music") == ""
    assert DEFAULT_HOTKEYS["toggle_power"], "this test means nothing if the default is empty"


def test_a_saved_combination_is_used_as_saved() -> None:
    assert resolve_binding({"toggle_music": "Ctrl+Alt+M"}, "toggle_music") == "Ctrl+Alt+M"
    assert resolve_binding({"toggle_music": "  Ctrl+Alt+M  "}, "toggle_music") == "Ctrl+Alt+M"


def test_a_missing_or_broken_file_still_answers() -> None:
    assert resolve_binding({}, "toggle_power") == DEFAULT_HOTKEYS["toggle_power"]
    assert resolve_binding(None, "toggle_power") == DEFAULT_HOTKEYS["toggle_power"]
    assert resolve_binding({"toggle_power": None}, "toggle_power") == ""


def test_a_suggestion_is_never_an_answer() -> None:
    """A placeholder must not be mistaken for an active key, and opening the
    settings page must not claim one."""
    for action, suggested in SUGGESTED_HOTKEYS.items():
        assert DEFAULT_HOTKEYS[action] == ""
        assert resolve_binding({}, action) == ""
        assert parse_hotkey(suggested) is not None, "a suggestion should at least be typeable"
