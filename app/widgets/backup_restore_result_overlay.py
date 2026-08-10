"""What a finished restore says, and the only way out of it.

Deliberately not the confirmation overlay with a flag or two. That one asks a
question before something happens and offers a way to back out; this one reports
something that has already happened and cannot be undone — the settings file is
replaced and writing is frozen. Sharing a widget between the two would put a
warning triangle and a Cancel button on a success, which is the one place a
cancel would be a lie.

So it closes in exactly one way. Escape, a click on the backdrop and the window
title bar all lead to the same place as the button, because there is no state
left to return to: everything still in memory describes the settings that were
just replaced.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.theme import qcolor_from_token, theme_manager
from app.widgets.animation_helpers import play_or_complete
from app.widgets.liquid_button import LiquidButton

_PANEL_WIDTH = 460
# The panel grows with its text; the cap is what keeps a long backup path from
# pushing the button off a small window.
_MAX_PANEL_HEIGHT_RATIO = 0.86
# Margins, spacing and the button — everything in the panel that is not the
# message, so the message can be told how much is left.
_PANEL_CHROME = 112
_MIN_MESSAGE_HEIGHT = 90


def _wraps(label: QLabel) -> None:
    """Let a wrapped label claim the height its text needs."""
    policy = label.sizePolicy()
    policy.setHeightForWidth(True)
    policy.setVerticalPolicy(QSizePolicy.MinimumExpanding)
    label.setSizePolicy(policy)


class BackupRestoreResultOverlay(QWidget):
    """The result of a restore, with one button: close the app."""

    close_requested = Signal()

    def __init__(self, labels: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._fade_anim: QPropertyAnimation | None = None
        self._panel_anim: QPropertyAnimation | None = None
        if parent is not None:
            self.setGeometry(parent.rect())

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)

        self._panel = QWidget(self)
        self._panel.setObjectName("backupResultPanel")
        self._panel.setAttribute(Qt.WA_StyledBackground, True)
        self._panel.setFixedWidth(_PANEL_WIDTH)
        # Wrapped text only reports its real height through heightForWidth, and
        # a policy without it gives every paragraph one line and clips the rest —
        # silently, and worst in the language with the longest sentences.
        policy = QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self._panel.setSizePolicy(policy)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(28, 24, 28, 22)
        panel_layout.setSpacing(12)
        panel_layout.setSizeConstraint(QLayout.SetMinimumSize)

        # The message scrolls if it has to; the button never does. On the
        # smallest window the text alone is taller than the panel is allowed to
        # be, and a button pushed past the edge would leave no way out of a
        # screen whose whole point is that there is exactly one.
        self._scroll = QScrollArea(self._panel)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("background: transparent;")
        message = QWidget()
        message.setObjectName("backupResultMessage")

        message_layout = QVBoxLayout(message)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        # A calm tick, not a warning triangle: nothing here went wrong.
        mark = QLabel("✓", message)
        mark.setObjectName("backupResultMark")
        mark.setFixedSize(30, 30)
        mark.setAlignment(Qt.AlignCenter)
        title = QLabel(labels.get("title", ""), message)
        title.setObjectName("backupResultTitle")
        title.setWordWrap(True)
        _wraps(title)
        title_row.addWidget(mark, 0, Qt.AlignVCenter)
        title_row.addWidget(title, 1, Qt.AlignVCenter)
        message_layout.addLayout(title_row)

        self._summary = QLabel(labels.get("summary", ""), message)
        self._summary.setObjectName("backupResultBody")
        self._summary.setWordWrap(True)
        _wraps(self._summary)
        message_layout.addWidget(self._summary)

        warning = labels.get("groups", "")
        if warning:
            # Its own line and its own colour: the groups are back by name and
            # light nothing until strips are assigned to them again, and that is
            # the one thing here the user still has to do.
            self._groups = QLabel(warning, message)
            self._groups.setObjectName("backupResultWarning")
            self._groups.setWordWrap(True)
            _wraps(self._groups)
            message_layout.addWidget(self._groups)

        copy_text = labels.get("copy", "")
        if copy_text:
            self._copy = QLabel(copy_text, message)
            self._copy.setObjectName("backupResultPath")
            self._copy.setWordWrap(True)
            _wraps(self._copy)
            self._copy.setTextInteractionFlags(Qt.TextSelectableByMouse)
            message_layout.addWidget(self._copy)

        self._restart = QLabel(labels.get("restart", ""), message)
        self._restart.setObjectName("backupResultBody")
        self._restart.setWordWrap(True)
        _wraps(self._restart)
        message_layout.addWidget(self._restart)
        message_layout.addStretch(1)
        self._scroll.setWidget(message)
        panel_layout.addWidget(self._scroll, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.close_button = LiquidButton(labels.get("close", ""), role="accent")
        self.close_button.setMinimumHeight(40)
        self.close_button.clicked.connect(self._finish)
        button_row.addWidget(self.close_button)
        panel_layout.addSpacing(4)
        panel_layout.addLayout(button_row)

        # Read out as one thing: a screen reader should not have to hunt four
        # labels to learn what happened.
        spoken = " ".join(
            part
            for part in (
                labels.get("title", ""),
                labels.get("summary", ""),
                labels.get("groups", ""),
                labels.get("copy", ""),
                labels.get("restart", ""),
            )
            if part
        )
        self.setAccessibleName(labels.get("title", ""))
        self.setAccessibleDescription(spoken)
        self.close_button.setAccessibleDescription(spoken)
        self._apply_style()

    # ── lifecycle ─────────────────────────────────────────────────────
    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
            self._panel.setMaximumHeight(int(parent.height() * _MAX_PANEL_HEIGHT_RATIO))
        self._fit_message()
        self.show()
        # Again once Qt has laid the labels out: only then does the message know
        # how tall it really is.
        QTimer.singleShot(0, self._fit_message)
        self.raise_()
        # Straight onto the only button there is.
        self.close_button.setFocus(Qt.PopupFocusReason)
        self._start_open_animation()

    def _fit_message(self) -> None:
        """Give the message exactly the room it needs, or all there is.

        A scroll area asks for almost nothing by default, which would make the
        usual short message scroll inside a half-empty panel. Sized here, where
        the window is known: the text gets its full height when it fits, and the
        cap takes over only when it does not.
        """
        message = self._scroll.widget()
        # Neither sizeHint nor heightForWidth is trustworthy for a column of
        # wrapped labels — both under-report until the labels have actually been
        # laid out at this width. The laid-out height is, which is why this runs
        # once more after the overlay is shown.
        content = max(message.sizeHint().height(), message.height())
        room = self._panel.maximumHeight() - _PANEL_CHROME
        self._scroll.setMinimumHeight(max(_MIN_MESSAGE_HEIGHT, min(content, room)))

    def _finish(self) -> None:
        self.close_requested.emit()

    def _start_open_animation(self) -> None:
        self.layout().activate()
        end_pos = self._panel.pos()
        self._panel.move(end_pos + QPoint(0, 12))
        self._opacity_effect.setOpacity(0.0)
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(170)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._panel_anim = QPropertyAnimation(self._panel, b"pos", self)
        self._panel_anim.setDuration(205)
        self._panel_anim.setStartValue(end_pos + QPoint(0, 12))
        self._panel_anim.setEndValue(end_pos)
        self._panel_anim.setEasingCurve(QEasingCurve.OutCubic)
        play_or_complete(self._fade_anim)
        play_or_complete(self._panel_anim)

    # ── there is only one way out ─────────────────────────────────────
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            # Dismissing this would leave the app running on settings that no
            # longer exist, which is the state the restore was avoiding.
            self._finish()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        # A click on the backdrop means the same as the button. Ignoring it
        # would just look broken.
        self._finish()
        event.accept()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in {QEvent.Type.Resize, QEvent.Type.Move}:
            parent = self.parentWidget()
            if parent is not None:
                self.setGeometry(parent.rect())
                self._panel.setMaximumHeight(int(parent.height() * _MAX_PANEL_HEIGHT_RATIO))
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 96 if theme_manager.is_dark else 64))
        painter.drawRect(self.rect())

    def _apply_style(self) -> None:
        palette = theme_manager.palette
        success = qcolor_from_token(palette["success_start"]).name()
        warning = qcolor_from_token(palette["danger_start"]).name()
        self.setStyleSheet(
            f"""
            #backupResultPanel {{
                background: {palette["surface_strong"]};
                border: 1px solid {palette["surface_border"]};
                border-radius: 16px;
            }}
            #backupResultMark {{
                color: {success};
                font-size: 20px;
                font-weight: 600;
                background: rgba(113, 216, 192, 0.14);
                border-radius: 15px;
            }}
            #backupResultTitle {{
                color: {palette["text"]};
                font-size: 17px;
                font-weight: 600;
            }}
            #backupResultBody {{
                color: {palette["text_soft"]};
                font-size: 13px;
            }}
            #backupResultWarning {{
                color: {warning};
                font-size: 13px;
            }}
            #backupResultPath {{
                color: {palette["muted"]};
                font-size: 12px;
            }}
            """
        )
