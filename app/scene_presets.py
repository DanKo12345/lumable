from __future__ import annotations

from dataclasses import dataclass

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class ScenePreset:
    """A built-in one-tap mood: a colour + brightness applied to the strip.

    Kept driver-agnostic (static colour only, no firmware effect codes) so a
    preset looks the same on every supported controller. Names are localised via
    the ``scene.<key>`` i18n keys.
    """

    key: str
    rgb: RGB
    brightness: int


SCENE_PRESETS: tuple[ScenePreset, ...] = (
    # The colours people actually reach for: warm/cool white first, then a clean
    # primary palette, plus two genuinely common moods (sunset glow, night-light).
    ScenePreset("warm_white", (255, 180, 110), 100),
    ScenePreset("cool_white", (220, 235, 255), 100),
    ScenePreset("red", (255, 0, 0), 100),
    ScenePreset("orange", (255, 95, 0), 100),
    ScenePreset("yellow", (255, 210, 0), 100),
    ScenePreset("green", (0, 210, 60), 100),
    ScenePreset("blue", (0, 90, 255), 100),
    ScenePreset("purple", (150, 40, 255), 100),
    ScenePreset("pink", (255, 55, 150), 100),
    ScenePreset("dawn", (255, 150, 110), 80),
    ScenePreset("sunset", (255, 70, 25), 85),
    ScenePreset("nightlight", (255, 115, 45), 18),
)

_BY_KEY = {preset.key: preset for preset in SCENE_PRESETS}


def get_scene_preset(key: str) -> ScenePreset | None:
    return _BY_KEY.get(str(key))
