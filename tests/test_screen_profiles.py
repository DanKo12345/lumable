"""Screen-sync profiles: stable ids, safe defaults, sensible per-profile intent."""

from __future__ import annotations

from app.screen_profiles import (
    DEFAULT_PROFILE_ID,
    NEUTRAL_INTENSITY,
    NEUTRAL_SMOOTHNESS,
    PROFILE_IDS,
    get_profile,
    normalize_profile_id,
    resolve_configs,
)


def test_the_three_profiles_exist_with_their_stable_ids() -> None:
    assert PROFILE_IDS == ("desktop", "game", "movie")
    for pid in PROFILE_IDS:
        assert get_profile(pid).profile_id == pid


def test_unknown_or_junk_falls_back_to_the_default() -> None:
    assert normalize_profile_id("nope") == DEFAULT_PROFILE_ID
    assert normalize_profile_id("") == DEFAULT_PROFILE_ID
    assert normalize_profile_id(None) == DEFAULT_PROFILE_ID
    assert get_profile("nope").profile_id == DEFAULT_PROFILE_ID


def test_ids_are_case_and_space_insensitive() -> None:
    assert normalize_profile_id("  Movie ") == "movie"


def test_game_is_punchier_and_faster_than_movie() -> None:
    game = get_profile("game")
    movie = get_profile("movie")
    assert game.shape.saturation > movie.shape.saturation      # more vivid
    assert game.temporal.half_life_s < movie.temporal.half_life_s  # reacts faster
    assert game.temporal.max_rate > movie.temporal.max_rate    # flashes allowed to move


def test_movie_rejects_black_bars_desktop_does_not() -> None:
    assert get_profile("movie").sample.reject_black_bars is True
    assert get_profile("desktop").sample.reject_black_bars is False


def test_only_movie_lets_true_black_stay_black() -> None:
    # Desktop is a bias light (brightness floor); Movie must not lift black.
    assert get_profile("movie").shape.min_brightness == 0
    assert get_profile("desktop").shape.min_brightness > 0


def test_neutral_adjustments_return_the_profile_unchanged() -> None:
    # The stored 0.3.3 defaults are the neutral point: upgrading must not move
    # the light twice.
    profile = get_profile("desktop")
    resolved = resolve_configs(profile, NEUTRAL_INTENSITY, NEUTRAL_SMOOTHNESS)
    assert abs(resolved.shape.saturation - profile.shape.saturation) < 1e-6
    assert abs(resolved.temporal.half_life_s - profile.temporal.half_life_s) < 1e-6
    assert resolved.sample == profile.sample


def test_intensity_scales_saturation_smoothness_scales_half_life() -> None:
    profile = get_profile("desktop")
    punchy = resolve_configs(profile, 100, NEUTRAL_SMOOTHNESS)
    calm = resolve_configs(profile, 10, NEUTRAL_SMOOTHNESS)
    assert punchy.shape.saturation > profile.shape.saturation > calm.shape.saturation

    slow = resolve_configs(profile, NEUTRAL_INTENSITY, 100)
    fast = resolve_configs(profile, NEUTRAL_INTENSITY, 0)
    assert slow.temporal.half_life_s > profile.temporal.half_life_s > fast.temporal.half_life_s
