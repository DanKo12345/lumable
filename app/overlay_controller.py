from __future__ import annotations

from typing import Any

from app.app_info import APP_AUTHOR, APP_VERSION
from app.feature_gate import is_pro
from app.license import activate_license_key
from app.storage import save_settings
from app.widgets import AboutOverlay, LicenseOverlay


class OverlayController:
    def __init__(self, host: Any) -> None:
        self._host = host

    def show_about(self) -> None:
        host = self._host
        plan = host._tr("app.edition.pro") if is_pro() else host._tr("app.edition.free")
        labels = {
            "title": host._tr("about.title"),
            "meta": host._tr("about.meta_text", version=APP_VERSION, stage=host._tr("app.version_stage.beta"), plan=plan),
            "author_title": host._tr("about.author_title"),
            "author_text": f"{APP_AUTHOR}\ngithub.com/DanKo12345",
            "privacy_title": host._tr("about.privacy_title"),
            "privacy_text": host._tr("about.privacy_text"),
            "components_title": host._tr("about.components_title"),
            "components_text": host._tr("about.components_text"),
            "ok": host._tr("dialog.ok"),
        }
        AboutOverlay(labels, host).exec()

    def show_license(self) -> None:
        host = self._host
        labels = {
            "title": host._tr("license.title"),
            "subtitle": host._tr("license.subtitle"),
            "key_label": host._tr("license.key_label"),
            "placeholder": host._tr("license.placeholder"),
            "activate": host._tr("license.activate"),
            "buy": host._tr("license.buy"),
            "cancel": host._tr("dialog.cancel"),
            "invalid": host._tr("license.invalid"),
            "activated": host._tr("license.activated"),
            "buy_unavailable": host._tr("license.buy_unavailable"),
        }

        def activate(key: str) -> tuple[bool, str]:
            if activate_license_key(key, host._settings):
                save_settings(host._settings)
                return True, labels["activated"]
            return False, labels["invalid"]

        if LicenseOverlay(labels, activate, host).exec():
            host._apply_localized_texts()
            host._log(host._tr("license.activated_log"))
