"""Applying a scene, and snapshotting the current state back into one.

The apply service is deliberately thin: it drives the already-tested
:class:`~app.local_api.backend.QtApiBackend` (which marshals every call onto the
Qt main thread), so this module has no Qt of its own and is unit-testable with a
fake backend. It follows the agreed rules:

- Stop any running stream first (via ``set_pc_mode("off")``) so nothing fights
  over the strip, then apply the base light state, then start the scene's PC mode
  last if it has one.
- Best-effort: an action the hardware or the current build can't do is recorded
  in the report, never a hard failure.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from app.scenes import make_scene, plan_apply

# Which report field an action maps to when it can't run at all.
_FIELD_BY_OP = {"power": "power", "color": "color", "brightness": "brightness", "effect": "effect", "cct": "cct"}


class _Backend(Protocol):
    def set_power(self, on: bool, device_id: str | None) -> None: ...
    def set_color(self, red: int, green: int, blue: int, device_id: str | None) -> None: ...
    def set_brightness(self, value: int, device_id: str | None) -> None: ...
    def set_effect(self, code: int, speed: int | None, device_id: str | None) -> None: ...
    def set_pc_mode(self, mode: str, preset: str | None = None) -> bool: ...


class SceneApplyService:
    def __init__(self, backend: _Backend) -> None:
        self._backend = backend

    def apply(
        self,
        scene: dict[str, Any],
        *,
        capabilities: dict[str, Any] | None = None,
        device_ids: list[str] | None = None,
        capabilities_for: Callable[[str | None], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Apply a scene, returning ``{"applied": [...], "skipped": [...]}``.

        ``device_ids`` is the scene's resolved target (from its ``target`` +
        groups). ``None`` means the default whole-group address (back-compat);
        an empty list means the target resolved to nothing, so per-device fields
        are reported as ``no_target`` rather than leaking onto every strip.
        """
        state = scene.get("state", {}) if isinstance(scene, dict) else {}
        targets: list[str | None] = list(device_ids) if device_ids is not None else [None]
        applied: list[str] = []
        skipped: list[dict[str, str]] = []

        def remember(field: str) -> None:
            if field not in applied:
                applied.append(field)

        def note(field: str, reason: str, device_id: str | None = None) -> None:
            entry: dict[str, str] = {"field": field, "reason": reason}
            if device_id:
                entry["target"] = device_id  # which strip couldn't take it
            skipped.append(entry)

        def caps_for(device_id: str | None) -> dict[str, Any] | None:
            return capabilities_for(device_id) if capabilities_for is not None else capabilities

        # The target resolved to no strips at all (a deleted group, or one whose
        # strips are offline). Report and get out *before* touching anything
        # global: stopping the running screen/music/DIY stream for a scene that
        # cannot apply would be worse than doing nothing.
        if not targets:
            plan = plan_apply(state, capabilities)
            skipped.extend(plan["skipped"])
            for action in plan["actions"]:
                note(_FIELD_BY_OP.get(action["op"], action["op"]), "no_target")
            return {"applied": applied, "skipped": skipped}

        # Hand the strip back from any live stream before painting the base look.
        self._backend.set_pc_mode("off")

        pc_mode_handled = False
        for device_id in targets:
            # Capabilities are resolved per target: a group can mix controllers,
            # so an effect may be fine on one strip and unsupported on another.
            plan = plan_apply(state, caps_for(device_id))
            for entry in plan["skipped"]:
                note(str(entry.get("field", "")), str(entry.get("reason", "")), device_id)

            for action in plan["actions"]:
                if action["op"] == "pc_mode":
                    if pc_mode_handled:  # PC modes are global, not per-strip
                        continue
                    pc_mode_handled = True
                    self._start_pc_mode(action["mode"], action.get("preset"), remember, note)
                else:
                    self._run_device_action(action, device_id, remember, note)

        return {"applied": applied, "skipped": skipped}

    def _start_pc_mode(self, mode: Any, preset: Any, remember, note) -> None:
        preset = str(preset).strip() if isinstance(preset, str) and preset.strip() else None
        if self._backend.set_pc_mode(str(mode), preset):
            remember("pc_mode")
        else:
            note("pc_mode", "refused")

    def _run_device_action(self, action: dict[str, Any], device_id: str | None, remember, note) -> None:
        op = action["op"]
        if op == "power":
            self._backend.set_power(bool(action["on"]), device_id)
            remember("power")
        elif op == "color":
            red, green, blue = action["rgb"]
            self._backend.set_color(int(red), int(green), int(blue), device_id)
            remember("color")
        elif op == "brightness":
            self._backend.set_brightness(int(action["value"]), device_id)
            remember("brightness")
        elif op == "cct":
            # A real white channel needs hardware support; we never fake it.
            note("cct", "not_wired", device_id)
        elif op == "effect":
            effect = action["effect"]
            if effect.get("kind") == "firmware":
                self._backend.set_effect(int(effect["ref"]), effect.get("speed"), device_id)
                remember("effect")
            else:
                # Selecting a specific software/DIY effect from a scene lands with
                # the phone effect picker; report, don't fail.
                note("effect", "pc_effect_pending", device_id)


def scene_from_status(
    status: dict[str, Any],
    name: str,
    *,
    target: dict[str, Any] | None = None,
    icon: str = "",
    color: str = "",
) -> dict[str, Any]:
    """Snapshot a live ``/status`` dict into a saveable scene (power, colour,
    brightness and any active PC mode)."""
    status = status if isinstance(status, dict) else {}
    colour = status.get("color") if isinstance(status.get("color"), dict) else None
    rgb = None
    if colour and all(key in colour for key in ("r", "g", "b")):
        rgb = [colour["r"], colour["g"], colour["b"]]
    if not color and rgb is not None:
        # A colour chip for the scene, so lists can show a dot without extra state.
        color = "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(c))) for c in rgb))
    power = status.get("power")
    effect = status.get("effect")
    pc_mode_kind = status.get("pc_mode")
    # Carry the active mode's preset (e.g. the screen-sync profile) so the scene
    # restores the exact look, not just "screen sync on". normalize_scene coerces
    # this to the canonical {kind, preset} form (and legacy strings on read).
    pc_mode = (
        {"kind": pc_mode_kind, "preset": status.get("pc_mode_preset")} if pc_mode_kind else None
    )
    state = {
        "power": power if isinstance(power, bool) else None,
        "rgb": rgb,
        "brightness": status.get("brightness"),
        "effect": effect if isinstance(effect, dict) else None,
        "pc_mode": pc_mode,
    }
    return make_scene(name, state, target=target, icon=icon, color=color)
