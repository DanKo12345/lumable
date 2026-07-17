"""Desktop scenes card wiring.

Snapshots the current look into a scene, lists saved scenes, and applies or
deletes them. It reuses the API backend, the scene store and the apply service so
the PC, the phone remote and the Local API all drive one shared model. In 0.3.2 a
scene applies to every connected strip (per-strip BLE addressing lands in 0.3.3).
"""

from __future__ import annotations

from typing import Any

from app import scene_store
from app.local_api.backend import QtApiBackend
from app.scene_apply import SceneApplyService, scene_from_status
from app.storage import save_settings


class SceneUiController:
    def __init__(self, host: Any) -> None:
        self._host = host
        self._backend: QtApiBackend | None = None

    def wire(self) -> None:
        host = self._host
        host.scenes_save_button.clicked.connect(self._save_current)
        host.scenes_name_field.returnPressed.connect(self._save_current)
        host.scenes_apply_button.clicked.connect(self._apply_selected)
        host.scenes_delete_button.clicked.connect(self._delete_selected)
        self.refresh()

    def relocalize(self) -> None:
        # The card title/subtitle are relocalised by UiLocalizationController; here
        # we refresh only the inner widgets this controller owns.
        host = self._host
        host.scenes_name_field.setPlaceholderText(host._tr("scenes.name_placeholder"))
        host.scenes_save_button.setText(host._tr("scenes.save"))
        host.scenes_apply_button.setText(host._tr("scenes.apply"))
        host.scenes_delete_button.setText(host._tr("scenes.delete"))
        host.scenes_hint.setText(host._tr("scenes.hint"))

    # ── helpers ───────────────────────────────────────────────────────
    def _get_backend(self) -> QtApiBackend:
        if self._backend is None:
            self._backend = QtApiBackend(self._host)
        return self._backend

    def _settings(self) -> dict[str, Any]:
        settings = self._host._settings
        return settings if isinstance(settings, dict) else {}

    def _selected_id(self) -> str:
        data = self._host.scenes_combo.currentData()
        return str(data) if data else ""

    # ── actions ───────────────────────────────────────────────────────
    def _save_current(self) -> None:
        host = self._host
        name = host.scenes_name_field.text().strip()
        if not name:
            return
        scene = scene_from_status(self._get_backend().status(), name)
        if scene_store.save_scene(self._settings(), scene) is not None:
            save_settings(host._settings)
            host.scenes_name_field.clear()
            host._log(host._tr("scenes.saved_log", name=name))
            self.refresh()

    def _apply_selected(self) -> None:
        scene_id = self._selected_id()
        if not scene_id:
            return
        scene = scene_store.get_scene(self._settings(), scene_id)
        if scene is None:
            return
        SceneApplyService(self._get_backend()).apply(scene)
        host = self._host
        host._log(host._tr("scenes.applied_log", name=scene.get("name", "")))

    def _delete_selected(self) -> None:
        scene_id = self._selected_id()
        if scene_id and scene_store.delete_scene(self._settings(), scene_id):
            save_settings(self._host._settings)
            self.refresh()

    def refresh(self) -> None:
        host = self._host
        combo = host.scenes_combo
        combo.blockSignals(True)
        combo.clear()
        scenes = scene_store.list_scenes(self._settings())
        for scene in scenes:
            combo.addItem(scene.get("name", ""), scene["scene_id"])
        combo.blockSignals(False)
        has_scenes = bool(scenes)
        combo.setEnabled(has_scenes)
        host.scenes_apply_button.setEnabled(has_scenes)
        host.scenes_delete_button.setEnabled(has_scenes)
