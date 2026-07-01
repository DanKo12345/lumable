from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer

from app.app_triggers import AppRule, match_rule
from app.foreground import foreground_process_name
from app.scene_presets import get_scene_preset

_POLL_INTERVAL_MS = 1500


class AppTriggerController(QObject):
    """Watches the foreground app and switches the strip to a mapped scene.

    Polls the active window's process every ~1.5s; when the foreground app
    changes, the first matching rule's scene is applied (or a default scene when
    nothing matches). Stays out of the way while a streaming mode (music / screen
    sync / app animation) owns the strip, and only acts when enabled.
    """

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self._host = host
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._last_process = ""
        self._last_scene = ""

    def start(self) -> None:
        self._timer.start()

    def _config(self) -> dict:
        settings = self._host._settings
        config = settings.get("app_triggers", {}) if isinstance(settings, dict) else {}
        return config if isinstance(config, dict) else {}

    def is_enabled(self) -> bool:
        return bool(self._config().get("enabled", False))

    def _streaming_mode_running(self) -> bool:
        host = self._host
        for attr in ("_ambient_ui", "_music_ui", "_software_fx_ui", "_diy_ui"):
            controller = getattr(host, attr, None)
            if controller is not None and controller.is_running():
                return True
        return False

    def _rules(self) -> list[AppRule]:
        rules = self._config().get("rules", [])
        if not isinstance(rules, list):
            return []
        return [
            AppRule(app=str(item.get("app", "")), scene=str(item.get("scene", "")))
            for item in rules
            if isinstance(item, dict)
        ]

    def _tick(self) -> None:
        host = self._host
        if not self.is_enabled() or not host._is_connected or self._streaming_mode_running():
            return
        process = foreground_process_name()
        if process == self._last_process:
            return  # foreground app unchanged since the last poll
        self._last_process = process
        rule = match_rule(process, self._rules())
        scene = rule.scene if rule is not None else str(self._config().get("default", "")).strip()
        if not scene or scene == self._last_scene or get_scene_preset(scene) is None:
            return
        self._last_scene = scene
        host._apply_scene_preset(scene)
