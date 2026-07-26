from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

# Motion modes for the UI. Not a boolean: "system" defers to the OS accessibility
# setting through a provider, "reduced" forces reduced motion, "full" forces all
# animations on. Stored under the ``motion_mode`` setting.
MOTION_MODES = ("system", "reduced", "full")
DEFAULT_MOTION_MODE = "system"


def normalize_motion_mode(value: object) -> str:
    """Coerce a stored/user value to a known mode; anything unknown → system."""
    text = str(value or "").strip().lower()
    return text if text in MOTION_MODES else DEFAULT_MOTION_MODE


class MotionPolicy(QObject):
    """Single source of truth for whether UI motion should be reduced.

    The resolved state changes only on :meth:`refresh` — the system provider is
    never called at import time, and any provider failure falls back to *not*
    reduced (animations stay on) so a probe error never silently kills the UI's
    life. Widgets consult :attr:`reduced` and react to :attr:`changed`; they must
    not re-derive the decision themselves.
    """

    changed = Signal(bool)  # resolved reduced state, emitted only when it changes

    def __init__(self, provider: Callable[[], bool] | None = None) -> None:
        super().__init__()
        self._mode = DEFAULT_MOTION_MODE
        self._provider = provider
        self._reduced = False

    def set_provider(self, provider: Callable[[], bool] | None) -> None:
        """Install the system-motion probe (e.g. the Windows one). Injectable so
        tests never touch the real OS API. Does not refresh on its own."""
        self._provider = provider

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def reduced(self) -> bool:
        return self._reduced

    def set_mode(self, mode: object) -> None:
        # Always re-resolve, even when the mode string is unchanged: a typical
        # startup is set_provider(...) then set_mode(stored_mode) where the stored
        # mode is already the default "system", and the provider must still be
        # read. ``changed`` still only fires when the resolved value flips.
        self._mode = normalize_motion_mode(mode)
        self.refresh()

    def refresh(self) -> None:
        """Recompute the resolved state. Call this after the app becomes active
        again so a changed Windows setting is picked up without a native event
        filter. Emits :attr:`changed` only when the resolved value flips."""
        resolved = self._resolve()
        if resolved != self._reduced:
            self._reduced = resolved
            self.changed.emit(resolved)

    def _resolve(self) -> bool:
        if self._mode == "reduced":
            return True
        if self._mode == "full":
            return False
        # "system": defer to the provider; any failure means animations stay on.
        if self._provider is None:
            return False
        try:
            return bool(self._provider())
        except Exception:
            return False


# App-wide singleton. Constructing it performs no OS probe (provider is None and
# refresh() is not called here) — the app installs a provider and refreshes once
# settings are loaded.
motion_policy = MotionPolicy()
