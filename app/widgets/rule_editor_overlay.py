"""The rule editor: one overlay for creating and for changing a rule.

Shaped like the rest of the app's dialogs — a panel with a pinned header and
footer and a scrolling middle — because the form is taller than the smallest
window the app supports, and the two things that must never be off-screen are the
reason a rule cannot be saved and the button that saves it.

What this widget knows and what it does not:

* It knows the *shape* of a rule form, from :mod:`app.automation_rule_form`: which
  field belongs to which trigger, when background is possible, what is still
  wrong. That module has no Qt in it, so those answers are tested without a window.
* It knows no wording. Every string arrives in ``labels``, the way the other
  overlays in this package take theirs, so the widget never reaches for the
  localisation manager and can be built in a test with five strings.
* It saves nothing. ``saved`` carries the form out to the controller, which is the
  only thing here allowed to talk to the automation facade.

Two behaviours worth stating, because they are what makes the form honest rather
than merely tidy:

* **Save is refused with a reason, never in silence.** The problem line sits in
  the pinned footer next to the button it disables, so the answer to "why can't I
  save" is always on screen — a disabled button with the explanation scrolled out
  of view is the same as no explanation.
* **Only the fields the current choices use are shown.** Changing the trigger from
  a time to an app takes the day chips away with it, so the form cannot collect a
  setting the rule has no place to keep.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTime,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.automation_rule_form import (
    ACTION_CHOICES,
    CHOICE_SCENE,
    EXECUTION_BACKGROUND,
    EXECUTION_RUNTIME,
    MAX_NAME_LENGTH,
    PROBLEM_SCENE,
    PROBLEM_SCENE_MISSING,
    TRIGGER_CHOICES,
    TRIGGER_FIELDS,
    background_allowed,
    cooldown_options,
    form_problems,
    idle_options,
    normalized,
    priority_options,
)
from app.theme import overlay_panel_colors, qcolor_from_token, theme_manager
from app.widgets.animation_helpers import play_or_complete
from app.widgets.clickable_label import ClickableLabel
from app.widgets.day_toggle import DayToggle
from app.widgets.liquid_button import LiquidButton
from app.widgets.static_popup_combo_box import StaticPopupComboBox
from app.widgets.themed_line_edit import ThemedLineEdit
from app.widgets.time_button import TimeButton

PANEL_W = 560
PANEL_MIN_H = 320
PANEL_MAX_H = 620
# The label column and the chips are sized together: seven day chips plus the label
# have to fit the panel's content width with the scrollbar showing, or the last chip
# ends up underneath it.
LABEL_W = 132
FIELD_H = 40
DAY_W = 40
DAY_H = 32


class _EditorPanel(QFrame):
    """The dialog surface, painted like the other overlay panels."""

    RADIUS = 24.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Fixed width; the owner controls the height so the panel can fit a short
        # window with its centre scrolling.
        self.setFixedWidth(PANEL_W)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        panel_top, panel_bottom = overlay_panel_colors()
        fill.setColorAt(0.0, panel_top)
        fill.setColorAt(1.0, panel_bottom)
        painter.fillPath(path, fill)

        shine = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        shine.setColorAt(0.0, QColor(255, 255, 255, 30 if theme_manager.is_dark else 62))
        shine.setColorAt(0.48, QColor(255, 255, 255, 6 if theme_manager.is_dark else 16))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(96 if theme_manager.is_dark else 108)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class RuleEditorOverlay(QWidget):
    """Create or change one rule. Answers on ``saved`` / ``delete_requested``."""

    saved = Signal(dict)
    delete_requested = Signal()
    closed = Signal()

    def __init__(
        self,
        labels: dict[str, str],
        form: dict[str, Any],
        *,
        scene_options: Any = (),
        can_delete: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._labels = labels
        self._form = dict(form)
        self._scene_options = [(str(key), str(name)) for key, name in scene_options]
        self._scene_ids = {key for key, _name in self._scene_options}
        # A scene this rule points at that no longer exists. Remembered because the
        # combo cannot hold it: without this the reason the rule stopped working is
        # lost the moment the editor opens.
        self._missing_scene = (
            str(form.get("scene_id", ""))
            if form.get("action") == CHOICE_SCENE and str(form.get("scene_id", "")) not in self._scene_ids
            else ""
        )
        self._fade_anim: QPropertyAnimation | None = None
        self._panel_anim: QPropertyAnimation | None = None
        self._rows: dict[str, QWidget] = {}
        # Set before anything is built: adding the first item to a combo emits
        # currentIndexChanged, which would reach _on_changed before the widgets it
        # reads even exist.
        self._loading = True
        if parent is not None:
            self.setGeometry(parent.rect())
        self._apply_style()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        self._panel = _EditorPanel(self)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(28, 16, 28, 18)
        panel_layout.setSpacing(10)
        panel_layout.addLayout(self._build_header())
        panel_layout.addWidget(self._build_form(), 1)
        panel_layout.addWidget(self._build_footer(can_delete))

        self._load(self._form)

    # ── construction ──────────────────────────────────────────────────
    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel(self._labels.get("title", ""), self._panel)
        title.setObjectName("ruleEditorTitle")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.addWidget(title, 1, Qt.AlignVCenter)
        self._close_button = ClickableLabel("✕", self._panel)
        self._close_button.setObjectName("ruleEditorClose")
        self._close_button.setFixedSize(32, 32)
        self._close_button.setAlignment(Qt.AlignCenter)
        self._close_button.setCursor(Qt.PointingHandCursor)
        self._close_button.setToolTip(self._labels.get("close", ""))
        self._close_button.setAccessibleName(self._labels.get("close", "Close"))
        self._close_button.clicked.connect(self.close_overlay)
        header.addWidget(self._close_button, 0, Qt.AlignTop | Qt.AlignRight)
        return header

    def _build_form(self) -> QScrollArea:
        self._scroll = QScrollArea(self._panel)
        self._scroll.setObjectName("ruleEditorScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setAttribute(Qt.WA_TranslucentBackground)
        self._scroll.viewport().setAutoFillBackground(False)

        centre = QWidget()
        centre.setObjectName("ruleEditorContent")
        column = QVBoxLayout(centre)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        self.name_input = ThemedLineEdit(centre)
        self.name_input.setObjectName("ruleEditorInput")
        self.name_input.setPlaceholderText(self._labels.get("name_placeholder", ""))
        # Stopped at the length the schema stores rather than truncated on the way
        # in: typing a name and being shown a shorter one after saving is the app
        # editing the user's label without saying so.
        self.name_input.setMaxLength(MAX_NAME_LENGTH)
        self.name_input.setMinimumHeight(FIELD_H)
        self.name_input.textChanged.connect(self._on_changed)
        column.addWidget(self._row("name", self._labels.get("name", ""), self.name_input))

        self.trigger_combo = self._combo()
        for kind in TRIGGER_CHOICES:
            self.trigger_combo.addItem(self._labels.get(f"trigger_{kind}", kind), kind)
        self.trigger_combo.currentIndexChanged.connect(self._on_changed)
        column.addWidget(self._row("trigger", self._labels.get("trigger", ""), self.trigger_combo))

        self.time_button = TimeButton("21:00", centre)
        self.time_button.set_picker_title(self._labels.get("time", ""))
        self.time_button.set_picker_labels(
            hours=self._labels.get("picker_hours", "Hours"),
            minutes=self._labels.get("picker_minutes", "Minutes"),
            ok=self._labels.get("picker_ok", "OK"),
        )
        self.time_button.timeChanged.connect(self._on_changed)
        column.addWidget(self._row("time_at", self._labels.get("time", ""), self.time_button, stretch=False))

        self.day_buttons: list[DayToggle] = []
        days_box = QWidget(centre)
        days_layout = QHBoxLayout(days_box)
        days_layout.setContentsMargins(0, 0, 0, 0)
        days_layout.setSpacing(5)
        for index in range(7):
            chip = DayToggle(self._labels.get(f"day_{index}", str(index)), lambda: theme_manager.palette, days_box)
            chip.setFixedSize(DAY_W, DAY_H)
            chip.clicked.connect(self._on_changed)
            self.day_buttons.append(chip)
            days_layout.addWidget(chip)
        days_layout.addStretch(1)
        column.addWidget(self._row("days", self._labels.get("days", ""), days_box))

        self.app_input = ThemedLineEdit(centre)
        self.app_input.setObjectName("ruleEditorInput")
        self.app_input.setPlaceholderText(self._labels.get("app_placeholder", ""))
        self.app_input.setMinimumHeight(FIELD_H)
        self.app_input.textChanged.connect(self._on_changed)
        column.addWidget(self._row("app", self._labels.get("app", ""), self.app_input))

        self.idle_combo = self._combo()
        self.idle_combo.currentIndexChanged.connect(self._on_changed)
        column.addWidget(self._row("minutes", self._labels.get("idle", ""), self.idle_combo))

        self.action_combo = self._combo()
        for choice in ACTION_CHOICES:
            self.action_combo.addItem(self._labels.get(f"action_{choice}", choice), choice)
        self.action_combo.currentIndexChanged.connect(self._on_changed)
        column.addWidget(self._row("action", self._labels.get("action", ""), self.action_combo))

        self.scene_combo = self._combo()
        self.scene_combo.addItem(self._labels.get("scene_none", ""), "")
        for scene_id, name in self._scene_options:
            self.scene_combo.addItem(name, scene_id)
        self.scene_combo.currentIndexChanged.connect(self._on_changed)
        column.addWidget(self._row("scene_id", self._labels.get("scene", ""), self.scene_combo))

        self.background_button = LiquidButton(self._labels.get("off", ""), "ghost", centre)
        self.background_button.setCheckable(True)
        self.background_button.setFixedHeight(FIELD_H)
        self.background_button.setMinimumWidth(120)
        self.background_button.setAccessibleName(self._labels.get("background", ""))
        self.background_button.clicked.connect(self._on_changed)
        column.addWidget(
            self._row("execution", self._labels.get("background", ""), self.background_button, stretch=False)
        )
        self.background_hint = QLabel(self._labels.get("background_hint", ""), centre)
        self.background_hint.setObjectName("ruleEditorHint")
        self.background_hint.setWordWrap(True)
        column.addWidget(self.background_hint)

        # Priority and cooldown are real, and almost nobody needs them. Folded away
        # so the form reads as "when / then" at a glance, and still reachable.
        self.advanced_button = LiquidButton(self._labels.get("advanced", ""), "ghost", centre)
        self.advanced_button.setCheckable(True)
        self.advanced_button.setFixedHeight(34)
        self.advanced_button.setMinimumWidth(140)
        self.advanced_button.clicked.connect(self._toggle_advanced)
        advanced_row = QHBoxLayout()
        advanced_row.setContentsMargins(0, 4, 0, 0)
        advanced_row.addWidget(self.advanced_button)
        advanced_row.addStretch(1)
        column.addLayout(advanced_row)

        self.advanced_box = QWidget(centre)
        advanced_layout = QVBoxLayout(self.advanced_box)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)
        self.priority_combo = self._combo()
        self.priority_combo.currentIndexChanged.connect(self._on_changed)
        advanced_layout.addWidget(
            self._row("priority", self._labels.get("priority", ""), self.priority_combo, track=False)
        )
        self.cooldown_combo = self._combo()
        self.cooldown_combo.currentIndexChanged.connect(self._on_changed)
        advanced_layout.addWidget(
            self._row("cooldown", self._labels.get("cooldown", ""), self.cooldown_combo, track=False)
        )
        self.advanced_box.setVisible(False)
        column.addWidget(self.advanced_box)
        column.addStretch(1)

        self._scroll.setWidget(centre)
        return self._scroll

    def _build_footer(self, can_delete: bool) -> QWidget:
        footer = QWidget(self._panel)
        column = QVBoxLayout(footer)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        # Pinned with the buttons, never inside the scroll: the reason Save is
        # refused has to be visible at the moment the user reaches for Save.
        self.problem_label = QLabel("", footer)
        self.problem_label.setObjectName("ruleEditorProblem")
        self.problem_label.setWordWrap(True)
        self.problem_label.setVisible(False)
        column.addWidget(self.problem_label)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(10)
        self.delete_button: LiquidButton | None = None
        if can_delete:
            self.delete_button = LiquidButton(self._labels.get("delete", ""), "danger", footer)
            self.delete_button.setFixedHeight(42)
            self.delete_button.setMinimumWidth(120)
            self.delete_button.clicked.connect(self.delete_requested.emit)
            buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        self.cancel_button = LiquidButton(self._labels.get("cancel", ""), "ghost", footer)
        self.cancel_button.setFixedHeight(42)
        self.cancel_button.setMinimumWidth(120)
        self.cancel_button.clicked.connect(self.close_overlay)
        self.save_button = LiquidButton(self._labels.get("save", ""), "accent", footer)
        self.save_button.setFixedHeight(42)
        self.save_button.setMinimumWidth(140)
        self.save_button.clicked.connect(self._accept)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        column.addLayout(buttons)
        return footer

    def _combo(self) -> StaticPopupComboBox:
        combo = StaticPopupComboBox(lambda: theme_manager.palette, lambda: theme_manager.is_dark)
        # Fixed, not minimum: the app's combo style asks for more height than a line
        # edit, and a column of fields where every other row is a different height
        # reads as an accident.
        combo.setFixedHeight(FIELD_H)
        return combo

    def _row(
        self, key: str, label: str, control: QWidget, *, stretch: bool = True, track: bool = True
    ) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        caption = QLabel(label, row)
        caption.setObjectName("ruleEditorLabel")
        caption.setFixedWidth(LABEL_W)
        caption.setWordWrap(True)
        # The label is a separate widget, so on its own the control would announce
        # only its value. Buddy plus an accessible name carry the field's meaning.
        caption.setBuddy(control)
        if not control.accessibleName():
            control.setAccessibleName(label)
        layout.addWidget(caption, 0, Qt.AlignVCenter)
        layout.addWidget(control, 1 if stretch else 0, Qt.AlignVCenter)
        if not stretch:
            layout.addStretch(1)
        if track:
            self._rows[key] = row
        return row

    # ── state ─────────────────────────────────────────────────────────
    def _load(self, form: dict[str, Any]) -> None:
        """Put the form into the controls once, without answering our own changes."""
        self._loading = True
        try:
            self.name_input.setText(str(form.get("name", "")))
            self._select(self.trigger_combo, form.get("trigger_kind"))
            time_value = QTime.fromString(str(form.get("time_at", "")), "HH:mm")
            self.time_button.setTime(time_value if time_value.isValid() else QTime(21, 0))
            days = {int(day) for day in form.get("days") or ()}
            for index, chip in enumerate(self.day_buttons):
                chip.setChecked(index in days)
            self.app_input.setText(str(form.get("app", "")))
            self._fill_idle(int(form.get("minutes", 10) or 10))
            self._select(self.action_combo, form.get("action"))
            self._select(self.scene_combo, str(form.get("scene_id", "")))
            self.background_button.setChecked(form.get("execution") == EXECUTION_BACKGROUND)
            self._fill_priority(int(form.get("priority", 0) or 0))
            self._fill_cooldown(int(form.get("cooldown_seconds", 0) or 0))
        finally:
            self._loading = False
        self._on_changed()

    def _fill_idle(self, current: int) -> None:
        self.idle_combo.clear()
        for minutes in idle_options(current):
            self.idle_combo.addItem(
                self._labels.get("idle_minutes", "{minutes}").format(minutes=minutes), minutes
            )
        self._select(self.idle_combo, current)

    def _fill_priority(self, current: int) -> None:
        self.priority_combo.clear()
        for value, key, args in priority_options(current):
            self.priority_combo.addItem(self._labels.get(key, str(value)).format(**args), value)
        self._select(self.priority_combo, current)

    def _fill_cooldown(self, current: int) -> None:
        self.cooldown_combo.clear()
        for value, key, args in cooldown_options(current):
            self.cooldown_combo.addItem(self._labels.get(key, str(value)).format(**args), value)
        self._select(self.cooldown_combo, current)

    @staticmethod
    def _select(combo: StaticPopupComboBox, value: Any) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def form(self) -> dict[str, Any]:
        """What the controls now say, on top of what the rule already carried.

        ``origin``, ``origin_ref``, ``enabled`` and ``require_name`` are not in the
        form because nothing here edits them — they come through untouched, which is
        what keeps a migrated rule recognisable as one after an edit.
        """
        collected = dict(self._form)
        collected.update(
            {
                "name": self.name_input.text().strip(),
                "trigger_kind": self.trigger_combo.currentData(),
                "time_at": self.time_button.time().toString("HH:mm"),
                "days": tuple(
                    index for index, chip in enumerate(self.day_buttons) if chip.isChecked()
                ),
                "app": self.app_input.text().strip(),
                "minutes": int(self.idle_combo.currentData() or 10),
                "action": self.action_combo.currentData(),
                "scene_id": str(self.scene_combo.currentData() or ""),
                "execution": (
                    EXECUTION_BACKGROUND
                    if self.background_button.isChecked()
                    else EXECUTION_RUNTIME
                ),
                "priority": int(self.priority_combo.currentData() or 0),
                "cooldown_seconds": int(self.cooldown_combo.currentData() or 0),
            }
        )
        return normalized(collected)

    def problems(self) -> list[str]:
        problems = form_problems(self.form(), scene_ids=self._scene_ids)
        if self._missing_scene and PROBLEM_SCENE in problems:
            # The combo has no item for a scene that no longer exists, so by the time
            # the form is collected the vanished id is gone and what is left looks
            # like "you have not picked one". It is not the same thing: one is a field
            # the user has not filled in, the other is a rule that stopped working
            # when they deleted a scene, and only the second explains itself.
            problems[problems.index(PROBLEM_SCENE)] = PROBLEM_SCENE_MISSING
        return problems

    def _on_changed(self, *_args: object) -> None:
        if getattr(self, "_loading", False):
            return
        if self.scene_combo.currentData():
            # They have chosen one; the old rule's missing scene is no longer the
            # thing standing in the way.
            self._missing_scene = ""
        self._sync_fields()
        self._sync_problems()

    def _sync_fields(self) -> None:
        """Show only what the current choices use, and only offer what is possible."""
        form = self.form()
        wanted = set(TRIGGER_FIELDS.get(form["trigger_kind"], ()))
        for key in ("time_at", "days", "app", "minutes"):
            row = self._rows.get(key)
            if row is not None:
                row.setVisible(key in wanted)
        scene_row = self._rows.get("scene_id")
        if scene_row is not None:
            scene_row.setVisible(form["action"] == CHOICE_SCENE)

        allowed = background_allowed(form)
        self.background_button.setEnabled(allowed)
        if not allowed and self.background_button.isChecked():
            # The capability went away with the action; the flag goes with it rather
            # than being stored for the schema to drop on the next read.
            self.background_button.setChecked(False)
        on = self.background_button.isChecked()
        self.background_button.setText(self._labels.get("on" if on else "off", ""))
        self.background_button.set_role("accent_soft" if on else "ghost")
        self.background_hint.setVisible(not allowed)

    def _sync_problems(self) -> None:
        problems = self.problems()
        first = problems[0] if problems else ""
        self.problem_label.setText(self._labels.get(f"problem_{first}", "") if first else "")
        self.problem_label.setVisible(bool(first))
        # Disabled *and* explained: the label above it says which field, so the
        # button is never a dead end.
        self.save_button.setEnabled(not problems)

    def _toggle_advanced(self) -> None:
        opening = self.advanced_button.isChecked()
        self.advanced_box.setVisible(opening)
        self.advanced_button.set_role("accent_soft" if opening else "ghost")
        if opening:
            QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(self.advanced_box, 0, 20))

    def show_problem(self, text: str) -> None:
        """Report something only the owner could know — a write that did not land.

        Kept separate from the form's own problems, and cleared by the next change,
        because it is about an attempt rather than about a field.
        """
        self.problem_label.setText(str(text))
        self.problem_label.setVisible(bool(text))

    def _accept(self) -> None:
        if self.problems():
            return  # the button is disabled; this covers Enter and a direct call
        # Not closed here: saving is a transaction that can fail, and an editor that
        # has already gone cannot say so or let the user try again. The owner closes
        # it once the rule is actually stored.
        self.saved.emit(self.form())

    # ── window plumbing ───────────────────────────────────────────────
    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self._fit_to_parent()
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        # A new rule opens on its name, which is the one field it cannot be saved
        # without; an existing one opens with the overlay focused so Esc works.
        if self._form.get("require_name"):
            self.name_input.setFocus(Qt.PopupFocusReason)
        QTimer.singleShot(0, self._start_open_animation)

    def _fit_to_parent(self) -> None:
        parent = self.parentWidget()
        available = PANEL_MAX_H if parent is None else max(PANEL_MIN_H, parent.height() - 24)
        height = min(PANEL_MAX_H, available)
        self._panel.setMinimumHeight(height)
        self._panel.setMaximumHeight(height)

    def _start_open_animation(self) -> None:
        self.layout().activate()
        end_pos = self._panel.pos()
        self._panel.move(end_pos + QPoint(0, 12))
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

    def close_overlay(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()
        self.closed.emit()
        self.deleteLater()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 44 if theme_manager.is_dark else 26))
        painter.drawRect(self.rect())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close_overlay()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in {QEvent.Type.Resize, QEvent.Type.Move}:
            parent = self.parentWidget()
            if parent is not None:
                self.setGeometry(parent.rect())
                self._fit_to_parent()
        return super().eventFilter(watched, event)

    def _apply_style(self) -> None:
        palette = theme_manager.palette
        self.setStyleSheet(
            f"""
            #ruleEditorTitle {{
                color: {palette["text"]};
                font-size: 20px;
                font-weight: 800;
            }}
            #ruleEditorClose {{
                color: {palette["muted"]};
                font-size: 15px;
                font-weight: 700;
                border-radius: 16px;
            }}
            #ruleEditorClose:hover {{
                color: {palette["text"]};
                background: {palette["field"]};
            }}
            #ruleEditorScroll, #ruleEditorScroll > QWidget, #ruleEditorContent {{
                background: transparent;
                border: none;
            }}
            #ruleEditorLabel {{
                color: {palette["text"]};
                font-size: 12px;
                font-weight: 700;
            }}
            #ruleEditorHint {{
                color: {palette["muted"]};
                font-size: 11px;
                font-weight: 600;
            }}
            #ruleEditorProblem {{
                color: #ff8f8f;
                font-size: 12px;
                font-weight: 700;
            }}
            #ruleEditorInput {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 12px;
                color: {palette["text"]};
                padding: 0 12px;
                font-size: 13px;
                font-weight: 600;
                selection-background-color: {palette["list_sel"]};
                selection-color: {palette["text"]};
            }}
            """
        )
