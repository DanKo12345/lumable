from __future__ import annotations

from app.ble_drivers import DRIVER_BY_ID, DRIVERS
from app.localization import localization_manager
from app.widgets.effect_preview_strip import effect_semantic_key


def test_driver_registry_contains_unique_supported_drivers() -> None:
    assert [driver.id for driver in DRIVERS] == ["bledom", "banlanx", "magic_home", "triones"]
    assert set(DRIVER_BY_ID) == {driver.id for driver in DRIVERS}


def test_all_declared_driver_effects_have_payloads_or_are_static() -> None:
    for driver in DRIVERS:
        for effect in driver.effects:
            if effect.code == 0:
                continue

            assert driver.effect_payload(effect.code) is not None, (driver.id, effect)


def test_all_declared_driver_effect_codes_are_unique() -> None:
    for driver in DRIVERS:
        codes = [effect.code for effect in driver.effects]

        assert len(codes) == len(set(codes)), driver.id


def test_all_declared_driver_effects_reject_neighbor_out_of_range_codes() -> None:
    for driver in DRIVERS:
        non_static_codes = [effect.code for effect in driver.effects if effect.code != 0]
        if not non_static_codes:
            continue

        assert driver.effect_payload(min(non_static_codes) - 1) is None, driver.id
        assert driver.effect_payload(max(non_static_codes) + 1) is None, driver.id


def test_all_declared_driver_effect_payloads_keep_their_code_byte() -> None:
    for driver in DRIVERS:
        for effect in driver.effects:
            if effect.code == 0:
                continue
            payload = driver.effect_payload(effect.code)

            assert payload is not None, (driver.id, effect)
            assert effect.code in payload, (driver.id, effect, payload.hex(" "))


def test_all_declared_driver_effects_have_translations() -> None:
    for driver in DRIVERS:
        for effect in driver.effects:
            key = f"effect.{effect.key}"

            assert localization_manager.t(key) != key, (driver.id, key)


def test_all_declared_driver_effects_have_preview_semantics() -> None:
    for driver in DRIVERS:
        for effect in driver.effects:
            if effect.code == 0:
                continue
            semantic = effect_semantic_key(effect.key, effect.code)

            assert semantic != "static_color", (driver.id, effect)
            assert (
                semantic.startswith(("fade", "flash", "jump"))
                or "rainbow" in semantic
                or "spectrum" in semantic
            ), (driver.id, effect, semantic)


def test_all_drivers_build_core_payloads_without_runtime_errors() -> None:
    for driver in DRIVERS:
        driver.reset_runtime_state()

        assert driver.power_payloads(True)
        assert driver.power_payloads(False)
        assert driver.color_payloads(1, 2, 3)
        assert isinstance(driver.brightness_payloads(50), list)


def test_driver_effect_speed_support_is_explicit() -> None:
    support = {driver.id: driver.supports_effect_speed() for driver in DRIVERS}

    assert support == {
        "bledom": True,
        "banlanx": True,
        "magic_home": False,
        "triones": True,
    }
