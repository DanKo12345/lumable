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

from typing import Any, Protocol

from app.scenes import make_scene, plan_apply


class _Backend(Protocol):
    def set_power(self, on: bool, device_id: str | None) -> None: ...
    def set_color(self, red: int, green: int, blue: int, device_id: str | None) -> None: ...
    def set_brightness(self, value: int, device_id: str | None) -> None: ...
    def set_effect(self, code: int, speed: int | None, device_id: str | None) -> None: ...
    def set_pc_mode(self, mode: str) -> bool: ...


class SceneApplyService:
    def __init__(self, backend: _Backend) -> None:
        self._backend = backend

    def apply(
        self, scene: dict[str, Any], *, capabilities: dict[str, Any] | None = None, device_ids: list[str] | None = None
    ) -> dict[str, Any]:
        """Apply a scene, returning ``{"applied": [...], "skipped": [...]}``.

        ``device_ids`` is the scene's resolved target (from its ``target`` +
        groups). ``None`` means the default whole-group address (back-compat);
        an empty list means the target resolved to nothing, so per-device fields
        are reported as ``no_target`` rather than leaking onto every strip.
        """
        state = scene.get("state", {}) if isinstance(scene, dict) else {}
        plan = plan_apply(state, capabilities)
        applied: list[str] = []
        skipped: list[dict[str, str]] = list(plan["skipped"])
        targets: list[str | None] = list(device_ids) if device_ids is not None else [None]

        # Hand the strip back from any live stream before painting the base look.
        self._backend.set_pc_mode("off")

        def per_device(field: str, call) -> None:
            if not targets:  # target resolved to no strips
                skipped.append({"field": field, "reason": "no_target"})
                return
            for device_id in targets:
                call(device_id)
            applied.append(field)

        for action in plan["actions"]:
            op = action["op"]
            if op == "power":
                per_device("power", lambda d, on=action["on"]: self._backend.set_power(bool(on), d))
            elif op == "color":
                red, green, blue = action["rgb"]
                per_device(
                    "color", lambda d, r=red, g=green, b=blue: self._backend.set_color(int(r), int(g), int(b), d)
                )
            elif op == "brightness":
                per_device("brightness", lambda d, v=action["value"]: self._backend.set_brightness(int(v), d))
            elif op == "cct":
                # A real white channel arrives with the driver capability matrix
                # (0.3.3); until then we don't emulate it on RGB-only strips.
                skipped.append({"field": "cct", "reason": "not_wired"})
            elif op == "effect":
                effect = action["effect"]
                if effect.get("kind") == "firmware":
                    per_device("effect", lambda d, e=effect: self._backend.set_effect(int(e["ref"]), e.get("speed"), d))
                else:
                    # Selecting a specific software/DIY effect from a scene lands
                    # with the phone effect picker (0.3.3); report, don't fail.
                    skipped.append({"field": "effect", "reason": "pc_effect_pending"})
            elif op == "pc_mode":
                # PC modes are global to the machine, not per-strip.
                if self._backend.set_pc_mode(str(action["mode"])):
                    applied.append("pc_mode")
                else:
                    skipped.append({"field": "pc_mode", "reason": "refused"})

        return {"applied": applied, "skipped": skipped}


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
    state = {
        "power": power if isinstance(power, bool) else None,
        "rgb": rgb,
        "brightness": status.get("brightness"),
        "effect": effect if isinstance(effect, dict) else None,
        "pc_mode": status.get("pc_mode"),
    }
    return make_scene(name, state, target=target, icon=icon, color=color)
