from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from app.feature_gate import is_pro, refresh_pro_status


class LicenseRefresher(QObject):
    """Revalidates the Pro license off the UI thread.

    ``is_pro`` answers instantly from a local-only cache so the UI never blocks.
    This worker performs the authoritative check (which may hit the network) in a
    background thread and reports the result back on the main thread via
    ``finished(is_pro, changed)``.
    """

    finished = Signal(bool, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._running = False

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
