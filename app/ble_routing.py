"""Pure routing decision for addressed BLE writes (no bleak, no Qt).

Given a target set of addresses plus the current primary and mirror addresses,
work out which connections a command should reach and whether the primary is
among them. The addressed write methods in ``ble.py`` are thin wrappers over
this, so the tricky "who gets written / do we sync the primary caches" logic is
unit-testable without any BLE.

Rules:
- ``targets is None`` means "all connected strips" — the legacy whole-set mode
  used by music/screen/DIY, unchanged.
- A concrete (possibly empty) set writes only to the addresses in it.
- ``sync_primary`` is True only when the primary is actually written, so the
  global colour/brightness caches and the desktop UI are updated for a primary
  write but never for a mirror-only one.
"""

from __future__ import annotations

from collections.abc import Iterable


def swap_primary(primary: object, mirrors: list, address: str | None) -> tuple[object, list] | None:
    """Promote the mirror at ``address`` to primary, demoting the current one.

    Returns ``(new_primary, new_mirrors)``, or ``None`` when nothing should
    change — an unknown address, the strip that is already primary, or no live
    primary to swap with. Pure: callers pass whatever objects carry ``.address``,
    so the ordering rules are testable without any BLE.
    """
    wanted = str(address or "").strip()
    if not wanted or primary is None:
        return None
    if str(getattr(primary, "address", "") or "").strip() == wanted:
        return None  # already the main strip

    promoted = next((m for m in mirrors if str(getattr(m, "address", "") or "").strip() == wanted), None)
    if promoted is None:
        return None

    # Keep the remaining mirrors in order and park the old primary at the end,
    # so the list reads as "the strips that follow the main one".
    remaining = [m for m in mirrors if m is not promoted]
    return promoted, [*remaining, primary]


def normalize_addresses(addresses: Iterable[str] | None) -> set[str] | None:
    if addresses is None:
        return None
    return {str(address).strip() for address in addresses if str(address).strip()}


def plan_targets(
    targets: Iterable[str] | None,
    primary_address: str | None,
    mirror_addresses: Iterable[str] | None,
) -> dict[str, object]:
    """Return ``{primary, mirrors, written, sync_primary}`` for a command."""
    primary = str(primary_address or "").strip()
    mirrors = [str(address).strip() for address in (mirror_addresses or []) if str(address).strip()]

    target_set = normalize_addresses(targets)

    def included(address: str) -> bool:
        return target_set is None or address in target_set

    primary_written = bool(primary) and included(primary)
    mirrors_written = [address for address in mirrors if included(address)]
    written = ([primary] if primary_written else []) + mirrors_written

    return {
        "primary": primary_written,
        "mirrors": mirrors_written,
        "written": written,
        # Only reach into the shared primary caches / desktop sliders when the
        # primary strip is actually part of this write.
        "sync_primary": primary_written,
    }
