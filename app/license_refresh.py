from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal

from app.feature_gate import is_pro, refresh_pro_status


class LicenseRefresher(QObject):
    """Revalidates the Pro license off the UI thread.

    ``is_pro`` answers instantly from a local-only cache so the UI never blocks.
    This worker performs the authoritative check (which may hit the network) in a
    background thread and reports the result back on the main thread via
    ``finished(is_pro, changed)``.
    """

    finished = Signal(bool, bool)

    # How often to wake and consider asking. Not how often anything is asked:
    # the check itself decides that from the receipt's own issued_at, so most
    # of these wake-ups do nothing at all. Hourly is small enough that a
    # fortnight cannot pass unnoticed and large enough to cost nothing.
    WAKE_INTERVAL_MS = 60 * 60 * 1000

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._running = False
        # Without this a window left open never asks again. The refresher used
        # to be called once, a second after starting, so an application running
        # for a fortnight kept a cached yes long after the receipt behind it had
        # expired — and a revoked licence stayed Pro until somebody happened to
        # restart.
        self._timer = QTimer(self)
        self._timer.setInterval(self.WAKE_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)

    def start_watching(self) -> None:
        """Ask now, and keep asking for as long as this window is open."""
        self.refresh()
        self._timer.start()

    def stop_watching(self) -> None:
        self._timer.stop()

    def refresh(self) -> None:
        if self._running:
            return
        self._running = True
        previous = is_pro()
        thread = threading.Thread(target=self._run, args=(previous,), daemon=True)
        thread.start()

    def _run(self, previous: bool) -> None:
        try:
            current = refresh_pro_status()
        except Exception:
            current = previous
        finally:
            self._running = False
        try:
            self.finished.emit(bool(current), bool(current) != bool(previous))
        except RuntimeError:
            # The window can be closed while the background check is still running.
            pass
