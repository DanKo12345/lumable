"""One line about a licence, and a button when there is something to do.

It shows what app.license_status decided and nothing else — no opinion of its
own about connections, dates or services. That matters more than it sounds: the
same situation is reachable from several places, and a widget that reasons for
itself is a second answer waiting to disagree with the first.

Hidden entirely when there is nothing to say, which is most of the time. A strip
that is always present, saying "everything is fine", is a strip people stop
seeing — and then the one time it says something else, they do not see that
either.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from app.license_status import Status


class LicenseStatusBanner(QWidget):
    def __init__(self, tr: Callable[[str], str], recheck: Callable[[], None], parent=None) -> None:
        super().__init__(parent)
        self._tr = tr
        self._recheck = recheck

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.PlainText)
        layout.addWidget(self._label, 1)

        self._button = QPushButton(tr("license_status.recheck"), self)
        self._button.setCursor(Qt.PointingHandCursor)
        self._button.clicked.connect(self._pressed)
        layout.addWidget(self._button, 0, Qt.AlignVCenter)

        self.hide()

    def show_status(self, status: Status) -> None:
        """Display a decision. The only way anything here changes."""
        if not status.message:
            self.hide()
            return

        self._label.setText(self._tr(status.message))
        self._button.setVisible(status.can_recheck)
        # Whatever else changed, a request that has finished leaves the button
        # usable again. Otherwise one failed check would end with a message
        # telling somebody to try again beside a button that cannot be pressed.
        self._button.setEnabled(status.can_recheck)
        self.show()

    def _pressed(self) -> None:
        # Disabled immediately rather than when the answer comes back: the
        # request runs in the background and a button that stays live invites
        # somebody to press it four more times while they wait.
        self._button.setEnabled(False)
        self._recheck()

    def retranslate(self) -> None:
        self._button.setText(self._tr("license_status.recheck"))
