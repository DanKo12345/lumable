from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuickMode:
    key: str
    label: str
    accent: str
    power: bool
    brightness: int
    speed: int
    effect_code: int
    color: tuple[int, int, int]

    def as_profile(self) -> dict:
        red, green, blue = self.color
        return {
            "name": self.label,
            "power": self.power,
            "brightness": self.brightness,
            "speed": self.speed,
            "effect_code": self.effect_code,
            "color": {"r": red, "g": green, "b": blue},
        }

    def matches(self, state: dict) -> bool:
        if bool(state.get("power")) != self.power:
            return False
        if int(state.get("brightness", -1)) != self.brightness:
            return False
        if int(state.get("effect_code", -1)) != self.effect_code:
            return False
        if self.effect_code != 0:
            return int(state.get("speed", -1)) == self.speed
        color = state.get("color", {})
        return (
            int(color.get("r", -1)),
            int(color.get("g", -1)),
            int(color.get("b", -1)),
        ) == self.color


QUICK_MODES: tuple[QuickMode, ...] = (
    QuickMode(
        key="chill",
        label="Chill",
        accent="#7fb7ff",
        power=True,
        brightness=74,
        speed=60,
        effect_code=0,
        color=(118, 174, 255),
    ),
    QuickMode(
        key="gaming",
        label="Gaming",
        accent="#f1ad84",
        power=True,
        brightness=90,
        speed=60,
        effect_code=0,
        color=(255, 126, 92),
    ),
    QuickMode(
        key="night",
        label="Night",
        accent="#b4a8ff",
        power=True,
        brightness=32,
        speed=45,
        effect_code=0,
        color=(255, 176, 98),
    ),
    QuickMode(
        key="rainbow",
        label="Rainbow",
        accent="#9a8cff",
        power=True,
        brightness=78,
        speed=35,
        effect_code=0x8A,
        color=(170, 96, 255),
    ),
)

QUICK_MODE_MAP: dict[str, QuickMode] = {mode.key: mode for mode in QUICK_MODES}
