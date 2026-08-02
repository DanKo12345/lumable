from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QWidget,
)

from app.diy_effect_controller import DiyEffectController
from app.diy_effects import MAX_MS, MAX_STEPS, MIN_STEPS, MOTION_KEYS, DiyEffect, DiyStep
from app.effect_share import decode_effect, encode_effect
from app.feature_gate import can_use
from app.storage import save_settings
from app.widgets import ColorPickerOverlay, ColorSwatch, ProfileRenameOverlay
from app.widgets.diy_row import DiyRow

_DEFAULT_STEPS = [
    {"rgb": [255, 77, 77], "duration_ms": 1000, "motion": "none"},
    {"rgb": [91, 140, 255], "duration_ms": 1000, "motion": "none"},
]


def _clean_motion(value: object) -> str:
    return value if value in MOTION_KEYS else "none"


class DiyUiController:
    """Wires the 'DIY effect' editor: a drag-reorderable list of colour steps, a
    transition mode and speed, and run/stop streaming via DiyEffectController.
    Pro-gated; works on any controller through the colour-stream engine."""

    def __init__(self, host: Any) -> None:
        self._host = host
        self._fx = DiyEffectController(host)
        self._steps: list[dict] = []
        self._transition = "smooth"
        self._next_id = 1
        self._color_picker: ColorPickerOverlay | None = None
        self._duration_overlay: ProfileRenameOverlay | None = None
        self._save_overlay: ProfileRenameOverlay | None = None
        self._import_overlay: ProfileRenameOverlay | None = None
        self._share_overlay: ProfileRenameOverlay | None = None

    # ── wiring / state ────────────────────────────────────────────────
    def wire(self) -> None:
        host = self._host
        host.diy_add_button.clicked.connect(self._add_step)
        host.diy_run_button.clicked.connect(self._toggle_run)
        host.diy_transition_segment.selected.connect(self._on_transition_selected)
        host.diy_speed_slider.valueChanged.connect(self._on_speed_changed)
        host.diy_list.reordered.connect(self._on_reordered)
        host.diy_save_button.clicked.connect(self._save_current)
        host.diy_delete_button.clicked.connect(self._delete_saved)
        host.diy_share_button.clicked.connect(self._share_current)
        host.diy_import_button.clicked.connect(self._import_code)
        host.diy_saved_combo.currentIndexChanged.connect(self._on_saved_selected)
        self.sync_controls()
        self.refresh_lock()

    def _config(self) -> dict:
        host = self._host
        config = host._settings.get("diy", {}) if isinstance(host._settings, dict) else {}
        return config if isinstance(config, dict) else {}

    def sync_controls(self) -> None:
        host = self._host
        config = self._config()
        raw_steps = config.get("steps")
        raw_steps = raw_steps if isinstance(raw_steps, list) and raw_steps else _DEFAULT_STEPS
        self._steps = []
        for item in raw_steps:
            if not isinstance(item, dict):
                continue
            rgb = item.get("rgb", [255, 255, 255])
            duration = int(item.get("duration_ms", 1000))
            self._steps.append({
                "id": self._take_id(), "rgb": list(rgb), "duration_ms": duration,
                "motion": _clean_motion(item.get("motion", "none")),
            })
        if len(self._steps) < MIN_STEPS:
            for step in _DEFAULT_STEPS[len(self._steps):]:
                self._steps.append({
                    "id": self._take_id(), "rgb": list(step["rgb"]),
                    "duration_ms": step["duration_ms"], "motion": step["motion"],
                })
        self._transition = "cut" if str(config.get("transition", "smooth")) == "cut" else "smooth"
        host.diy_speed_slider.jump_to(int(config.get("speed", 50)))
        host.diy_speed_value.setText(f"{host.diy_speed_slider.value()}%")
        self._sync_transition_segment()
        self._rebuild_rows()
        self._update_preview()
        self._refresh_saved_combo()

    # ── saved library ─────────────────────────────────────────────────
    def _saved_list(self) -> list[dict]:
        host = self._host
        saved = host._settings.get("diy_saved", []) if isinstance(host._settings, dict) else []
        return saved if isinstance(saved, list) else []

    def _refresh_saved_combo(self, select_name: str = "") -> None:
        host = self._host
        combo = host.diy_saved_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(host._tr("diy.saved_none"), "")
        for entry in self._saved_list():
            name = str(entry.get("name", ""))
            if name:
                combo.addItem(name, name)
        index = combo.findData(select_name) if select_name else 0
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        self._sync_library_actions()

    def _on_saved_selected(self) -> None:
        name = str(self._host.diy_saved_combo.currentData() or "")
        self._sync_library_actions()
        if not name:
            return
        entry = next((e for e in self._saved_list() if str(e.get("name", "")) == name), None)
        if entry is not None:
            self._load_effect(entry)

    def _sync_library_actions(self) -> None:
        name = str(self._host.diy_saved_combo.currentData() or "")
        self._host.diy_delete_button.setEnabled(bool(name) and can_use("diy_effects"))

    def _load_effect(self, entry: dict) -> None:
        host = self._host
        self._steps = []
        for item in entry.get("steps", []):
            if not isinstance(item, dict):
                continue
            self._steps.append({
                "id": self._take_id(),
                "rgb": list(item.get("rgb", [255, 255, 255])),
                "duration_ms": int(item.get("duration_ms", 1000)),
                "motion": _clean_motion(item.get("motion", "none")),
            })
        while len(self._steps) < MIN_STEPS:
            default = _DEFAULT_STEPS[len(self._steps)]
            self._steps.append({
                "id": self._take_id(), "rgb": list(default["rgb"]),
                "duration_ms": default["duration_ms"], "motion": default["motion"],
            })
        self._transition = "cut" if str(entry.get("transition", "smooth")) == "cut" else "smooth"
        host.diy_speed_slider.jump_to(int(entry.get("speed", 50)))
        host.diy_speed_value.setText(f"{host.diy_speed_slider.value()}%")
        self._sync_transition_segment()
        self._rebuild_rows()
        self._persist()
        self._update_preview()
        if self._fx.is_running():
            self._fx.configure(self._build_effect())

    def _save_current(self) -> None:
        host = self._host
        if not can_use("diy_effects"):
            host._show_license_overlay()
            return
        if self._save_overlay is not None:
            self._save_overlay.raise_()
            return
        overlay = ProfileRenameOverlay(
            {
                "title": host._tr("diy.save_title"),
                "prompt": host._tr("diy.save_prompt"),
                "cancel": host._tr("dialog.cancel"),
                "ok": host._tr("dialog.ok"),
            },
            str(host.diy_saved_combo.currentData() or ""),
            host,
        )
        self._save_overlay = overlay
        overlay.nameSelected.connect(self._do_save)
        overlay.closed.connect(lambda: setattr(self, "_save_overlay", None))
        overlay.open()

    def _do_save(self, name: str) -> None:
        host = self._host
        name = name.strip()[:40]
        if not name or not isinstance(host._settings, dict):
            return
        snapshot = {
            "name": name,
            "steps": [{"rgb": list(s["rgb"]), "duration_ms": int(s["duration_ms"]), "motion": s.get("motion", "none")} for s in self._steps],
            "transition": self._transition,
            "speed": int(host.diy_speed_slider.value()),
        }
        saved = [e for e in self._saved_list() if str(e.get("name", "")).lower() != name.lower()]
        saved.append(snapshot)
        host._settings["diy_saved"] = saved[-8:]
        save_settings(host._settings)
        self._refresh_saved_combo(select_name=name)
        host._log(host._tr("diy.saved_log", name=name))

    def _delete_saved(self) -> None:
        host = self._host
        name = str(host.diy_saved_combo.currentData() or "")
        if not name or not isinstance(host._settings, dict):
            return
        host._settings["diy_saved"] = [e for e in self._saved_list() if str(e.get("name", "")) != name]
        save_settings(host._settings)
        self._refresh_saved_combo()

    # ── share / import ────────────────────────────────────────────────
    def _share_current(self) -> None:
        host = self._host
        if not can_use("diy_effects"):
            host._show_license_overlay()
            return
        effect = {
            "name": str(host.diy_saved_combo.currentData() or ""),
            "steps": [{"rgb": list(s["rgb"]), "duration_ms": int(s["duration_ms"]), "motion": s.get("motion", "none")} for s in self._steps],
            "transition": self._transition,
            "speed": int(host.diy_speed_slider.value()),
        }
        code = encode_effect(effect)
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(code)
        host._log(host._tr("diy.share_copied"))
        if self._share_overlay is not None:
            self._share_overlay.raise_()
            return
        # Show the code so the user sees it worked and can copy it manually too.
        overlay = ProfileRenameOverlay(
            {
                "title": host._tr("diy.share_title"),
                "prompt": host._tr("diy.share_copied"),
                "cancel": host._tr("dialog.cancel"),
                "ok": host._tr("dialog.ok"),
            },
            code,
            host,
        )
        self._share_overlay = overlay
        overlay.closed.connect(lambda: setattr(self, "_share_overlay", None))
        overlay.open()

    def _import_code(self) -> None:
        host = self._host
        if not can_use("diy_effects"):
            host._show_license_overlay()
            return
        if self._import_overlay is not None:
            self._import_overlay.raise_()
            return
        overlay = ProfileRenameOverlay(
            {
                "title": host._tr("diy.import_title"),
                "prompt": host._tr("diy.import_prompt"),
                "cancel": host._tr("dialog.cancel"),
                "ok": host._tr("dialog.ok"),
            },
            "",
            host,
        )
        self._import_overlay = overlay
        overlay.nameSelected.connect(self._apply_import)
        overlay.closed.connect(lambda: setattr(self, "_import_overlay", None))
        overlay.open()

    def _apply_import(self, code: str) -> None:
        host = self._host
        entry = decode_effect(code)
        if entry is None:
            host._show_error(host._tr("diy.import_invalid"))
            return
        self._load_effect(entry)
        name = str(entry.get("name", "")).strip()[:40] or host._tr("diy.import_default_name")
        self._do_save(name)

    def _take_id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def _step_by_id(self, step_id: int) -> dict | None:
        return next((s for s in self._steps if s["id"] == step_id), None)

    # ── rows ──────────────────────────────────────────────────────────
    def _rebuild_rows(self) -> None:
        host = self._host
        host.diy_list.clear()
        for step in self._steps:
            host.diy_list.add_row(self._make_row(step["id"]))

    def _make_row(self, step_id: int) -> QWidget:
        host = self._host
        step = self._step_by_id(step_id) or {"rgb": [255, 255, 255], "duration_ms": 1000, "motion": "none"}
        row = DiyRow(str(step_id))
        layout = QHBoxLayout(row)
        # Symmetric vertical padding; the item is sized to this widget's natural
        # height (see _rebuild_rows), so the content sits centred with equal margins.
        layout.setContentsMargins(8, 0, 12, 0)
        layout.setSpacing(8)

        swatch = ColorSwatch(lambda: host._theme_tokens)
        swatch.setFixedSize(26, 26)
        swatch.set_color(QColor(*step["rgb"]))
        swatch.clicked.connect(lambda sid=step_id: self._pick_color(sid))
        layout.addWidget(swatch, 0, Qt.AlignVCenter)

        r, g, b = (int(c) for c in step["rgb"])
        hex_label = QLabel(f"#{r:02X}{g:02X}{b:02X}")
        hex_label.setObjectName("cardSubtitle")
        layout.addWidget(hex_label, 0, Qt.AlignVCenter)
        layout.addStretch(1)

        # Fixed right-side grid: motion / duration / remove.
        right = QWidget()
        right.setFixedWidth(host._sz(310))
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(host._sz(8))
        right_layout.setAlignment(Qt.AlignVCenter)
        right_layout.addStretch(1)

        motion_key = _clean_motion(step.get("motion", "none"))
        motion = host._pill(host._tr(f"diy.motion_{motion_key}"))
        text_width = motion.fontMetrics().horizontalAdvance(motion.text())
        motion.setFixedWidth(max(host._sz(74), text_width + host._sz(30)))
        motion.setToolTip(host._tr("diy.motion_hint"))
        # These chips sit in a bare row with no label beside them, so the
        # purpose has to come from the tooltip's wording.
        motion.set_purpose(host._tr("diy.motion_hint"))
        motion.clicked.connect(lambda _checked=False, sid=step_id: self._cycle_motion(sid))
        right_layout.addWidget(motion, 0, Qt.AlignVCenter)

        value = host._pill(f"{step['duration_ms'] / 1000:.1f} {host._tr('diy.seconds_short')}")
        value.setToolTip(host._tr("diy.duration"))
        value.set_purpose(host._tr("diy.duration"))
        value.clicked.connect(lambda _checked=False, sid=step_id: self._edit_duration(sid))
        right_layout.addWidget(value, 0, Qt.AlignVCenter)

        remove = host._button("✕", "ghost")
        remove.setFixedSize(28, 28)
        remove.clicked.connect(lambda _checked=False, sid=step_id: self._remove_step(sid))
        right_layout.addWidget(remove, 0, Qt.AlignVCenter)

        layout.addWidget(right, 0, Qt.AlignVCenter)
        return row

    # ── edits ─────────────────────────────────────────────────────────
    def _pick_color(self, step_id: int) -> None:
        step = self._step_by_id(step_id)
        if step is None:
            return
        if self._color_picker is not None:
            self._color_picker.raise_()
            return
        host = self._host
        picker = ColorPickerOverlay(
            host._tr("diy.pick_color"),
            QColor(*step["rgb"]),
            {
                "red": host._tr("slider.red"),
                "green": host._tr("slider.green"),
                "blue": host._tr("slider.blue"),
                "hex": host._tr("color.hex"),
                "recent": host._tr("color.recent"),
                "cancel": host._tr("dialog.cancel"),
                "ok": host._tr("dialog.ok"),
            },
            host._color_history(),
            host,
        )
        self._color_picker = picker
        picker.colorSelected.connect(lambda color, sid=step_id: self._apply_picked_color(sid, color))
        picker.closed.connect(lambda: setattr(self, "_color_picker", None))
        picker.open()

    def _apply_picked_color(self, step_id: int, color: QColor) -> None:
        step = self._step_by_id(step_id)
        if step is None:
            return
        step["rgb"] = [color.red(), color.green(), color.blue()]
        self._rebuild_rows()
        self._after_change()

    def _edit_duration(self, step_id: int) -> None:
        step = self._step_by_id(step_id)
        if step is None:
            return
        if self._duration_overlay is not None:
            self._duration_overlay.raise_()
            return
        host = self._host
        overlay = ProfileRenameOverlay(
            {
                "title": host._tr("diy.duration"),
                "prompt": host._tr("diy.seconds_short"),
                "cancel": host._tr("dialog.cancel"),
                "ok": host._tr("dialog.ok"),
            },
            f"{step['duration_ms'] / 1000:.1f}",
            host,
        )
        self._duration_overlay = overlay
        overlay.nameSelected.connect(lambda text, sid=step_id: self._apply_duration_text(sid, text))
        overlay.closed.connect(lambda: setattr(self, "_duration_overlay", None))
        overlay.open()

    def _apply_duration_text(self, step_id: int, text: str) -> None:
        step = self._step_by_id(step_id)
        if step is None:
            return
        try:
            seconds = float(text.replace(",", "."))
        except ValueError:
            return
        step["duration_ms"] = max(0, min(MAX_MS, round(seconds * 1000)))
        self._rebuild_rows()
        self._after_change()

    def _cycle_motion(self, step_id: int) -> None:
        step = self._step_by_id(step_id)
        if step is None:
            return
        current = _clean_motion(step.get("motion", "none"))
        index = MOTION_KEYS.index(current)
        step["motion"] = MOTION_KEYS[(index + 1) % len(MOTION_KEYS)]
        self._rebuild_rows()
        self._after_change()

    def _add_step(self) -> None:
        if not can_use("diy_effects"):
            self._host._show_license_overlay()
            return
        if len(self._steps) >= MAX_STEPS:
            return
        self._steps.append({"id": self._take_id(), "rgb": [255, 200, 60], "duration_ms": 1000, "motion": "none"})
        self._rebuild_rows()
        self._after_change()

    def _remove_step(self, step_id: int) -> None:
        if len(self._steps) <= MIN_STEPS:
            self._host._show_error(self._host._tr("diy.min_steps"))
            return
        self._steps = [s for s in self._steps if s["id"] != step_id]
        self._rebuild_rows()
        self._after_change()

    def _on_reordered(self, keys: list) -> None:
        # The container already moved the row widgets; just mirror the new order
        # into our step list and persist (no rebuild needed).
        by_key = {str(s["id"]): s for s in self._steps}
        self._steps = [by_key[k] for k in keys if k in by_key]
        self._after_change()

    def _on_transition_selected(self, key: str) -> None:
        self._transition = "cut" if key == "cut" else "smooth"
        self._after_change()

    def _on_speed_changed(self) -> None:
        self._host.diy_speed_value.setText(f"{self._host.diy_speed_slider.value()}%")
        self._after_change()

    def _after_change(self) -> None:
        self._persist()
        self._update_preview()
        if self._fx.is_running():
            self._fx.configure(self._build_effect())

    # ── effect build / run ────────────────────────────────────────────
    def _build_effect(self) -> DiyEffect:
        steps: list[DiyStep] = []
        for step in self._steps:
            rgb = tuple(int(c) for c in step["rgb"])
            duration = int(step["duration_ms"])
            motion = _clean_motion(step.get("motion", "none"))
            if self._transition == "cut":
                steps.append(DiyStep(rgb=rgb, transition_ms=0, hold_ms=duration, motion=motion))
            else:
                steps.append(DiyStep(rgb=rgb, transition_ms=duration, hold_ms=0, motion=motion))
        return DiyEffect(steps=tuple(steps), speed=int(self._host.diy_speed_slider.value()))

    def _toggle_run(self) -> None:
        host = self._host
        if not host.diy_run_button.isChecked():
            self._stop_run()
            return
        if not can_use("diy_effects"):
            host.diy_run_button.setChecked(False)
            host._show_license_overlay()
            return
        if not host._is_connected:
            host.diy_run_button.setChecked(False)
            host._show_error(host._tr("diy.not_connected"))
            return
        self._start_run()

    def _start_run(self) -> None:
        host = self._host
        # Only one owner drives the strip at a time — stop the others (screen
        # sync, music, software FX, sleep/sunrise timers).
        host.stop_streams(exclude=self)
        if not host.power_button.isChecked():
            host.power_button.setChecked(True)
            host._toggle_power()
        self._fx.configure(self._build_effect())

        def sink(red: int, green: int, blue: int) -> None:
            host._ble.set_color_stream(red, green, blue)

        self._fx.start(sink)
        self._set_manual_controls_enabled(False)
        host.diy_run_button.set_icon_kind("square")
        host.diy_run_button.setText(host._tr("diy.stop"))
        host._log(host._tr("diy.started_log"))

    def _stop_run(self) -> None:
        host = self._host
        was_running = self._fx.is_running()
        self._fx.stop()
        self._set_manual_controls_enabled(True)
        host.diy_run_button.setChecked(False)
        host.diy_run_button.set_icon_kind("circle-play")
        host.diy_run_button.setText(host._tr("diy.run"))
        if was_running:
            host._log(host._tr("diy.stopped_log"))

    def is_running(self) -> bool:
        return self._fx.is_running()

    def stop_if_running(self) -> None:
        if self._fx.is_running():
            self._stop_run()

    def activate(self) -> bool:
        """Run the current DIY effect as if its Run button was pressed. Returns
        whether it actually started (a gate may have blocked it)."""
        self._host.diy_run_button.setChecked(True)
        self._toggle_run()
        return self.is_running()

    def shutdown(self) -> None:
        self._fx.stop()

    def _set_manual_controls_enabled(self, enabled: bool) -> None:
        host = self._host
        for name in ("red_slider", "green_slider", "blue_slider", "brightness_slider",
                     "pick_color_button", "effect_combo", "speed_slider", "temperature_slider"):
            widget = getattr(host, name, None)
            if widget is not None:
                widget.setEnabled(enabled)

    # ── presentation ──────────────────────────────────────────────────
    def _update_preview(self) -> None:
        preview = getattr(self._host, "diy_preview", None)
        if preview is not None:
            preview.set_colors([tuple(int(c) for c in s["rgb"]) for s in self._steps])
            preview.set_smooth(self._transition == "smooth")
            preview.set_effect(self._build_effect())

    def _sync_transition_segment(self) -> None:
        self._host.diy_transition_segment.set_current(self._transition, animate=False)

    def _persist(self) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        host._settings["diy"] = {
            "steps": [{"rgb": list(s["rgb"]), "duration_ms": int(s["duration_ms"]), "motion": s.get("motion", "none")} for s in self._steps],
            "transition": self._transition,
            "speed": int(host.diy_speed_slider.value()),
        }
        save_settings(host._settings)

    def refresh_lock(self) -> None:
        host = self._host
        unlocked = can_use("diy_effects")
        lock = getattr(host, "diy_lock_label", None)
        if lock is not None:
            lock.setVisible(not unlocked)
        for name in ("diy_list", "diy_add_button", "diy_transition_segment",
                     "diy_speed_slider", "diy_run_button", "diy_saved_combo",
                     "diy_save_button", "diy_delete_button", "diy_share_button", "diy_import_button"):
            widget = getattr(host, name, None)
            if widget is not None:
                widget.setEnabled(unlocked)
        self._sync_library_actions()

    def relocalize(self) -> None:
        host = self._host
        host.diy_library_label.setText(host._tr("diy.library"))
        host.diy_library_hint.setText(host._tr("diy.library_hint"))
        host.diy_timeline_label.setText(host._tr("diy.timeline"))
        host.diy_timeline_hint.setText(host._tr("diy.timeline_hint"))
        host.diy_playback_label.setText(host._tr("diy.playback"))
        host.diy_playback_hint.setText(host._tr("diy.playback_hint"))
        host.diy_add_button.setText(host._tr("diy.add_step"))
        host.diy_transition_label.setText(host._tr("diy.transition"))
        host.diy_transition_segment.set_labels({
            "smooth": host._tr("diy.transition_smooth"),
            "cut": host._tr("diy.transition_cut"),
        })
        self._sync_transition_segment()
        running = self._fx.is_running()
        host.diy_run_button.set_icon_kind("square" if running else "circle-play")
        host.diy_run_button.setText(host._tr("diy.stop") if running else host._tr("diy.run"))
        host.diy_save_button.setText(host._tr("diy.save"))
        for button, key in (
            (host.diy_delete_button, "diy.delete"),
            (host.diy_share_button, "diy.share"),
            (host.diy_import_button, "diy.import"),
        ):
            label = host._tr(key)
            button.setText("")
            button.setAccessibleName(label)
            button.setToolTip(label)
        host._set_slider_label_text("diy.speed", host._tr("diy.speed"))
        self._rebuild_rows()  # row labels (duration / seconds)
        current = str(host.diy_saved_combo.currentData() or "")
        self._refresh_saved_combo(select_name=current)
        self.refresh_lock()
        self._sync_library_actions()
