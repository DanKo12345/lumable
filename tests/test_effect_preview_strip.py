from __future__ import annotations

import math

from app.widgets.effect_preview_strip import effect_semantic_key


def test_shared_triones_magic_home_effects_map_to_preview_semantics() -> None:
    assert effect_semantic_key("triones_effect_26", 0x26) == "fade_red"
    assert effect_semantic_key("magic_home_effect_2f", 0x2F) == "fade_green_blue"
    assert effect_semantic_key("magic_home_effect_30", 0x30) == "flash_spectrum"
    assert effect_semantic_key("triones_effect_38", 0x38) == "jump_rgb_cmyw"


def test_banlanx_effects_map_to_preview_semantics() -> None:
    assert effect_semantic_key("banlanx_effect_01", 0x01) == "smooth_rainbow"
    assert effect_semantic_key("banlanx_effect_04", 0x04) == "fade_spectrum"
    assert effect_semantic_key("banlanx_effect_0d", 0x0D) == "flash_red"
    assert effect_semantic_key("banlanx_effect_17", 0x17) == "smooth_spectrum"


def test_bledom_effect_keys_keep_existing_preview_semantics() -> None:
    assert effect_semantic_key("fade_red", 0x8B) == "fade_red"
    assert effect_semantic_key("jump_rgb", 0x87) == "jump_rgb"
    assert effect_semantic_key("fade_spectrum", 0x89) == "fade_spectrum"


def test_all_driver_effects_have_non_static_preview_semantics() -> None:
    from app.ble_drivers.banlanx import BANLANX_EFFECTS
    from app.ble_drivers.bledom import BLEDOM_EFFECTS
    from app.ble_drivers.magic_home import MAGIC_HOME_EFFECTS
    from app.ble_drivers.triones import TRIONES_EFFECTS

    all_effects = [*BANLANX_EFFECTS, *BLEDOM_EFFECTS, *MAGIC_HOME_EFFECTS, *TRIONES_EFFECTS]
    missing = []
    for effect in all_effects:
        if effect.code == 0:
            continue
        semantic = effect_semantic_key(effect.key, effect.code)
        is_handled = (
            semantic.startswith(("fade", "flash", "jump"))
            or "rainbow" in semantic
            or "spectrum" in semantic
        )
        if not is_handled:
            missing.append((effect.key, effect.code, semantic))

    assert missing == []


def test_preview_phase_stays_continuous_when_speed_changes() -> None:
    from PySide6.QtWidgets import QApplication

    from app.widgets.effect_preview_strip import EffectPreviewStrip

    _app = QApplication.instance() or QApplication([])
    preview = EffectPreviewStrip()
    preview._effect_key = "smooth_rainbow"
    preview._effect_code = 0x8A
    preview._phase = 1.25
    preview._last_tick_ms = 1000

    class FakeElapsed:
        def elapsed(self) -> int:
            return 1000

    preview._elapsed = FakeElapsed()

    preview.set_speed(100)
    preview._tick()
    preview.deleteLater()

    assert math.isclose(preview._phase, 1.25)


def test_jump_preview_uses_absolute_timing_and_shorter_steps() -> None:
    from PySide6.QtWidgets import QApplication

    from app.widgets.effect_preview_strip import EffectPreviewStrip

    _app = QApplication.instance() or QApplication([])
    preview = EffectPreviewStrip()
    preview.set_effect("jump_rgb", 0x87, reset_phase=True)
    preview.set_speed(60)

    class FakeElapsed:
        def elapsed(self) -> int:
            return round(preview._jump_step_duration_ms())

    preview._elapsed = FakeElapsed()
    preview._last_tick_ms = 0
    preview._phase = 0.0

    preview._tick()
    step_index = int((preview._phase / (math.pi * 2.0)) * len(preview._effect_palette())) % len(preview._effect_palette())
    preview.deleteLater()

    assert preview._jump_step_duration_ms() == 1140.0
    assert step_index == 1


def test_flash_preview_is_slower_than_old_fast_strobe() -> None:
    from PySide6.QtWidgets import QApplication

    from app.widgets.effect_preview_strip import EffectPreviewStrip

    _app = QApplication.instance() or QApplication([])
    preview = EffectPreviewStrip()
    preview.set_effect("flash_red", 0x95, reset_phase=True)
    preview.set_speed(60)

    assert preview._flash_cycle_duration_ms() == 2220.0

    class FakeElapsed:
        def elapsed(self) -> int:
            return round(preview._flash_cycle_duration_ms() / 2)

    preview._elapsed = FakeElapsed()
    preview._last_tick_ms = 0
    preview._phase = 0.0

    preview._tick()
    preview.deleteLater()

    assert math.isclose(preview._phase, math.pi, rel_tol=0.02)
