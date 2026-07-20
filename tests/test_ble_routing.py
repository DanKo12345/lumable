from __future__ import annotations

from dataclasses import dataclass

from app.ble_routing import normalize_addresses, plan_targets, swap_primary


@dataclass
class _Strip:
    address: str

PRIMARY = "AA:BB"
MIRRORS = ["CC:DD", "EE:FF"]


def test_none_targets_writes_everything() -> None:
    plan = plan_targets(None, PRIMARY, MIRRORS)
    assert plan["primary"] is True
    assert plan["mirrors"] == ["CC:DD", "EE:FF"]
    assert plan["written"] == ["AA:BB", "CC:DD", "EE:FF"]
    assert plan["sync_primary"] is True


def test_primary_only() -> None:
    plan = plan_targets({PRIMARY}, PRIMARY, MIRRORS)
    assert plan["primary"] is True
    assert plan["mirrors"] == []
    assert plan["written"] == ["AA:BB"]
    assert plan["sync_primary"] is True


def test_single_mirror_does_not_touch_primary() -> None:
    plan = plan_targets({"CC:DD"}, PRIMARY, MIRRORS)
    assert plan["primary"] is False
    assert plan["mirrors"] == ["CC:DD"]
    assert plan["written"] == ["CC:DD"]
    assert plan["sync_primary"] is False  # a mirror-only write must not sync the primary


def test_group_including_primary() -> None:
    plan = plan_targets({PRIMARY, "EE:FF"}, PRIMARY, MIRRORS)
    assert plan["written"] == ["AA:BB", "EE:FF"]
    assert plan["sync_primary"] is True


def test_empty_or_removed_targets_write_nothing() -> None:
    empty = plan_targets(set(), PRIMARY, MIRRORS)
    assert empty["written"] == []
    assert empty["sync_primary"] is False

    gone = plan_targets({"99:99"}, PRIMARY, MIRRORS)
    assert gone["written"] == []
    assert gone["primary"] is False


def test_addresses_are_normalised() -> None:
    # Whitespace and duplicates on both the target set and the mirror list collapse.
    plan = plan_targets({" CC:DD ", "", "CC:DD", "EE:FF "}, PRIMARY, [" CC:DD ", "EE:FF"])
    assert plan["mirrors"] == ["CC:DD", "EE:FF"]
    assert plan["written"] == ["CC:DD", "EE:FF"]


def test_no_primary_connected() -> None:
    plan = plan_targets(None, "", MIRRORS)
    assert plan["primary"] is False
    assert plan["written"] == ["CC:DD", "EE:FF"]
    assert plan["sync_primary"] is False


# ── promoting a mirror to primary ────────────────────────────────────────
def test_promoting_a_mirror_swaps_roles() -> None:
    primary, first, second = _Strip("AA"), _Strip("BB"), _Strip("CC")
    new_primary, mirrors = swap_primary(primary, [first, second], "BB")
    assert new_primary is first
    # The other mirror keeps its place; the old primary joins the list.
    assert mirrors == [second, primary]


def test_promoting_keeps_a_single_mirror_case_simple() -> None:
    primary, mirror = _Strip("AA"), _Strip("BB")
    new_primary, mirrors = swap_primary(primary, [mirror], "BB")
    assert new_primary is mirror
    assert mirrors == [primary]


def test_promoting_is_a_no_op_for_the_current_primary() -> None:
    primary = _Strip("AA")
    assert swap_primary(primary, [_Strip("BB")], "AA") is None


def test_promoting_an_unknown_or_empty_address_changes_nothing() -> None:
    primary = _Strip("AA")
    assert swap_primary(primary, [_Strip("BB")], "ZZ") is None
    assert swap_primary(primary, [_Strip("BB")], "") is None
    assert swap_primary(primary, [_Strip("BB")], None) is None


def test_promoting_needs_a_live_primary() -> None:
    assert swap_primary(None, [_Strip("BB")], "BB") is None


def test_promoting_tolerates_untrimmed_addresses() -> None:
    primary, mirror = _Strip("AA"), _Strip(" BB ")
    new_primary, mirrors = swap_primary(primary, [mirror], "BB")
    assert new_primary is mirror
    assert mirrors == [primary]


def test_normalize_addresses_helper() -> None:
    assert normalize_addresses(None) is None
    assert normalize_addresses([" a ", "b", "", "a"]) == {"a", "b"}
