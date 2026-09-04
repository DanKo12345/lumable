from __future__ import annotations

from typing import TYPE_CHECKING

from app.main_layout import select_section
from app.storage import save_settings
from app.widgets.onboarding_overlay import OnboardingOverlay

if TYPE_CHECKING:
    from app.main_window import MainWindow


class OnboardingController:
    """Own the first-run tour and its one piece of persistent state."""

    def __init__(self, window: MainWindow) -> None:
        self._window = window
        self._overlay: OnboardingOverlay | None = None

    @property
    def overlay(self) -> OnboardingOverlay | None:
        return self._overlay

    def maybe_show(self) -> None:
        settings = self._window._settings
        if isinstance(settings, dict) and settings.get("onboarding_seen"):
            return
        self.show()

    def show(self) -> None:
        if self._overlay is not None:
            self._overlay.raise_()
            return
        overlay = OnboardingOverlay(self.labels(), self._window)
        self._overlay = overlay
        overlay.sectionRequested.connect(
            lambda key: select_section(self._window, key)
        )
        overlay.finished.connect(self._on_finished)
        overlay.open()

    def _on_finished(self) -> None:
        self._overlay = None
        settings = self._window._settings
        if isinstance(settings, dict) and not settings.get("onboarding_seen"):
            settings["onboarding_seen"] = True
            save_settings(settings)

    def labels(self) -> dict:
        tr = self._window._tr
        return {
            "skip": tr("onboarding.skip"),
            "back": tr("onboarding.back"),
            "next": tr("onboarding.next"),
            "finish": tr("onboarding.finish"),
            "tour": tr("onboarding.tour"),
            "welcome_title": tr("onboarding.welcome_title"),
            "welcome_body": tr("onboarding.welcome_body"),
            "welcome_note": tr("onboarding.welcome_note"),
            "demo_searching": tr("onboarding.demo_searching"),
            "demo_connected": tr("onboarding.demo_connected"),
            "demo_scene_title": tr("onboarding.demo_scene_title"),
            "demo_scene_target": tr("onboarding.demo_scene_target"),
            "demo_sync": tr("onboarding.demo_sync"),
            "demo_profile_descriptions": {
                profile: tr(f"ambient.profile.{profile}_desc")
                for profile in ("desktop", "game", "movie")
            },
            "demo_rule_title": tr("onboarding.demo_rule_title"),
            "demo_rule_detail": tr("onboarding.demo_rule_detail"),
            "demo_rule_off": tr("onboarding.demo_rule_off"),
            "demo_rule_on": tr("onboarding.demo_rule_on"),
            "demo_status_searching": tr("onboarding.demo_status_searching"),
            "demo_status_disconnected": tr("onboarding.demo_status_disconnected"),
            "demo_status_connected": tr("onboarding.demo_status_connected"),
            "demo_strip_name": tr("onboarding.demo_strip_name"),
            "tour_steps": [
                {
                    "section": "color",
                    "target": "color_card",
                    "icon": "color",
                    "title": tr("onboarding.tour_color_title"),
                    "body": tr("onboarding.tour_color_body"),
                    "demo": "color",
                },
                {
                    "section": "scenes",
                    "target": "scenes_card",
                    "icon": "layers-3",
                    "title": tr("onboarding.tour_scenes_title"),
                    "body": tr("onboarding.tour_scenes_body"),
                    "demo": "scene",
                },
                {
                    "section": "ambient",
                    "target": "ambient_card",
                    "icon": "monitor",
                    "title": tr("onboarding.tour_sync_title"),
                    "body": tr("onboarding.tour_sync_body"),
                    "demo": "sync",
                },
                {
                    "section": "automations",
                    "target": "automations_rules_card",
                    "icon": "workflow",
                    "title": tr("onboarding.tour_automation_title"),
                    "body": tr("onboarding.tour_automation_body"),
                    "demo": "rule",
                },
                {
                    "section": "settings",
                    "target": "device_card",
                    "icon": "device",
                    "title": tr("onboarding.tour_device_title"),
                    "body": tr("onboarding.tour_device_body"),
                },
                {
                    "section": "settings",
                    "target": "device_status_card",
                    "icon": "circle-dot",
                    "title": tr("onboarding.tour_status_title"),
                    "body": tr("onboarding.tour_status_body"),
                    "demo": "connected",
                },
                {
                    "section": "settings",
                    "target": "diagnostics_card",
                    "icon": "diagnostics",
                    "title": tr("onboarding.tour_diagnostics_title"),
                    "body": tr("onboarding.tour_diagnostics_body"),
                },
            ],
        }
