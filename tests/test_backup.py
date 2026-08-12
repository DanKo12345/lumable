"""A portable backup: what travels, what must not, and what a bad file does.

The expensive mistakes here are quiet ones — a licence key or a Bluetooth
address riding along in a file meant to be shared, or a restore that half
succeeds and leaves someone with neither their old scenes nor their new ones.
"""

from __future__ import annotations

import json

from app.backup import (
    BACKUP_KIND,
    BACKUP_VERSION,
    MAX_BACKUP_BYTES,
    PORTABLE_KEYS,
    WITHHELD_KEYS,
    build_backup,
    inspect_backup,
    restore_into,
)

_SECRETS = {
    "license": {"license_key": "LUMA-XXXX-YYYY", "license_id": "abc"},
    "api": {"enabled": True, "token": "s3cr3t", "port": 7345},
    "last_device_address": "AA:BB:CC:DD:EE:01",
    "last_device_name": "Demo strip",
    "extra_device_addresses": ["AA:BB:CC:DD:EE:FF"],
    "device_names": {"AA:BB:CC:DD:EE:01": "Desk"},
    "last_state": {"power": True},
    "capture_compatibility": {"probed": True},
    "window_width": 1280,
    "window_height": 860,
    "onboarding_seen": True,
}


def _settings(**extra) -> dict:
    base = {
        "scenes": [{"scene_id": "s1", "name": "Read"}],
        "automations": {"enabled": True, "rules": [{"id": "r1"}]},
        "device_groups": [
            {"group_id": "g1", "name": "Desk", "members": ["AA:BB:CC:DD:EE:01"]}
        ],
        "hotkeys": {"enabled": True, "bindings": {"toggle_power": "Alt+L"}},
        "theme_mode": "dark",
        **_SECRETS,
    }
    base.update(extra)
    return base


# ── what must not travel ──────────────────────────────────────────────
def test_no_secret_or_machine_detail_reaches_the_file() -> None:
    """A backup is meant to be copied to another machine, sent to support, or
    kept in a folder someone syncs. Every one of these would be a leak."""
    document = build_backup(_settings())
    text = json.dumps(document)

    for key in WITHHELD_KEYS:
        assert key not in document["data"], key
    for secret in ("LUMA-XXXX-YYYY", "s3cr3t", "AA:BB:CC:DD:EE:01", "Demo strip"):
        assert secret not in text, secret


def test_a_key_nobody_has_thought_about_does_not_travel() -> None:
    """The list says what is carried, not what is skipped: a setting added later
    stays out until someone decides it belongs, which is the safe direction to
    be wrong in."""
    document = build_backup(_settings(some_future_setting={"token": "leak"}))

    assert "some_future_setting" not in document["data"]
    assert "leak" not in json.dumps(document)


def test_group_names_travel_and_their_strips_do_not() -> None:
    """Members are BLE addresses. Carrying the groups while dropping what is in
    them has to be visible, or a scene aimed at a group lights nothing and
    explains nothing."""
    document = build_backup(_settings())

    groups = document["data"]["device_groups"]
    assert [group["name"] for group in groups] == ["Desk"]
    assert groups[0]["members"] == []
    assert groups[0]["group_id"] == "g1", "a scene points at the group by id"


# ── what does travel ──────────────────────────────────────────────────
def test_the_things_a_person_made_are_all_there() -> None:
    document = build_backup(_settings())

    assert document["kind"] == BACKUP_KIND
    assert document["version"] == BACKUP_VERSION
    assert document["data"]["scenes"][0]["name"] == "Read"
    assert document["data"]["hotkeys"]["bindings"]["toggle_power"] == "Alt+L"
    assert document["data"]["theme_mode"] == "dark"


def test_a_missing_section_is_simply_absent() -> None:
    """Someone who never made a DIY effect should not get an empty one back."""
    document = build_backup({"scenes": [], "automations": {}})

    assert "diy_saved" not in document["data"]


# ── refusing a file ───────────────────────────────────────────────────
def test_a_file_from_a_newer_version_is_refused_whole() -> None:
    """Reading it as far as it goes would drop exactly the parts this build does
    not understand, and report success while doing it."""
    document = build_backup(_settings())
    document["version"] = BACKUP_VERSION + 1

    check = inspect_backup(json.dumps(document))

    assert not check.ok
    assert check.error == "too_new"
    assert check.version == BACKUP_VERSION + 1


def test_broken_json_is_refused_before_anything_is_touched() -> None:
    for raw in ("", "{", "not json at all", '{"kind": '):
        assert not inspect_backup(raw).ok


def test_json_from_somewhere_else_is_not_a_backup() -> None:
    check = inspect_backup(json.dumps({"version": 1, "data": {"scenes": []}}))

    assert check.error == "not_a_backup"


def test_a_file_without_the_essentials_is_refused() -> None:
    document = build_backup(_settings())
    del document["data"]["scenes"]

    assert inspect_backup(json.dumps(document)).error == "incomplete"


def test_an_enormous_file_is_refused_before_it_is_parsed() -> None:
    """The cheapest way to survive a hostile or corrupt file is not to hand it
    to the parser at all."""
    check = inspect_backup(b"[" + b" " * (MAX_BACKUP_BYTES + 1))

    assert check.error == "too_large"


def test_a_good_file_reports_what_is_in_it() -> None:
    check = inspect_backup(json.dumps(build_backup(_settings())))

    assert check.ok
    assert check.counts["scenes"] == 1
    assert check.counts["automations"] == 1
    assert check.counts["device_groups"] == 1


# ── restoring ─────────────────────────────────────────────────────────
def test_a_restore_builds_a_new_settings_and_leaves_the_old_one_alone() -> None:
    """Either the caller writes the result or it does not; there is no state
    where half of it has been applied."""
    current = _settings(scenes=[{"scene_id": "old", "name": "Old"}])
    check = inspect_backup(json.dumps(build_backup(_settings())))

    restored, _report = restore_into(current, check.payload)

    assert current["scenes"][0]["name"] == "Old", "the original was modified"
    assert restored["scenes"][0]["name"] == "Read"


def test_a_restore_keeps_the_settings_that_belong_to_this_machine() -> None:
    """The licence, the strip and the window belong to the installation, not to
    the backup — restoring must not sign someone out or forget their strip."""
    current = _settings()

    restored, _report = restore_into(current, build_backup(_settings())["data"])

    assert restored["license"] == current["license"]
    assert restored["last_device_address"] == current["last_device_address"]
    assert restored["api"]["token"] == "s3cr3t"


def test_a_hand_edited_file_cannot_put_a_secret_back() -> None:
    """Only the portable keys are read, whatever else the document claims."""
    payload = dict(build_backup(_settings())["data"])
    payload["license"] = {"license_key": "FORGED"}
    payload["last_device_address"] = "11:22:33:44:55:66"

    restored, _report = restore_into({"license": {"license_key": "MINE"}}, payload)

    assert restored["license"] == {"license_key": "MINE"}
    assert "last_device_address" not in restored


def test_the_restore_says_how_many_groups_need_their_strips_back() -> None:
    """Silence here is the failure: the groups look restored and light nothing."""
    payload = build_backup(_settings())["data"]

    _restored, report = restore_into({}, payload)

    assert report.groups_need_strips == 1
    assert report.counts["scenes"] == 1


def test_every_portable_key_is_actually_carried() -> None:
    """A key on the list but missing from the export would be a promise the
    backup does not keep."""
    settings = {key: [] for key in PORTABLE_KEYS}
    document = build_backup(settings)

    assert set(document["data"]) == set(PORTABLE_KEYS)
