"""Screen-sync profiles: Desktop / Game / Movie as one settled preset each.

A profile is the full recipe for turning a frame into a strip colour — the
spatial :class:`~app.screen_sample.SampleConfig`, the HSV shaping (saturation,
gamma, brightness range, saturation floor) and the temporal
:class:`~app.screen_temporal.TemporalConfig`. Keeping the three tuned together
is what makes "Movie" calm and "Game" punchy without the user touching ten
sliders.

Qt-free and keyed by **stable ids** (``desktop`` / ``game`` / ``movie``), never
display names, so a saved choice survives a language change and a rename.

The intent of each:

- **Desktop** — steady bias light. Edge-weighted, gentle boost, well smoothed,
  a brightness floor so a dark editor still glows faintly.
- **Game** — reactive and vivid. Dominant colour, strong saturation, a short
  half-life and a high flash rate so it keeps up, but the absolute step cap
  still stops a muzzle flash from strobing the room.
- **Movie** — faithful and calm. Black-bar rejection on, restrained saturation,
  slow smoothing, no brightness floor so true black scenes stay dark.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.screen_sample import SampleConfig
from app.screen_temporal import TemporalConfig

DEFAULT_PROFILE_ID = "desktop"

# The two user adjustments ("Intensity" / "Smoothness") are offsets on top of a
# profile, not replacements. Their neutral points are the values already stored
# by 0.3.3 (saturation 55, smoothing 65), so upgrading applies the profile's
# intended look once — the sliders don't move the light a second time.
NEUTRAL_INTENSITY = 55
NEUTRAL_SMOOTHNESS = 65


@dataclass(frozen=True)
class ShapeConfig:
    """The per-frame HSV shaping between the spatial and temporal stages."""

    saturation: float = 1.4
    gamma: float = 1.0
    min_brightness: int = 0
    max_brightness: int = 255
    min_saturation: float = 0.0


@dataclass(frozen=True)
class ScreenProfile:
    profile_id: str
    sample: SampleConfig
    shape: ShapeConfig
    temporal: TemporalConfig


_PROFILES: dict[str, ScreenProfile] = {
    "desktop": ScreenProfile(
        profile_id="desktop",
        sample=SampleConfig(edge_weight=1.8, dominant=False, reject_black_bars=False),
        shape=ShapeConfig(saturation=1.35, gamma=1.05, min_brightness=18, min_saturation=0.18),
        temporal=TemporalConfig(half_life_s=0.16, max_rate=360, max_step=48),
    ),
    "game": ScreenProfile(
        profile_id="game",
        sample=SampleConfig(edge_weight=1.4, dominant=True, reject_black_bars=False),
        shape=ShapeConfig(saturation=1.7, gamma=1.1, min_brightness=8, min_saturation=0.3),
        temporal=TemporalConfig(half_life_s=0.05, max_rate=900, max_step=70),
    ),
    "movie": ScreenProfile(
        profile_id="movie",
        sample=SampleConfig(edge_weight=1.2, dominant=True, reject_black_bars=True),
        shape=ShapeConfig(saturation=1.25, gamma=1.0, min_brightness=0, min_saturation=0.12),
        temporal=TemporalConfig(half_life_s=0.22, max_rate=260, max_step=40),
    ),
}

PROFILE_IDS: tuple[str, ...] = ("desktop", "game", "movie")


def normalize_profile_id(profile_id: object) -> str:
    """A known profile id, or the default — never raises on stored junk."""
    key = str(profile_id or "").strip().lower()
    return key if key in _PROFILES else DEFAULT_PROFILE_ID


def get_profile(profile_id: object) -> ScreenProfile:
    return _PROFILES[normalize_profile_id(profile_id)]


@dataclass(frozen=True)
class ResolvedConfig:
    sample: SampleConfig
    shape: ShapeConfig
    temporal: TemporalConfig


def resolve_configs(profile: ScreenProfile, intensity: int, smoothness: int) -> ResolvedConfig:
    """Apply the user's Intensity/Smoothness on top of a profile.

    At the neutral points the profile is returned unchanged. Intensity scales the
    saturation boost; Smoothness scales the temporal half-life (calmer or
    snappier) — clamped so the extremes stay sane.
    """
    sat_scale = max(0.3, 1.0 + (int(intensity) - NEUTRAL_INTENSITY) / float(NEUTRAL_INTENSITY) * 0.7)
    hl_scale = max(0.2, min(2.5, 1.0 + (int(smoothness) - NEUTRAL_SMOOTHNESS) / float(NEUTRAL_SMOOTHNESS) * 1.2))

    shape = replace(profile.shape, saturation=profile.shape.saturation * sat_scale)
    temporal = replace(profile.temporal, half_life_s=profile.temporal.half_life_s * hl_scale)
    return ResolvedConfig(sample=profile.sample, shape=shape, temporal=temporal)
