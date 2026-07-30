from __future__ import annotations

from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from app.app_info import APP_AUTHOR, APP_CHECKOUT_URL, APP_VERSION
from app.feature_gate import invalidate_pro_cache, is_pro
from app.license import activate_license_key, deactivate_license
from app.storage import save_settings
from app.support import supported_controllers
from app.widgets import AboutOverlay, LicenseOverlay, UpdateOverlay


def _supported_catalog_text(intro: str) -> str:
    """A readable bullet list of the controller families LumaBLE supports, built
    from the live driver list so it never drifts from what actually works."""
    lines = [intro] if intro else []
    for entry in supported_controllers():
        aliases = entry.get("aliases", "")
        suffix = f"  ({aliases})" if aliases else ""
        lines.append(f"• {entry['name']}{suffix}")
    return "\n".join(lines)


class OverlayController:
    def __init__(self, host: Any) -> None:
        self._host = host
        self._about_overlay: AboutOverlay | None = None
        self._license_overlay: LicenseOverlay | None = None
        self._update_overlay: UpdateOverlay | None = None

    def show_update(self, info) -> None:
        host = self._host
        if self._update_overlay is not None:
            self._update_overlay.raise_()
            return
        labels = {
            "title": host._tr("updates.popup_title"),
            "release": str(getattr(info, "title", "") or ""),
            "versions": host._tr("updates.popup_versions", current=info.current_version, latest=info.latest_version),
            "installed": host._tr("updates.popup_installed"),
            "available": host._tr("updates.popup_available"),
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "whats_new": host._tr("updates.popup_whats_new"),
            "notes": str(getattr(info, "notes", "") or ""),
            "open": host._tr("updates.popup_open"),
            "later": host._tr("updates.popup_later"),
            "skip": host._tr("updates.popup_skip"),
            "close": host._tr("dialog.close"),
        }
        overlay = UpdateOverlay(labels, info.latest_version, host)
        self._update_overlay = overlay
        overlay.update_requested.connect(host._update_controller.open_update_page)
        overlay.skip_requested.connect(host._update_controller.skip_version)
        overlay.closed.connect(lambda: setattr(self, "_update_overlay", None))
        overlay.open()

    def show_about(self) -> None:
        host = self._host
        if self._about_overlay is not None:
            self._about_overlay.raise_()
            return
        plan = host._tr("app.edition.pro") if is_pro() else host._tr("app.edition.free")
        labels = {
            "title": host._tr("about.title"),
            "meta": host._tr("about.meta_text", version=APP_VERSION, stage=host._tr("app.version_stage.beta"), plan=plan),
            "author_title": host._tr("about.author_title"),
            "author_text": f"{APP_AUTHOR}\ngithub.com/DanKo12345",
            "supported_title": host._tr("about.supported_title"),
            "supported_text": _supported_catalog_text(host._tr("about.supported_intro")),
            "privacy_title": host._tr("about.privacy_title"),
            "privacy_text": host._tr("about.privacy_text"),
            "components_title": host._tr("about.components_title"),
            "components_text": host._tr("about.components_text"),
            "guide": host._tr("about.show_guide"),
            "ok": host._tr("dialog.ok"),
        }
        overlay = AboutOverlay(labels, host)
        self._about_overlay = overlay
        overlay.closed.connect(lambda: setattr(self, "_about_overlay", None))
        overlay.guideRequested.connect(host.show_onboarding)
        overlay.open()

    def show_license(self) -> None:
        host = self._host
        if self._license_overlay is not None:
            self._license_overlay.raise_()
            return
        labels = {
            "title": host._tr("license.title"),
            "hero_title": host._tr("license.hero_title"),
            "subtitle": host._tr("license.subtitle"),
            "have_key": host._tr("license.have_key"),
            "back": host._tr("dialog.back"),
            "close": host._tr("dialog.close"),
            "feat_music": host._tr("license.feat_music"),
            "feat_music_desc": host._tr("license.feat_music_desc"),
            "feat_screen": host._tr("license.feat_screen"),
            "feat_screen_desc": host._tr("license.feat_screen_desc"),
            "feat_diy": host._tr("license.feat_diy"),
            "feat_diy_desc": host._tr("license.feat_diy_desc"),
            "feat_schedule": host._tr("license.feat_schedule"),
            "feat_schedule_desc": host._tr("license.feat_schedule_desc"),
            "feat_effects": host._tr("license.feat_effects"),
            "feat_effects_desc": host._tr("license.feat_effects_desc"),
            "feat_profiles": host._tr("license.feat_profiles"),
            "feat_profiles_desc": host._tr("license.feat_profiles_desc"),
            "active_title": host._tr("license.active_title"),
            "active_license": host._tr("license.active_license"),
            "active_dev": host._tr("license.active_dev"),
            "key_label": host._tr("license.key_label"),
            "placeholder": host._tr("license.placeholder"),
            "activate": host._tr("license.activate"),
            "activating": host._tr("license.activating"),
            "buy": host._tr("license.buy"),
            "cancel": host._tr("dialog.cancel"),
            "ok": host._tr("dialog.ok"),
            "invalid": host._tr("license.invalid"),
            "activated": host._tr("license.activated"),
            "buy_unavailable": host._tr("license.buy_unavailable"),
            "deactivate": host._tr("license.deactivate"),
            "deactivate_confirm": host._tr("license.deactivate_confirm"),
            "deactivated": host._tr("license.deactivated"),
            "deactivate_failed": host._tr("license.deactivate_failed"),
        }
        license_state = host._settings.get("license", {})
        is_license_pro = is_pro()
        is_dev_pro = bool(is_license_pro and not str(license_state.get("license_key", "")).strip())
        mode = "dev" if is_dev_pro else ("license" if is_license_pro else "free")

        def activate(key: str) -> tuple[bool, str]:
            if activate_license_key(key, host._settings):
                save_settings(host._settings)
                invalidate_pro_cache()
                return True, labels["activated"]
            return False, labels["invalid"]

        def open_checkout() -> bool:
            url = APP_CHECKOUT_URL.strip()
            if not url:
                return False
            return QDesktopServices.openUrl(QUrl(url))

        def deactivate() -> tuple[bool, str]:
            if deactivate_license(host._settings):
                save_settings(host._settings)
                invalidate_pro_cache()
                return True, labels["deactivated"]
            return False, labels["deactivate_failed"]

        overlay = LicenseOverlay(
            labels,
            activate,
            host,
            mode=mode,
            buy_callback=open_checkout,
            deactivate_callback=deactivate,
            license_key=str(license_state.get("license_key", "")).strip(),
        )
        self._license_overlay = overlay

        def on_activated() -> None:
            host._apply_localized_texts()
            host._log(host._tr("license.activated_log"))

        def on_deactivated() -> None:
            host._apply_localized_texts()
            host._log(host._tr("license.deactivated_log"))

        overlay.activated.connect(on_activated)
        overlay.deactivated.connect(on_deactivated)
        overlay.closed.connect(lambda: setattr(self, "_license_overlay", None))
        overlay.open()
