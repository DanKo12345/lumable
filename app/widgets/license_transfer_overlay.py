"""Moving a Pro licence to another computer.

An activation belongs to one installation, so the key on this machine has to be
handed back before it will work anywhere else. That is easy to do and easy not
to know about, which is why it is a named action in Settings rather than a link
somebody finds afterwards.

Three things this window is careful about.

The key is shown masked. It is a credential — what somebody types to claim a
purchase — and this window opens at exactly the sort of moment when a screen is
being shared with whoever is helping. Revealing and copying are separate,
deliberate acts.

The request runs off the UI thread. Handing a licence back is up to two calls to
Lemon Squeezy with a ten-second timeout each, and a window frozen for twenty
seconds looks like a window that has crashed.

Nothing is cleared until the server has confirmed. That rule lives in
deactivate_license and the ordering in license_transfer; this file only has to
avoid telling somebody a comforting story about what happened. A failure says
the licence is still here, because it is.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from app.license_transfer import FREED, NOT_FREED, masked_key
from app.theme import theme_manager
from app.widgets.liquid_button import LiquidButton


class _TransferWorker(QThread):
    """The network call, off the thread that draws the window."""

    done = Signal(str, str)

    def __init__(self, run: Callable[[], tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self._run = run

    def run(self) -> None:
        try:
            outcome, key = self._run()
        except Exception:
            # A failure is an answer, not a crash — and the message goes
            # nowhere near the field a key travels in.
            outcome, key = NOT_FREED, ""
        self.done.emit(str(outcome), str(key))


class LicenseTransferDialog(QDialog):
    def __init__(self, key: str, run_transfer: Callable[[], tuple[str, str]], tr, parent=None) -> None:
        super().__init__(parent)
        self._tr = tr
        self._key = str(key or "")
        self._run_transfer = run_transfer
        self._revealed = False
        self._worker: _TransferWorker | None = None
        self.freed = False

        self.setWindowTitle(tr("transfer.title"))
        self.setObjectName("licenseTransferDialog")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._apply_style()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        self._headline = QLabel(tr("transfer.headline"))
        self._headline.setObjectName("transferHeadline")
        self._headline.setWordWrap(True)
        self._headline.setTextFormat(Qt.PlainText)
        layout.addWidget(self._headline)

        self._body = QLabel(tr("transfer.body"))
        self._body.setObjectName("transferBody")
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.PlainText)
        layout.addWidget(self._body)

        key_box = QFrame(self)
        key_box.setObjectName("transferKeyBox")
        key_row = QHBoxLayout(key_box)
        key_row.setContentsMargins(14, 10, 10, 10)
        key_row.setSpacing(8)
        self._key_label = QLabel(masked_key(self._key))
        self._key_label.setObjectName("transferKey")
        self._key_label.setTextFormat(Qt.PlainText)
        self._key_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        key_row.addWidget(self._key_label, 1)

        self._reveal = LiquidButton(tr("transfer.reveal"), "ghost", self)
        self._reveal.clicked.connect(self._toggle_reveal)
        key_row.addWidget(self._reveal)

        self._copy = LiquidButton(tr("transfer.copy"), "ghost", self)
        self._copy.clicked.connect(self._copy_key)
        key_row.addWidget(self._copy)
        layout.addWidget(key_box)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self._close = LiquidButton(tr("transfer.cancel"), "ghost", self)
        self._close.clicked.connect(self.reject)
        buttons.addWidget(self._close)

        self._confirm = LiquidButton(tr("transfer.confirm"), "accent", self)
        self._confirm.setDefault(True)
        self._confirm.clicked.connect(self._start)
        buttons.addWidget(self._confirm)
        layout.addLayout(buttons)

    def _apply_style(self) -> None:
        palette = theme_manager.palette
        self.setStyleSheet(
            f"""
            QDialog#licenseTransferDialog {{
                background: {palette["surface_strong"]};
                border: 1px solid {palette["surface_border"]};
                color: {palette["text"]};
            }}
            QLabel {{
                background: transparent;
                color: {palette["text"]};
            }}
            QLabel#transferHeadline {{
                font-size: 17px;
                font-weight: 800;
            }}
            QLabel#transferBody {{
                color: {palette["text_soft"]};
                font-size: 13px;
                font-weight: 500;
            }}
            QFrame#transferKeyBox {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 12px;
            }}
            QLabel#transferKey {{
                color: {palette["text"]};
                font-family: "Cascadia Mono", "Consolas";
                font-size: 13px;
                font-weight: 700;
            }}
            """
        )

    # ── the key ───────────────────────────────────────────────────────
    def _toggle_reveal(self) -> None:
        self._revealed = not self._revealed
        self._key_label.setText(self._key if self._revealed else masked_key(self._key))
        self._reveal.setText(self._tr("transfer.hide" if self._revealed else "transfer.reveal"))

    def _copy_key(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._key)

    # ── the request ───────────────────────────────────────────────────
    def _start(self) -> None:
        self._confirm.setEnabled(False)
        self._close.setEnabled(False)
        self._headline.setText(self._tr("transfer.working"))
        self._worker = _TransferWorker(self._run_transfer, self)
        self._worker.done.connect(self._finished)
        self._worker.start()

    def _finished(self, outcome: str, key: str) -> None:
        self._close.setEnabled(True)
        if outcome == FREED:
            self.freed = True
            # The key is still on screen, and still worth copying: it is needed
            # on the other machine and this is the last place it is offered.
            self._headline.setText(self._tr("transfer.freed_headline"))
            self._body.setText(self._tr("transfer.freed_body"))
            if key:
                self._key = key
                self._key_label.setText(self._key if self._revealed else masked_key(self._key))
            self._confirm.hide()
            self._close.setText(self._tr("transfer.done"))
            return

        # Nothing was released, so nothing is said about anything having been.
        self._headline.setText(self._tr("transfer.failed_headline"))
        self._body.setText(self._tr("transfer.failed_body"))
        self._confirm.setEnabled(True)
        self._confirm.setText(self._tr("transfer.retry"))
