"""Desktop scenes card wiring.

Snapshots the current look into a scene, lists saved scenes, and applies or
deletes them. It reuses the API backend, the scene store and the apply service so
the PC, the phone remote and the Local API all drive one shared model. Since 0.3.3
a scene targets all strips, the main strip, or a group, resolved through BLE
addressed routing.
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtWidgets import QMenu, QWidget

from app import scene_store
from app.local_api.backend import QtApiBackend
from app.scene_apply import scene_from_status
from app.storage import save_settings
from app.widgets import ProfileConfirmOverlay, SceneTileData


class SceneUiController:
    def __init__(self, host: Any) -> None:
        self._host = host
        self._backend: QtApiBackend | None = None
        self._member_chips: list[tuple[str, Any]] = []
        self._active_scene_id = ""
        # Applying a scene moves the sliders programmatically, and their signals
        # call note_manual_light_change(). The backend delivers those moves
        # synchronously (same-thread invoker), so a flag around the apply call
        # ignores exactly the echoes — and nothing else.
        self._applying_scene = False
        self._delete_overlay: ProfileConfirmOverlay | None = None

    def wire(self) -> None:
        host = self._host
        host.scenes_save_button.clicked.connect(self._save_current)
        host.scenes_name_field.returnPressed.connect(self._save_current)
        host.scenes_grid.scene_activated.connect(self._apply_scene)
        host.scenes_grid.scene_menu_requested.connect(self._open_scene_menu)
        host.groups_create_button.clicked.connect(self._create_group)
        host.groups_name_field.returnPressed.connect(self._create_group)
        host.groups_delete_button.clicked.connect(self._delete_group)
        self.refresh()

    # ── groups ────────────────────────────────────────────────────────
    def _refresh_group_members(self) -> None:
        """One toggle per connected strip, rebuilt from the live device list."""
        host = self._host
        layout = getattr(host, "groups_members_layout", None)
        if layout is None:
            return
        # The chips were registered in host._buttons by host._button(); they must
        # leave that list before deleteLater(), or the next theme refresh walks
        # into a dead C++ object and crashes.
        buttons_registry = getattr(host, "_buttons", None)
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                if buttons_registry is not None and widget in buttons_registry:
                    buttons_registry.remove(widget)
                widget.deleteLater()
        self._member_chips = []
        try:
            devices = self._get_backend().devices()
        except Exception:
            devices = []
        for device in devices:
            address = str(device.get("address", "")).strip()
            if not address:
                continue
            chip = host._button(str(device.get("name") or address), "ghost")
            chip.setCheckable(True)
            layout.addWidget(chip)
            self._member_chips.append((address, chip))
        has_strips = bool(self._member_chips)
        host.groups_members_container.setVisible(has_strips)
        host.groups_empty_state.setVisible(not has_strips)
        host.groups_create_button.setEnabled(has_strips)

    def _refresh_groups_combo(self) -> None:
        host = self._host
        combo = host.groups_combo
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        groups = scene_store.list_groups(self._settings())
        for group in groups:
            combo.addItem(group["name"], group["group_id"])
        index = combo.findData(previous)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        has_groups = bool(groups)
        combo.setEnabled(has_groups)
        host.groups_delete_button.setEnabled(has_groups)

    def _create_group(self) -> None:
        host = self._host
        name = host.groups_name_field.text().strip()
        members = [address for address, chip in self._member_chips if chip.isChecked()]
        if not name or not members:
            return
        if scene_store.save_group(self._settings(), name, members) is not None:
            save_settings(host._settings)
            host.groups_name_field.clear()
            host._log(host._tr("groups.created_log", name=name, count=len(members)))
            self.refresh()

    def _delete_group(self) -> None:
        group_id = str(self._host.groups_combo.currentData() or "")
        if group_id and scene_store.delete_group(self._settings(), group_id):
            save_settings(self._host._settings)
            self.refresh()

    def relocalize(self) -> None:
        # The card title/subtitle are relocalised by UiLocalizationController; here
        # we refresh only the inner widgets this controller owns.
        host = self._host
        host.scenes_name_field.setPlaceholderText(host._tr("scenes.name_placeholder"))
        host.scenes_create_heading.setText(host._tr("scenes.create_section"))
        host.scenes_saved_heading.setText(host._tr("scenes.saved_section"))
        host.scenes_save_button.setText(host._tr("scenes.save"))
        host.scenes_empty_label.setText(host._tr("scenes.empty"))
        host.scenes_target_label.setText(host._tr("scenes.target_label"))
        host.scenes_hint.setText(host._tr("scenes.hint"))
        host.groups_name_field.setPlaceholderText(host._tr("groups.name_placeholder"))
        host.groups_create_button.setText(host._tr("groups.create"))
        host.groups_delete_button.setText(host._tr("groups.delete"))
        host.groups_empty_label.setText(host._tr("groups.no_strips"))
        host.groups_hint.setText(host._tr("groups.hint"))
        self._refresh_targets()  # the built-in target names are translated too
        self._refresh_scenes_grid()  # tile target labels are translated too

    # ── helpers ───────────────────────────────────────────────────────
    def _get_backend(self) -> QtApiBackend:
        if self._backend is None:
            self._backend = QtApiBackend(self._host)
        return self._backend

    def _settings(self) -> dict[str, Any]:
        settings = self._host._settings
        return settings if isinstance(settings, dict) else {}

    def _selected_target(self) -> dict[str, Any]:
        """The target a newly saved scene should carry. 'all' keeps the familiar
        behaviour; primary or a group route as addressed BLE writes."""
        data = str(self._host.scenes_target_combo.currentData() or "all")
        if data.startswith("group:"):
            return {"kind": "group", "group_id": data.split(":", 1)[1]}
        if data == "primary":
            return {"kind": "primary"}
        return {"kind": "all"}

    def _refresh_targets(self) -> None:
        host = self._host
        combo = host.scenes_target_combo
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(host._tr("scenes.target_all"), "all")
        combo.addItem(host._tr("scenes.target_primary"), "primary")
        for group in scene_store.list_groups(self._settings()):
            combo.addItem(group["name"], f"group:{group['group_id']}")
        index = combo.findData(previous)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    # ── actions ───────────────────────────────────────────────────────
    def _save_current(self) -> None:
        host = self._host
        name = host.scenes_name_field.text().strip()
        if not name:
            return
        scene = scene_from_status(self._get_backend().status(), name, target=self._selected_target())
        if scene_store.save_scene(self._settings(), scene) is not None:
            save_settings(host._settings)
            host.scenes_name_field.clear()
            host._log(host._tr("scenes.saved_log", name=name))
            self.refresh()

    def _apply_scene(self, scene_id: str) -> None:
        scene_id = str(scene_id or "")
        if not scene_id:
            return
        scene = scene_store.get_scene(self._settings(), scene_id)
        if scene is None:
            return
        # Go through the backend so the desktop uses the same targeting/report
        # path as the phone remote and the Local API.
        self._applying_scene = True
        try:
            report = self._get_backend().apply_scene(scene_id) or {}
        finally:
            self._applying_scene = False
        host = self._host
        name = scene.get("name", "")
        reached = report.get("targets") or []
        if reached:
            self._set_active_scene(scene_id)
            host._log(host._tr("scenes.applied_to_log", name=name, targets=", ".join(reached)))
            return
        # The scene points at a group whose strips are gone or offline — say so
        # instead of claiming success, and hint at how to fix it.
        if str((scene.get("target") or {}).get("kind", "all")) != "all":
            host._show_error(host._tr("scenes.target_gone", name=name))
        else:
            self._set_active_scene(scene_id)
            host._log(host._tr("scenes.applied_log", name=name))

    def _set_active_scene(self, scene_id: str) -> None:
        self._active_scene_id = scene_id
        grid = getattr(self._host, "scenes_grid", None)
        if grid is not None:
            grid.set_active(scene_id or None)

    def note_manual_light_change(self) -> None:
        """Clear the applied-scene highlight once the user changes the light by
        hand — the strip no longer shows that scene. Programmatic echoes from an
        in-flight apply are ignored via the _applying_scene flag."""
        if not self._active_scene_id or self._applying_scene:
            return
        self._set_active_scene("")

    def _open_scene_menu(self, scene_id: str, global_pos: Any) -> None:
        host = self._host
        if not isinstance(host, QWidget):  # headless (tests) — no popup to show
            return
        menu = QMenu(cast(QWidget, host))
        delete_action = menu.addAction(host._tr("scenes.delete"))
        chosen = menu.exec(global_pos)
        if chosen is delete_action:
            self._confirm_delete_scene(scene_id)

    def _confirm_delete_scene(self, scene_id: str) -> None:
        host = self._host
        scene = scene_store.get_scene(self._settings(), scene_id)
        if scene is None:
            return
        if self._delete_overlay is not None:
            return
        if not isinstance(host, QWidget):  # headless (tests): no dialog to show
            self._delete_scene(scene_id)
            return
        overlay = ProfileConfirmOverlay(
            {
                "title": host._tr("scenes.delete_confirm_title"),
                "message": host._tr("scenes.delete_confirm_text", name=scene.get("name", "")),
                "cancel": host._tr("dialog.cancel"),
                "confirm": host._tr("scenes.delete"),
            },
            cast(QWidget, host),
            confirm_role="danger",
        )
        self._delete_overlay = overlay
        overlay.confirmed.connect(lambda scene_id=scene_id: self._delete_scene(scene_id))
        overlay.closed.connect(lambda: setattr(self, "_delete_overlay", None))
        overlay.open()

    def _delete_scene(self, scene_id: str) -> None:
        if scene_id and scene_store.delete_scene(self._settings(), scene_id):
            save_settings(self._host._settings)
            if self._active_scene_id == scene_id:
                self._set_active_scene("")
            self.refresh()

    def _target_label(self, scene: dict[str, Any], group_names: dict[str, str]) -> str:
        host = self._host
        target = scene.get("target") or {}
        kind = str(target.get("kind", "all"))
        if kind == "primary":
            return host._tr("scenes.target_primary")
        if kind == "group":
            group_id = str(target.get("group_id", ""))
            return group_names.get(group_id) or host._tr("scenes.target_missing")
        return host._tr("scenes.target_all")

    def _refresh_scenes_grid(self) -> None:
        host = self._host
        grid = getattr(host, "scenes_grid", None)
        if grid is None:
            return
        scenes = scene_store.list_scenes(self._settings())
        group_names = {group["group_id"]: group["name"] for group in scene_store.list_groups(self._settings())}
        entries = [
            SceneTileData(
                scene_id=scene["scene_id"],
                name=scene.get("name", ""),
                color=str(scene.get("color", "")),
                target_label=self._target_label(scene, group_names),
            )
            for scene in scenes
        ]
        if self._active_scene_id and all(entry.scene_id != self._active_scene_id for entry in entries):
            self._active_scene_id = ""  # the applied scene was deleted/overwritten away
        grid.set_scenes(entries, active_id=self._active_scene_id)
        has_scenes = bool(entries)
        grid.setVisible(has_scenes)
        host.scenes_empty_state.setVisible(not has_scenes)

    def refresh(self) -> None:
        self._refresh_group_members()
        self._refresh_groups_combo()
        self._refresh_targets()
        self._refresh_scenes_grid()
