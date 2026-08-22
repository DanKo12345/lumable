from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSignalBlocker,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.theme import qcolor_from_token, theme_manager
from app.widgets.animation_helpers import motion_reduced, play_or_complete
from app.widgets.liquid_button import LiquidButton
from app.widgets.profile_action_overlay import _ProfileActionPanel
from app.widgets.scene_tile_grid import SceneTileData

_INTRO_WIDTH = 620
_INTRO_HEIGHT = 350
_TIP_WIDTH = 390
_TIP_HEIGHT = 214
_SURFACE_MARGIN = 14
_AUTOPLAY_MS = 5600
_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_LUCIDE_DIR = _ASSETS / "icons" / "lucide"
_ICON_PATH = _ASSETS / "icon.png"


class _Dots(QWidget):
    """Compact progress indicator shared by the automatic and manual tour."""

    _SPACING = 16.0

    def __init__(self, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._count = max(1, count)
        self._pos = 0.0
        self.setFixedSize(int((self._count - 1) * self._SPACING + 20), 14)
        self._anim = QPropertyAnimation(self, b"posValue", self)
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def get_pos_value(self) -> float:
        return self._pos

    def set_pos_value(self, value: float) -> None:
        self._pos = float(value)
        self.update()

    posValue = Property(float, get_pos_value, set_pos_value)

    def set_current(self, index: int, *, animate: bool = True) -> None:
        index = max(0, min(self._count - 1, index))
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(float(index))
            play_or_complete(self._anim)
        else:
            self._pos = float(index)
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = theme_manager.palette
        cy = self.height() / 2.0
        total = (self._count - 1) * self._SPACING
        start_x = (self.width() - total) / 2.0

        painter.setPen(Qt.NoPen)
        muted = qcolor_from_token(palette["muted"])
        muted.setAlpha(115)
        painter.setBrush(muted)
        for index in range(self._count):
            painter.drawEllipse(QPointF(start_x + index * self._SPACING, cy), 3.2, 3.2)

        painter.setBrush(qcolor_from_token(palette["accent_start"]))
        active_x = start_x + self._pos * self._SPACING
        painter.drawRoundedRect(QRectF(active_x - 8.0, cy - 3.6, 16.0, 7.2), 3.6, 3.6)


class OnboardingOverlay(QWidget):
    """A first-run welcome followed by a safe, visual tour of the real UI.

    Section changes and scrolling are real so the user learns where things live.
    Device connection and colour movement are deliberately demonstrations only:
    sliders are changed under ``QSignalBlocker``, the preview is restored, and no
    BLE method or persisted setting is touched.
    """

    finished = Signal()
    sectionRequested = Signal(str)

    def __init__(self, labels: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._labels = labels
        self._tour_steps: list[dict[str, Any]] = list(labels.get("tour_steps", []))
        self._tour_index = -1
        self._touring = False
        self._autoplay = True
        self._target: QWidget | None = None
        self._targets: list[QWidget] = []
        self._watched_targets: list[QWidget] = []
        self._watched_geometry_widgets: list[QWidget] = []
        self._spotlight_rect = QRectF()
        self._spotlight_alpha = 1.0
        self._icon_cache: dict[str, QPixmap] = {}
        self._fade_anim: QPropertyAnimation | None = None
        self._panel_anim: QPropertyAnimation | None = None
        self._spot_anim = QPropertyAnimation(self, b"spotlightAlpha", self)
        self._spot_anim.setDuration(280)
        self._spot_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._spot_anim.finished.connect(self.update)
        self._scroll_anim: QPropertyAnimation | None = None
        self._follow_bar = None
        self._tracking_scroll = False
        self._demo_anim: QVariantAnimation | None = None
        self._retired_demo_anims: list[QVariantAnimation] = []
        self._demo_saved: dict[str, Any] = {}
        self._initial_section = self._current_section_key()
        self._initial_scroll = self._body_scroll_value()
        self._autoplay_timer = QTimer(self)
        self._autoplay_timer.setSingleShot(True)
        self._autoplay_timer.timeout.connect(self._auto_next)
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(60)
        self._geometry_timer.timeout.connect(self._realign_after_resize)
        self._geometry_retries = 0
        self._geometry_animate_scroll = False
        if parent is not None:
            self.setGeometry(parent.rect())
        self._apply_style()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._build_ui()

    # ── build ─────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        self._panel = _ProfileActionPanel(self, height=1)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(36, 22, 36, 24)
        panel_layout.setSpacing(10)

        self._intro_icon = QLabel(self._panel)
        self._intro_icon.setObjectName("onboardIcon")
        self._intro_icon.setFixedSize(68, 68)
        self._intro_icon.setAlignment(Qt.AlignCenter)
        self._intro_icon.setPixmap(self._icon_pixmap("app"))
        panel_layout.addWidget(self._intro_icon, 0, Qt.AlignHCenter)

        self._intro_title = QLabel(self._labels.get("welcome_title", "LumaBLE"), self._panel)
        self._intro_title.setObjectName("onboardTitle")
        self._intro_title.setAlignment(Qt.AlignCenter)
        self._intro_title.setWordWrap(True)
        panel_layout.addWidget(self._intro_title)

        self._intro_body = QLabel(self._labels.get("welcome_body", ""), self._panel)
        self._intro_body.setObjectName("onboardBody")
        self._intro_body.setAlignment(Qt.AlignCenter)
        self._intro_body.setWordWrap(True)
        panel_layout.addWidget(self._intro_body)

        self._intro_note = QLabel(self._labels.get("welcome_note", ""), self._panel)
        self._intro_note.setObjectName("onboardNote")
        self._intro_note.setAlignment(Qt.AlignCenter)
        self._intro_note.setWordWrap(True)
        panel_layout.addWidget(self._intro_note)
        panel_layout.addStretch(1)

        intro_actions = QHBoxLayout()
        intro_actions.setSpacing(14)
        self._later_button = LiquidButton(self._labels["skip"], "ghost", self._panel)
        self._later_button.setMinimumHeight(44)
        self._later_button.clicked.connect(self._finish)
        self._tour_button = LiquidButton(self._labels["tour"], "accent", self._panel)
        self._tour_button.setMinimumHeight(44)
        self._tour_button.clicked.connect(self._begin_tour)
        intro_actions.addWidget(self._later_button, 1)
        intro_actions.addWidget(self._tour_button, 2)
        panel_layout.addLayout(intro_actions)

        # Floating coach panel. It is not nested in the welcome panel: once the
        # tour starts the real app needs to remain visible around it.
        self._tip = _ProfileActionPanel(self, height=1)
        self._tip.hide()
        tip_layout = QVBoxLayout(self._tip)
        tip_layout.setContentsMargins(20, 16, 20, 16)
        tip_layout.setSpacing(7)

        tip_header = QHBoxLayout()
        self._tip_icon = QLabel(self._tip)
        self._tip_icon.setFixedSize(42, 42)
        self._tip_icon.setAlignment(Qt.AlignCenter)
        self._tip_title = QLabel("", self._tip)
        self._tip_title.setObjectName("onboardTourTitle")
        self._tip_title.setWordWrap(True)
        self._tip_skip = LiquidButton(self._labels["skip"], "ghost", self._tip)
        self._tip_skip.setFixedSize(92, 32)
        self._tip_skip.clicked.connect(self._finish)
        tip_header.addWidget(self._tip_icon)
        tip_header.addWidget(self._tip_title, 1)
        tip_header.addWidget(self._tip_skip)
        tip_layout.addLayout(tip_header)

        self._tip_body = QLabel("", self._tip)
        self._tip_body.setObjectName("onboardTourBody")
        self._tip_body.setWordWrap(True)
        self._tip_body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        tip_layout.addWidget(self._tip_body)

        self._demo_status = QLabel("", self._tip)
        self._demo_status.setObjectName("onboardDemoStatus")
        self._demo_status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._demo_status.hide()
        tip_layout.addWidget(self._demo_status)
        tip_layout.addStretch(1)

        tip_footer = QHBoxLayout()
        tip_footer.setSpacing(10)
        self._tip_back = LiquidButton(self._labels["back"], "ghost", self._tip)
        self._tip_back.setFixedSize(96, 36)
        self._tip_back.clicked.connect(self._manual_prev)
        self._dots = _Dots(len(self._tour_steps), self._tip)
        self._tip_next = LiquidButton(self._labels["next"], "accent", self._tip)
        self._tip_next.setFixedSize(118, 36)
        self._tip_next.clicked.connect(self._manual_next)
        tip_footer.addWidget(self._tip_back)
        tip_footer.addStretch(1)
        tip_footer.addWidget(self._dots)
        tip_footer.addSpacing(10)
        tip_footer.addWidget(self._tip_next)
        tip_layout.addLayout(tip_footer)

        self._resize_surfaces()

    # ── tour navigation ───────────────────────────────────────────────
    def _begin_tour(self) -> None:
        if not self._tour_steps:
            self._finish()
            return
        self._touring = True
        self._autoplay = True
        self._panel.hide()
        self._tip.show()
        self._go_tour_step(0)

    def _next(self) -> None:
        """Compatibility entry used by keyboard and motion tests."""
        if not self._touring:
            self._begin_tour()
            return
        self._manual_next()

    def _prev(self) -> None:
        if self._touring:
            self._manual_prev()

    def _manual_next(self) -> None:
        self._autoplay = False
        self._autoplay_timer.stop()
        if self._tour_index >= len(self._tour_steps) - 1:
            self._finish()
            return
        self._go_tour_step(self._tour_index + 1)

    def _manual_prev(self) -> None:
        self._autoplay = False
        self._autoplay_timer.stop()
        if self._tour_index <= 0:
            return
        self._go_tour_step(self._tour_index - 1)

    def _auto_next(self) -> None:
        if not self._touring or not self._autoplay:
            return
        if self._tour_index < len(self._tour_steps) - 1:
            self._go_tour_step(self._tour_index + 1)

    def _go_tour_step(self, index: int) -> None:
        if not 0 <= index < len(self._tour_steps):
            return
        if self._scroll_anim is not None:
            self._scroll_anim.stop()
        self._tracking_scroll = False
        self._restore_demo()
        self._autoplay_timer.stop()
        self._tour_index = index
        step = self._tour_steps[index]
        self._tip_icon.setPixmap(self._icon_pixmap(str(step.get("icon", ""))).scaled(
            42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))
        self._tip_title.setText(str(step.get("title", "")))
        self._tip_body.setText(str(step.get("body", "")))
        self._tip_next.setText(
            self._labels["finish"] if index == len(self._tour_steps) - 1 else self._labels["next"]
        )
        self._tip_back.setEnabled(index > 0)
        self._dots.set_current(index, animate=not motion_reduced())
        self.setAccessibleName(str(step.get("title", "")))
        self._demo_status.hide()
        self._demo_status.clear()
        self.sectionRequested.emit(str(step.get("section", "color")))
        QTimer.singleShot(0, self, self._settle_tour_step)

    def _settle_tour_step(self) -> None:
        if not self._touring or not 0 <= self._tour_index < len(self._tour_steps):
            return
        step = self._tour_steps[self._tour_index]
        parent = self.parentWidget()
        names = step.get("targets") or [step.get("target", "")]
        for old_target in self._watched_targets:
            try:
                old_target.removeEventFilter(self)
            except RuntimeError:
                pass
        self._watched_targets = []
        self._targets = []
        if parent is not None:
            for name in names:
                target = getattr(parent, str(name), None)
                if isinstance(target, QWidget):
                    self._targets.append(target)
                    target.installEventFilter(self)
                    self._watched_targets.append(target)
        self._target = self._targets[0] if self._targets else None
        self.set_spotlight_rect(QRectF())
        if motion_reduced():
            self._scroll_target_into_view(animate=False)
        else:
            # Section selection can finish its layout a turn after the signal,
            # especially when the window is already maximised. Measure only
            # after that burst instead of freezing an intermediate rectangle.
            self._geometry_retries = 4
            self._geometry_animate_scroll = True
            self._geometry_timer.start()

    # ── spotlight + scroll ────────────────────────────────────────────
    def get_spotlight_rect(self) -> QRectF:
        return QRectF(self._spotlight_rect)

    def set_spotlight_rect(self, rect: QRectF) -> None:
        self._spotlight_rect = QRectF(rect)
        if not self._tracking_scroll:
            self._position_tip()
        self.update()

    spotlightRect = Property(QRectF, get_spotlight_rect, set_spotlight_rect)

    def get_spotlight_alpha(self) -> float:
        return self._spotlight_alpha

    def set_spotlight_alpha(self, value: float) -> None:
        self._spotlight_alpha = max(0.0, min(1.0, float(value)))
        self.update()

    spotlightAlpha = Property(float, get_spotlight_alpha, set_spotlight_alpha)

    def _target_is_in_body_scroll(self, scroll: Any, target: QWidget) -> bool:
        body = scroll.widget() if scroll is not None else None
        return body is not None and (target is body or body.isAncestorOf(target))

    def _visible_targets(self) -> list[QWidget]:
        return [target for target in self._targets if target.isVisible()]

    def _raw_target_rect(self) -> QRectF:
        rect = QRectF()
        for target in self._visible_targets():
            top_left = self.mapFromGlobal(target.mapToGlobal(QPoint(0, 0)))
            target_rect = QRectF(top_left.x(), top_left.y(), target.width(), target.height())
            rect = target_rect if rect.isEmpty() else rect.united(target_rect)
        return rect

    def _target_rect(self) -> QRectF:
        targets = self._visible_targets()
        if not targets:
            return QRectF()
        # The target and this overlay live in different widget branches. Mapping
        # directly between them loses offsets introduced by QScrollArea and the
        # centred content wrapper on some Qt/Windows layouts. Global coordinates
        # are the one stable bridge between those branches.
        rect = self._raw_target_rect()
        parent = self.parentWidget()
        scroll = getattr(parent, "body_scroll", None) if parent is not None else None
        if (
            scroll is not None
            and scroll.isVisible()
            and all(self._target_is_in_body_scroll(scroll, target) for target in targets)
        ):
            view_top = self.mapFromGlobal(scroll.viewport().mapToGlobal(QPoint(0, 0)))
            viewport = QRectF(view_top.x(), view_top.y(), scroll.viewport().width(), scroll.viewport().height())
            if rect.width() > viewport.width() or rect.height() > viewport.height():
                # A card taller than the viewport cannot have its real far edge
                # shown. Frame the visible work area as one honest closed region
                # instead of clipping the card into an open or invented border.
                rect = viewport.adjusted(10, 10, -10, -10)
            elif not viewport.contains(rect):
                # The card fits but is still travelling during guided scrolling.
                # Showing a viewport-sized substitute here is the oversized frame
                # that could remain after opening the guide maximised.
                return QRectF()
        return rect.intersected(QRectF(self.rect()).adjusted(6, 6, -6, -6))

    def _animate_spotlight(self, target: QRectF) -> None:
        self._spot_anim.stop()
        # The focus geometry is truthful from the first painted frame. Animating
        # the rectangle itself briefly highlighted unrelated rows and cropped the
        # control the step was explaining; only the outline now fades in.
        self.set_spotlight_rect(target)
        if target.isEmpty() or motion_reduced():
            self.set_spotlight_alpha(1.0)
            return
        self.set_spotlight_alpha(0.0)
        self._spot_anim.setStartValue(0.0)
        self._spot_anim.setEndValue(1.0)
        play_or_complete(self._spot_anim)

    def _sync_spotlight_to_target(self, _value: int | None = None) -> None:
        if self._touring:
            self.set_spotlight_rect(self._target_rect())

    def _reveal_tour_step(self) -> None:
        if not self._touring or not 0 <= self._tour_index < len(self._tour_steps):
            return
        self._tracking_scroll = False
        self._animate_spotlight(self._target_rect())
        self._position_tip()
        step = self._tour_steps[self._tour_index]
        self._start_demo(str(step.get("demo", "")))
        if self._autoplay and self._tour_index < len(self._tour_steps) - 1:
            index = self._tour_index
            if self._demo_anim is not None and self._demo_anim.state() == QAbstractAnimation.Running:
                self._demo_anim.finished.connect(lambda: self._arm_autoplay(index))
            else:
                self._arm_autoplay(index)

    def _arm_autoplay(self, index: int) -> None:
        if self._touring and self._autoplay and self._tour_index == index:
            self._autoplay_timer.start(_AUTOPLAY_MS)

    def _scroll_target_into_view(self, *, animate: bool = True) -> None:
        parent = self.parentWidget()
        scroll = getattr(parent, "body_scroll", None) if parent is not None else None
        targets = self._visible_targets()
        if (
            scroll is None
            or not targets
            or scroll.widget() is None
            or not all(self._target_is_in_body_scroll(scroll, target) for target in targets)
        ):
            self._reveal_tour_step()
            return

        bar = scroll.verticalScrollBar()
        raw = self._raw_target_rect()
        viewport_top = self.mapFromGlobal(scroll.viewport().mapToGlobal(QPoint(0, 0))).y()
        content_top = bar.value() + raw.top() - viewport_top
        wanted = content_top - max(18, (scroll.viewport().height() - raw.height()) // 2)
        wanted = max(bar.minimum(), min(bar.maximum(), wanted))
        if self._follow_bar is not bar:
            if self._follow_bar is not None:
                self._follow_bar.valueChanged.disconnect(self._sync_spotlight_to_target)
            bar.valueChanged.connect(self._sync_spotlight_to_target)
            self._follow_bar = bar
        if not animate or motion_reduced() or wanted == bar.value():
            bar.setValue(wanted)
            self._reveal_tour_step()
            return
        self._tracking_scroll = True
        self.set_spotlight_rect(QRectF())
        self._scroll_anim = QPropertyAnimation(bar, b"value", self)
        self._scroll_anim.setDuration(620)
        self._scroll_anim.setStartValue(bar.value())
        self._scroll_anim.setEndValue(wanted)
        self._scroll_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._scroll_anim.finished.connect(self._reveal_tour_step)
        play_or_complete(self._scroll_anim)

    def _realign_after_resize(self) -> None:
        if not self._touring:
            return
        if self._scroll_anim is not None:
            self._scroll_anim.stop()
        self._tracking_scroll = False
        animate_scroll = self._geometry_animate_scroll
        self._geometry_animate_scroll = False
        self._scroll_target_into_view(animate=animate_scroll)
        scroll_running = (
            self._scroll_anim is not None
            and self._scroll_anim.state() == QAbstractAnimation.Running
        )
        if self._spotlight_rect.isEmpty() and not scroll_running and self._geometry_retries > 0:
            # During a maximise/restore burst Qt can briefly hide the page while
            # rebuilding its layout. Try again once that transient state passes.
            self._geometry_retries -= 1
            self._geometry_timer.start()

    def _position_tip(self) -> None:
        if not self._touring or not self._tip.isVisible():
            return
        margin = _SURFACE_MARGIN
        bounds = QRectF(margin, margin, max(0, self.width() - margin * 2), max(0, self.height() - margin * 2))
        # Keep the controls in one place throughout the tour. Moving the coach
        # to whichever corner overlaps least made the pointer chase Next up and
        # down the window after every step.
        self._tip.move(round(bounds.left()), round(bounds.top()))

    # ── visual-only demonstrations ───────────────────────────────────
    def _start_demo(self, kind: str) -> None:
        if self._demo_saved.get("kind") == kind:
            return
        if kind == "color":
            self._start_color_demo()
        elif kind == "scene":
            self._start_scene_demo()
        elif kind == "sync":
            self._start_sync_demo()
        elif kind == "rule":
            self._start_rule_demo()
        elif kind == "connected":
            self._start_connection_demo()

    def _start_color_demo(self) -> None:
        parent = self.parentWidget()
        names = ("red_slider", "green_slider", "blue_slider", "brightness_slider")
        if parent is None or any(getattr(parent, name, None) is None for name in names):
            return
        sliders = [getattr(parent, name) for name in names]
        values = [getattr(parent, name.replace("slider", "value"), None) for name in names]
        preview = getattr(parent, "preview", None)
        self._demo_saved = {
            "kind": "color",
            "sliders": sliders,
            "values": [slider.value() for slider in sliders],
            "display_values": [float(getattr(slider, "_display_value", slider.value())) for slider in sliders],
            "labels": [value.text() if value is not None else "" for value in values],
            "value_widgets": values,
            "preview": preview,
            "preview_color": QColor(getattr(preview, "_color", QColor(88, 182, 255))),
            "preview_brightness": int(getattr(preview, "_brightness", 100)),
        }
        self._demo_anim = QVariantAnimation(self)
        self._demo_anim.setStartValue(0.0)
        self._demo_anim.setEndValue(1.0)
        self._demo_anim.setDuration(2600)
        self._demo_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._demo_anim.valueChanged.connect(self._apply_color_demo)
        if motion_reduced():
            self._apply_color_demo(1.0)
        else:
            play_or_complete(self._demo_anim)

    def _apply_color_demo(self, progress: Any) -> None:
        if self._demo_saved.get("kind") != "color":
            return
        amount = float(progress)
        starts = self._demo_saved["values"]
        # Pass through a contrasting cool colour before settling on the final
        # magenta. A single interpolation was almost invisible whenever the
        # user's current colour happened to be close to the destination.
        middle = (72, 188, 238, 84)
        targets = (218, 86, 196, 72)
        if amount < 0.5:
            local = amount * 2.0
            segment_start = starts
            segment_end = middle
        else:
            local = (amount - 0.5) * 2.0
            segment_start = middle
            segment_end = targets
        current = [
            round(start + (target - start) * local)
            for start, target in zip(segment_start, segment_end, strict=True)
        ]
        for slider, value in zip(self._demo_saved["sliders"], current, strict=True):
            blocker = QSignalBlocker(slider)
            slider.setValue(value)
            del blocker
            set_display = getattr(slider, "set_display_value", None)
            if callable(set_display):
                set_display(float(value))
        for widget, text in zip(
            self._demo_saved["value_widgets"],
            (str(current[0]), str(current[1]), str(current[2]), f"{current[3]}%"),
            strict=True,
        ):
            if widget is not None:
                widget.setText(text)
        preview = self._demo_saved.get("preview")
        if preview is not None:
            preview.set_color(QColor(*current[:3]))
            preview.set_brightness(current[3])

    def _start_scene_demo(self) -> None:
        parent = self.parentWidget()
        grid = getattr(parent, "scenes_grid", None) if parent is not None else None
        empty = getattr(parent, "scenes_empty_state", None) if parent is not None else None
        if grid is None or empty is None:
            return
        entries = [tile.data for tile in grid.tiles()]
        active_id = next((tile.scene_id for tile in grid.tiles() if tile.is_active()), "")
        self._demo_saved = {
            "kind": "scene",
            "grid": grid,
            "entries": entries,
            "active_id": active_id,
            "grid_visible": grid.isVisible(),
            "grid_minimum_height": grid.minimumHeight(),
            "grid_maximum_height": grid.maximumHeight(),
            "empty": empty,
            "empty_visible": empty.isVisible(),
            "empty_minimum_height": empty.minimumHeight(),
            "empty_maximum_height": empty.maximumHeight(),
        }
        grid.set_scenes(
            [
                *entries,
                SceneTileData(
                    scene_id="__onboarding_demo_scene__",
                    name=str(self._labels.get("demo_scene_title", "")),
                    color="#c878ff",
                    target_label=str(self._labels.get("demo_scene_target", "")),
                ),
            ],
            active_id="__onboarding_demo_scene__",
        )
        grid.show()
        tile = grid.tiles()[-1]
        tile.ensurePolished()
        expanded = max(56, tile.sizeHint().height())
        tile_effect = QGraphicsOpacityEffect(tile)
        tile_effect.setOpacity(0.0)
        tile.setGraphicsEffect(tile_effect)
        grid.ensurePolished()
        grid.layout().activate()
        grid_height = max(expanded, grid.sizeHint().height())
        if not entries:
            grid.setMinimumHeight(0)
            grid.setMaximumHeight(0)
        self._demo_saved.update(
            {
                "tile": tile,
                "tile_effect": tile_effect,
                "expanded_height": expanded,
                "grid_height": grid_height,
                "animate_grid_height": not entries,
            }
        )
        if empty.isVisible():
            empty.ensurePolished()
            empty_height = max(1, empty.sizeHint().height())
            empty_effect = QGraphicsOpacityEffect(empty)
            empty_effect.setOpacity(1.0)
            empty.setGraphicsEffect(empty_effect)
            self._demo_saved["empty_height"] = empty_height
            self._demo_saved["empty_effect"] = empty_effect
        self._demo_anim = QVariantAnimation(self)
        self._demo_anim.setStartValue(0.0)
        self._demo_anim.setEndValue(1.0)
        self._demo_anim.setDuration(1600)
        self._demo_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._demo_anim.valueChanged.connect(self._apply_scene_demo)
        self._apply_scene_demo(1.0 if motion_reduced() else 0.0)
        QTimer.singleShot(0, self, self._refresh_scene_demo_geometry)
        if not motion_reduced():
            play_or_complete(self._demo_anim)

    def _refresh_scene_demo_geometry(self) -> None:
        if self._touring and self._demo_saved.get("kind") == "scene":
            self._scroll_target_into_view()

    def _apply_scene_demo(self, progress: Any) -> None:
        if self._demo_saved.get("kind") != "scene":
            return
        amount = max(0.0, min(1.0, float(progress)))
        self._demo_saved["tile_effect"].setOpacity(amount)
        if self._demo_saved["animate_grid_height"]:
            self._demo_saved["grid"].setMaximumHeight(
                round(self._demo_saved["grid_height"] * amount)
            )
        empty = self._demo_saved["empty"]
        empty_effect = self._demo_saved.get("empty_effect")
        if empty_effect is not None:
            empty.setMaximumHeight(round(self._demo_saved["empty_height"] * (1.0 - amount)))
            empty_effect.setOpacity(1.0 - amount)
            if amount >= 1.0:
                empty.hide()
        if self._target is not None:
            self._sync_spotlight_to_target()

    def _start_sync_demo(self) -> None:
        parent = self.parentWidget()
        preview = getattr(parent, "ambient_preview", None) if parent is not None else None
        status = getattr(parent, "ambient_status_label", None) if parent is not None else None
        profile = getattr(parent, "ambient_profile_segment", None) if parent is not None else None
        sliders = [
            getattr(parent, "ambient_saturation_slider", None),
            getattr(parent, "ambient_smoothing_slider", None),
        ]
        values = [
            getattr(parent, "ambient_saturation_value", None),
            getattr(parent, "ambient_smoothing_value", None),
        ]
        description = getattr(parent, "ambient_profile_description", None) if parent is not None else None
        if preview is None or profile is None or any(slider is None for slider in sliders):
            return
        current_profile = profile.current_key()
        target_profile = "movie" if current_profile != "movie" else "game"
        starts = [slider.value() for slider in sliders]
        targets = [88 if starts[0] < 70 else 42, 35 if starts[1] > 50 else 82]
        self._demo_saved = {
            "kind": "sync",
            "preview": preview,
            "raw": getattr(preview, "_raw", None),
            "color": getattr(preview, "_color", None),
            "status": status,
            "status_text": status.text() if status is not None else "",
            "status_visible": status.isVisible() if status is not None else False,
            "profile": profile,
            "profile_key": current_profile,
            "profile_target": target_profile,
            "profile_changed": False,
            "profile_description": description,
            "profile_description_text": description.text() if description is not None else "",
            "sliders": sliders,
            "slider_values": starts,
            "slider_display_values": [
                float(getattr(slider, "_display_value", slider.value())) for slider in sliders
            ],
            "slider_targets": targets,
            "value_widgets": values,
            "value_texts": [value.text() if value is not None else "" for value in values],
        }
        if status is not None:
            status.setText(str(self._labels.get("demo_sync", "")))
            status.show()
        self._demo_anim = QVariantAnimation(self)
        self._demo_anim.setStartValue(0.0)
        self._demo_anim.setEndValue(1.0)
        self._demo_anim.setDuration(3000)
        self._demo_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._demo_anim.valueChanged.connect(self._apply_sync_demo)
        self._apply_sync_demo(1.0 if motion_reduced() else 0.0)
        if not motion_reduced():
            play_or_complete(self._demo_anim)

    def _apply_sync_demo(self, progress: Any) -> None:
        if self._demo_saved.get("kind") != "sync":
            return
        amount = float(progress)
        if amount >= 0.22 and not self._demo_saved["profile_changed"]:
            profile = self._demo_saved["profile"]
            profile.set_current(self._demo_saved["profile_target"], animate=not motion_reduced())
            self._demo_saved["profile_changed"] = True
            description = self._demo_saved.get("profile_description")
            descriptions = self._labels.get("demo_profile_descriptions", {})
            if description is not None and isinstance(descriptions, dict):
                description.setText(str(descriptions.get(self._demo_saved["profile_target"], "")))
        current = [
            round(start + (target - start) * amount)
            for start, target in zip(
                self._demo_saved["slider_values"],
                self._demo_saved["slider_targets"],
                strict=True,
            )
        ]
        for slider, value in zip(self._demo_saved["sliders"], current, strict=True):
            blocker = QSignalBlocker(slider)
            slider.setValue(value)
            del blocker
            set_display = getattr(slider, "set_display_value", None)
            if callable(set_display):
                set_display(float(value))
        for widget, value in zip(self._demo_saved["value_widgets"], current, strict=True):
            if widget is not None:
                widget.setText(f"{value}%")
        stops = ((46, 126, 255), (188, 70, 255), (255, 126, 56))
        segment = min(1, int(amount * 2.0))
        local = amount * 2.0 - segment
        start = stops[segment]
        end = stops[segment + 1]
        raw = tuple(round(a + (b - a) * local) for a, b in zip(start, end, strict=True))
        final = tuple(max(0, min(255, round(channel * 0.82 + 24))) for channel in raw)
        self._demo_saved["preview"].set_colors(raw, final)

    def _start_rule_demo(self) -> None:
        parent = self.parentWidget()
        hint = getattr(parent, "automations_empty_hint", None) if parent is not None else None
        if hint is None:
            return
        self._demo_saved = {
            "kind": "rule",
            "hint": hint,
            "text": hint.text(),
            "style": hint.styleSheet(),
            "visible": hint.isVisible(),
            "minimum_height": hint.minimumHeight(),
            "maximum_height": hint.maximumHeight(),
        }
        self._set_rule_demo_content(1.0)
        hint.ensurePolished()
        self._demo_saved["expanded_height"] = max(64, hint.sizeHint().height())
        effect = QGraphicsOpacityEffect(hint)
        effect.setOpacity(0.0)
        hint.setGraphicsEffect(effect)
        self._demo_saved["opacity_effect"] = effect
        hint.setMinimumHeight(0)
        hint.setMaximumHeight(0)
        hint.show()
        self._demo_anim = QVariantAnimation(self)
        self._demo_anim.setStartValue(0.0)
        self._demo_anim.setEndValue(1.0)
        self._demo_anim.setDuration(1600)
        self._demo_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._demo_anim.valueChanged.connect(self._apply_rule_demo)
        self._apply_rule_demo(1.0 if motion_reduced() else 0.0)
        QTimer.singleShot(0, self, self._refresh_rule_demo_geometry)
        if not motion_reduced():
            play_or_complete(self._demo_anim)

    def _refresh_rule_demo_geometry(self) -> None:
        if self._touring and self._demo_saved.get("kind") == "rule":
            self._scroll_target_into_view()

    def _apply_rule_demo(self, progress: Any) -> None:
        if self._demo_saved.get("kind") != "rule":
            return
        amount = max(0.0, min(1.0, float(progress)))
        self._set_rule_demo_content(amount)
        hint = self._demo_saved["hint"]
        height = round(float(self._demo_saved["expanded_height"]) * amount)
        hint.setMaximumHeight(height)
        effect = self._demo_saved.get("opacity_effect")
        if effect is not None:
            effect.setOpacity(amount)
        if self._target is not None:
            self._sync_spotlight_to_target()

    def _set_rule_demo_content(self, progress: float) -> None:
        palette = theme_manager.palette
        state = str(self._labels.get("demo_rule_on", ""))
        hint = self._demo_saved["hint"]
        hint.setText(
            f"<b>{self._labels.get('demo_rule_title', '')}</b>"
            f"&nbsp;&nbsp;&nbsp;<span style='color:{palette['accent_start']}'><b>{state}</b></span><br>"
            f"<span style='color:{palette['muted']}'>{self._labels.get('demo_rule_detail', '')}</span>"
        )
        start = QColor(palette["surface_border"])
        end = QColor(palette["accent_start"])
        amount = max(0.0, min(1.0, progress))
        border = QColor(
            round(start.red() + (end.red() - start.red()) * amount),
            round(start.green() + (end.green() - start.green()) * amount),
            round(start.blue() + (end.blue() - start.blue()) * amount),
        ).name()
        hint.setStyleSheet(
            f"color: {palette['text']}; background: {palette['surface_soft']}; "
            f"border: 1px solid {border}; border-radius: 8px; padding: 12px;"
        )

    def _start_connection_demo(self) -> None:
        parent = self.parentWidget()
        dot = getattr(parent, "device_status_dot", None) if parent is not None else None
        status = getattr(parent, "device_status", None) if parent is not None else None
        hint = getattr(parent, "device_status_hint", None) if parent is not None else None
        self._demo_saved = {
            "kind": "connected",
            "dot": dot,
            "dot_style": dot.styleSheet() if dot is not None else "",
            "status": status,
            "status_text": status.text() if status is not None else "",
            "hint": hint,
            "hint_text": hint.text() if hint is not None else "",
            "hint_visible": hint.isVisible() if hint is not None else False,
            "hint_wanted": getattr(parent, "_status_hint_wanted", True) if parent is not None else True,
        }
        self._demo_anim = QVariantAnimation(self)
        self._demo_anim.setStartValue(0.0)
        self._demo_anim.setEndValue(1.0)
        self._demo_anim.setDuration(2400)
        self._demo_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._demo_anim.valueChanged.connect(self._apply_connection_demo)
        if motion_reduced():
            self._apply_connection_demo(1.0)
        else:
            play_or_complete(self._demo_anim)

    def _apply_connection_demo(self, progress: Any) -> None:
        amount = float(progress)
        palette = theme_manager.palette
        if amount < 0.28:
            color = "#707783"
            status_key = "demo_status_disconnected"
        elif amount < 0.62:
            color = "#f5b94a"
            status_key = "demo_status_searching"
        else:
            color = palette["success_start"]
            status_key = "demo_status_connected"
        dot = self._demo_saved.get("dot")
        if dot is not None:
            dot.setStyleSheet(f"background: {color}; border-radius: {max(1, dot.width() // 2)}px;")
        status = self._demo_saved.get("status")
        if status is not None:
            status.setText(str(self._labels.get(status_key, "")))
        hint = self._demo_saved.get("hint")
        if hint is not None:
            hint.setText(str(self._labels.get("demo_strip_name", "")))
            parent = self.parentWidget()
            show_hint = getattr(parent, "_set_status_hint_visible", None) if parent is not None else None
            if callable(show_hint):
                show_hint(True)
            else:
                hint.show()

    def _restore_demo(self) -> None:
        if self._demo_anim is not None:
            self._demo_anim.stop()
            # Keep the stopped wrapper alive until the overlay itself is gone.
            # Deleting it in the same event turn that builds the next Qt demo
            # can crash PySide on Windows while queued valueChanged delivery is
            # still unwinding.
            self._retired_demo_anims.append(self._demo_anim)
            self._demo_anim = None
        restore = getattr(self, f"_restore_{self._demo_saved.get('kind', '')}_demo", None)
        if callable(restore):
            restore()
        self._demo_saved = {}
        self._demo_status.hide()
        self._demo_status.clear()

    def _restore_color_demo(self) -> None:
        for slider, value in zip(self._demo_saved["sliders"], self._demo_saved["values"], strict=True):
            blocker = QSignalBlocker(slider)
            slider.setValue(value)
            del blocker
        for slider, value in zip(
            self._demo_saved["sliders"], self._demo_saved["display_values"], strict=True
        ):
            set_display = getattr(slider, "set_display_value", None)
            if callable(set_display):
                set_display(value)
        for widget, text in zip(
            self._demo_saved["value_widgets"], self._demo_saved["labels"], strict=True
        ):
            if widget is not None:
                widget.setText(text)
        preview = self._demo_saved.get("preview")
        if preview is not None:
            preview.set_color(self._demo_saved["preview_color"])
            preview.set_brightness(self._demo_saved["preview_brightness"])

    def _restore_sync_demo(self) -> None:
        preview = self._demo_saved["preview"]
        raw = self._demo_saved["raw"]
        color = self._demo_saved["color"]
        if color is None:
            preview.clear()
        elif raw is None:
            preview.set_color(*color)
        else:
            preview.set_colors(raw, color)
        status = self._demo_saved.get("status")
        if status is not None:
            status.setText(self._demo_saved["status_text"])
            status.setVisible(self._demo_saved["status_visible"])
        profile = self._demo_saved["profile"]
        profile.set_current(self._demo_saved["profile_key"], animate=False)
        description = self._demo_saved.get("profile_description")
        if description is not None:
            description.setText(self._demo_saved["profile_description_text"])
        for slider, value, display_value in zip(
            self._demo_saved["sliders"],
            self._demo_saved["slider_values"],
            self._demo_saved["slider_display_values"],
            strict=True,
        ):
            blocker = QSignalBlocker(slider)
            slider.setValue(value)
            del blocker
            set_display = getattr(slider, "set_display_value", None)
            if callable(set_display):
                set_display(display_value)
        for widget, text in zip(
            self._demo_saved["value_widgets"], self._demo_saved["value_texts"], strict=True
        ):
            if widget is not None:
                widget.setText(text)

    def _restore_scene_demo(self) -> None:
        grid = self._demo_saved["grid"]
        self._demo_saved["tile"].setGraphicsEffect(None)
        empty = self._demo_saved["empty"]
        if self._demo_saved.get("empty_effect") is not None:
            empty.setGraphicsEffect(None)
        empty.setMinimumHeight(self._demo_saved["empty_minimum_height"])
        empty.setMaximumHeight(self._demo_saved["empty_maximum_height"])
        grid.set_scenes(self._demo_saved["entries"], self._demo_saved["active_id"])
        grid.setMinimumHeight(self._demo_saved["grid_minimum_height"])
        grid.setMaximumHeight(self._demo_saved["grid_maximum_height"])
        grid.setVisible(self._demo_saved["grid_visible"])
        empty.setVisible(self._demo_saved["empty_visible"])

    def _restore_rule_demo(self) -> None:
        hint = self._demo_saved["hint"]
        hint.setGraphicsEffect(None)
        hint.setMinimumHeight(self._demo_saved["minimum_height"])
        hint.setMaximumHeight(self._demo_saved["maximum_height"])
        hint.setText(self._demo_saved["text"])
        hint.setStyleSheet(self._demo_saved["style"])
        hint.setVisible(self._demo_saved["visible"])

    def _restore_connected_demo(self) -> None:
        dot = self._demo_saved.get("dot")
        if dot is not None:
            dot.setStyleSheet(self._demo_saved["dot_style"])
        status = self._demo_saved.get("status")
        if status is not None:
            status.setText(self._demo_saved["status_text"])
        hint = self._demo_saved.get("hint")
        if hint is None:
            return
        hint.setText(self._demo_saved["hint_text"])
        parent = self.parentWidget()
        show_hint = getattr(parent, "_set_status_hint_visible", None) if parent is not None else None
        if callable(show_hint):
            show_hint(self._demo_saved["hint_wanted"])
        else:
            hint.setVisible(self._demo_saved["hint_visible"])

    # ── lifecycle ─────────────────────────────────────────────────────
    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
            scroll = getattr(parent, "body_scroll", None)
            if scroll is not None:
                for widget in (scroll, scroll.viewport()):
                    widget.installEventFilter(self)
                    self._watched_geometry_widgets.append(widget)
        self._resize_surfaces()
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        self._start_open_animation()

    def _start_open_animation(self) -> None:
        self.layout().activate()
        self._panel.layout().activate()
        end_pos = self._panel.pos()
        self._panel.move(end_pos + QPoint(0, 14))
        self._opacity_effect.setOpacity(0.0)
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(180)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._panel_anim = QPropertyAnimation(self._panel, b"pos", self)
        self._panel_anim.setDuration(220)
        self._panel_anim.setStartValue(end_pos + QPoint(0, 14))
        self._panel_anim.setEndValue(end_pos)
        self._panel_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.finished.connect(self._drop_overlay_effect)
        play_or_complete(self._panel_anim)
        play_or_complete(self._fade_anim)

    def _drop_overlay_effect(self) -> None:
        self.setGraphicsEffect(None)
        self._opacity_effect = None

    def _finish(self) -> None:
        self._autoplay_timer.stop()
        self._spot_anim.stop()
        if self._scroll_anim is not None:
            self._scroll_anim.stop()
        self._restore_demo()
        parent = self.parentWidget()
        for target in self._watched_targets:
            try:
                target.removeEventFilter(self)
            except RuntimeError:
                pass
        self._watched_targets = []
        for widget in self._watched_geometry_widgets:
            try:
                widget.removeEventFilter(self)
            except RuntimeError:
                pass
        self._watched_geometry_widgets = []
        if parent is not None:
            parent.removeEventFilter(self)
            if self._touring and self._initial_section:
                self.sectionRequested.emit(self._initial_section)
                scroll = getattr(parent, "body_scroll", None)
                if scroll is not None:
                    QTimer.singleShot(
                        0,
                        scroll,
                        lambda: scroll.verticalScrollBar().setValue(self._initial_scroll),
                    )
        self.hide()
        self.finished.emit()
        self.deleteLater()

    def _current_section_key(self) -> str:
        parent = self.parentWidget()
        stack = getattr(parent, "_section_stack", None) if parent is not None else None
        pages = getattr(parent, "_nav_pages", {}) if parent is not None else {}
        current = stack.currentWidget() if stack is not None else None
        for key, page in pages.items():
            if page is current:
                return str(key)
        return "color"

    def _body_scroll_value(self) -> int:
        parent = self.parentWidget()
        scroll = getattr(parent, "body_scroll", None) if parent is not None else None
        return scroll.verticalScrollBar().value() if scroll is not None else 0

    def _resize_surfaces(self) -> None:
        intro_width = max(360, min(_INTRO_WIDTH, self.width() - _SURFACE_MARGIN * 2))
        intro_height = max(300, min(_INTRO_HEIGHT, self.height() - _SURFACE_MARGIN * 2))
        self._panel.setFixedSize(intro_width, intro_height)
        tip_width = max(340, min(_TIP_WIDTH, self.width() - _SURFACE_MARGIN * 2))
        tip_height = max(196, min(_TIP_HEIGHT, self.height() - _SURFACE_MARGIN * 2))
        self._tip.setFixedSize(tip_width, tip_height)
        self._position_tip()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._finish()
            return
        if event.key() in {Qt.Key_Return, Qt.Key_Enter, Qt.Key_Right}:
            self._manual_next() if self._touring else self._begin_tour()
            return
        if event.key() == Qt.Key_Left and self._touring:
            self._manual_prev()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        # Once the user takes control, the tour must stop moving underneath them.
        if self._touring:
            self._autoplay = False
            self._autoplay_timer.stop()
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched in (*self._watched_targets, *self._watched_geometry_widgets) and event.type() in {
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
        }:
            if (
                self._demo_saved.get("kind") in {"rule", "scene"}
                and watched is self._target
                and event.type() in {QEvent.Type.Move, QEvent.Type.Resize}
            ):
                # The demo row deliberately grows the Rules card. Follow that
                # geometry every frame instead of clearing and rediscovering the
                # spotlight, which would make the outline flash during reveal.
                self._sync_spotlight_to_target()
                return super().eventFilter(watched, event)
            # A section can continue moving after it becomes visible: the live
            # preview expands when leaving Settings, for example. Keep the frame
            # attached to the real card instead of preserving its first position.
            # Once that section settles, still scroll smoothly: turning this off
            # made a genuinely animated preview force the tour to jump in one
            # frame after waiting for the layout burst.
            self.set_spotlight_rect(QRectF())
            self._geometry_retries = 4
            self._geometry_animate_scroll = True
            self._geometry_timer.start()
        if watched is self.parentWidget() and event.type() in {QEvent.Type.Resize, QEvent.Type.Move}:
            parent = self.parentWidget()
            if parent is not None:
                self.setGeometry(parent.rect())
                self._resize_surfaces()
                # Qt lays out the page after the top-level resize event. Reading
                # card coordinates here preserves the old windowed geometry when
                # the user maximises (and vice versa), so measure once the layout
                # event burst has settled instead.
                self.set_spotlight_rect(QRectF())
                self._geometry_retries = 4
                self._geometry_animate_scroll = False
                self._geometry_timer.start()
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        alpha = 168 if theme_manager.is_dark else 116
        if not self._touring or self._spotlight_rect.isEmpty():
            painter.setBrush(QColor(0, 0, 0, 96 if theme_manager.is_dark else 60))
            painter.drawRect(self.rect())
            return
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        hole = QPainterPath()
        focus_rect = self._spotlight_rect.adjusted(-8, -8, 8, 8)
        hole.addRoundedRect(focus_rect, 12, 12)
        painter.fillPath(shade.subtracted(hole), QColor(0, 0, 0, alpha))
        accent = qcolor_from_token(theme_manager.palette["accent_start"])
        accent.setAlpha(round(210 * self._spotlight_alpha))
        painter.setPen(QPen(accent, 2.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(focus_rect, 12, 12)

    # ── icons ─────────────────────────────────────────────────────────
    def _icon_pixmap(self, kind: str) -> QPixmap:
        cached = self._icon_cache.get(kind)
        if cached is not None:
            return cached
        palette = theme_manager.palette
        accent = qcolor_from_token(palette["accent_start"])
        accent_end = qcolor_from_token(palette["accent_end"])
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = cy = size / 2.0

        glow_color = qcolor_from_token(palette["success_start"]) if kind == "check" else accent
        glow = QRadialGradient(cx, cy, 30.0)
        glow.setColorAt(0.0, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), 120))
        glow.setColorAt(0.6, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), 40))
        glow.setColorAt(1.0, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), 30.0, 30.0)

        if kind == "app":
            app_pixmap = QPixmap(str(_ICON_PATH))
            if not app_pixmap.isNull():
                scaled = app_pixmap.scaled(42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                painter.drawPixmap(int(cx - scaled.width() / 2), int(cy - scaled.height() / 2), scaled)
        elif kind == "sparkle":
            fill = QLinearGradient(cx - 16.0, cy - 16.0, cx + 16.0, cy + 16.0)
            fill.setColorAt(0.0, accent)
            fill.setColorAt(1.0, accent_end)
            painter.setBrush(fill)
            self._draw_sparkle(painter, cx - 4.0, cy, 15.0)
            self._draw_sparkle(painter, cx + 11.0, cy - 11.0, 6.0)
        elif kind == "check":
            pen = QPen(qcolor_from_token(palette["success_start"]), 5.0)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(cx - 12.0, cy + 1.0)
            path.lineTo(cx - 3.0, cy + 10.0)
            path.lineTo(cx + 13.0, cy - 10.0)
            painter.drawPath(path)
        else:
            glyph = self._lucide_glyph(kind, 34, accent)
            if glyph is not None:
                painter.drawPixmap(int(cx - glyph.width() / 2), int(cy - glyph.height() / 2), glyph)
        painter.end()
        self._icon_cache[kind] = pixmap
        return pixmap

    @staticmethod
    def _draw_sparkle(painter: QPainter, cx: float, cy: float, size: float) -> None:
        waist = size * 0.32
        path = QPainterPath()
        path.moveTo(cx, cy - size)
        path.cubicTo(cx + waist, cy - waist, cx + waist, cy - waist, cx + size, cy)
        path.cubicTo(cx + waist, cy + waist, cx + waist, cy + waist, cx, cy + size)
        path.cubicTo(cx - waist, cy + waist, cx - waist, cy + waist, cx - size, cy)
        path.cubicTo(cx - waist, cy - waist, cx - waist, cy - waist, cx, cy - size)
        painter.drawPath(path)

    @staticmethod
    def _lucide_glyph(name: str, size: int, color: QColor) -> QPixmap | None:
        svg = _LUCIDE_DIR / f"{name}.svg"
        if not svg.exists():
            return None
        renderer = QSvgRenderer(str(svg))
        glyph = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        glyph.fill(Qt.transparent)
        glyph_painter = QPainter(glyph)
        glyph_painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(glyph_painter, QRectF(0, 0, size, size))
        glyph_painter.end()
        tint = QImage(glyph.size(), QImage.Format_ARGB32_Premultiplied)
        tint.fill(Qt.transparent)
        tint_painter = QPainter(tint)
        tint_painter.fillRect(tint.rect(), color)
        tint_painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        tint_painter.drawImage(0, 0, glyph)
        tint_painter.end()
        return QPixmap.fromImage(tint)

    def _apply_style(self) -> None:
        palette = theme_manager.palette
        self.setStyleSheet(
            f"""
            #onboardTitle {{
                color: {palette["text"]};
                font-size: 24px;
                font-weight: 800;
            }}
            #onboardBody {{
                color: {palette["text_soft"]};
                font-size: 14px;
                font-weight: 500;
            }}
            #onboardNote {{
                color: {palette["muted"]};
                font-size: 12px;
                font-weight: 600;
            }}
            #onboardTourTitle {{
                color: {palette["text"]};
                font-size: 17px;
                font-weight: 800;
            }}
            #onboardTourBody {{
                color: {palette["text_soft"]};
                font-size: 12.5px;
                font-weight: 500;
            }}
            #onboardDemoStatus {{
                color: {palette["text"]};
                font-size: 12px;
                font-weight: 700;
            }}
            """
        )
