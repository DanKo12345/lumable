from __future__ import annotations

from app.hotkeys import (
    ACTIONS,
    DEFAULT_HOTKEYS,
    Hotkey,
    format_hotkey,
    key_to_vk,
    parse_hotkey,
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


def test_defaults_are_all_valid_and_mappable() -> None:
    assert set(DEFAULT_HOTKEYS) == set(ACTIONS)
    for spec in DEFAULT_HOTKEYS.values():
        hk = parse_hotkey(spec)
        assert hk is not None
        assert key_to_vk(hk.key) is not None
        assert to_win_modifiers(hk.mods) != 0  # defaults always carry a modifier
