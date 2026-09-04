from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from app.app_info import APP_AUTHOR, APP_CHECKOUT_URL, APP_VERSION
from app.feature_gate import invalidate_pro_cache, is_pro, note_outcome, obtain_receipt
from app.install_identity import NEW, load_identity, save_identity
from app.license import activate_license_key, deactivate_license, normalize_license_key
from app.license_client import ISSUED
from app.storage import save_settings
from app.support import supported_controllers
from app.widgets import AboutOverlay, LicenseOverlay, UpdateOverlay

ACTIVATE = "activate"
RESUME = "resume"
WRONG_KEY = "wrong_key"


def activation_plan(settings: dict, key: str) -> str:
    """What a typed key means on a machine that may already hold one.

    Three answers, and the middle one is the reason this is a function rather
    than a condition inside a closure. ``resume`` is for somebody whose
    activation succeeded and whose receipt did not: typing the same key again
    must finish what it started, not spend a second slot on the same licence.

    ``wrong_key`` is a different key on a machine that already has one. Going
    on would ask the service about the *stored* key while telling the person
    their new one worked. Replacing a licence is its own act — the old
    activation has to be handed back first — and doing that unasked would take
    a slot from a machine that may still be using it.
    """
    licence = settings.get("license", {}) if isinstance(settings, dict) else {}
    if not isinstance(licence, dict):
        licence = {}
    if not str(licence.get("instance_id", "")).strip():
        return ACTIVATE
    stored = normalize_license_key(str(licence.get("license_key", "")))
    return RESUME if stored and stored == normalize_license_key(key) else WRONG_KEY

def _has_licence(settings: dict) -> bool:
    """Whether this installation has anything to lose.

    A receipt on its own counts: it was issued for an installation, so its
    presence is proof that this one was not fresh, whatever else is missing.
    """
    licence = settings.get("license", {}) if isinstance(settings, dict) else {}
    if not isinstance(licence, dict):
        return False
    return bool(
        str(licence.get("license_key", "")).strip()
        or str(licence.get("instance_id", "")).strip()
        or licence.get("receipt")
    )


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

    def show_license_transfer(self) -> None:
        """Hand this machine's activation back so the key works elsewhere.

        The two things that could go wrong are kept apart. Whether there is
        anything to transfer is decided before a window opens, so somebody with
        no licence is told so rather than shown a form that cannot do anything.
        And the deactivation itself is handed to the dialog to run on its own
        thread, because it is up to two calls to Lemon Squeezy and a window
        frozen that long looks like one that has crashed.
        """
        from app.license_transfer import can_transfer, key_to_carry, transfer
        from app.widgets.license_transfer_overlay import LicenseTransferDialog

        host = self._host
        if not can_transfer(host._settings):
            host._log(host._tr("transfer.unavailable"))
            return

        def run() -> tuple[str, str]:
            # deactivate_license is what clears the stored licence, and only
            # once the server has confirmed. Nothing here may write before it.
            return transfer(host._settings, deactivate_license, save_settings)

        dialog = LicenseTransferDialog(
            key_to_carry(host._settings), run, host._tr, parent=host
        )
        dialog.exec()
        if dialog.freed:
            # Nothing the service said about the licence that was here is about
            # this machine any more.
            note_outcome("")
            invalidate_pro_cache()
            host._log(host._tr("transfer.freed_headline"))
            host._apply_localized_texts()
            host._show_license_status()

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
            "needs_internet": host._tr("license.needs_internet"),
            "already_active": host._tr("license.already_active"),
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
            """Take an activation, then earn the receipt that turns it into Pro.

            Runs on the overlay's own worker thread, so both requests happen
            off the interface thread and the window keeps drawing.

            The order matters more than it looks. What Lemon Squeezy grants is
            written down *before* the receipt is asked for: the slot has been
            spent by then, and a service that is briefly unreachable must not
            leave somebody having paid for an activation this machine has no
            record of. The next launch then asks only for the receipt, and
            never activates a second time.
            """
            # The identity this machine activates under. Without one there is
            # nothing for a receipt to be bound to, so the attempt is refused
            # here rather than spending an activation slot on an instance the
            # signing server could never recognise.
            outcome = load_identity(has_licence=_has_licence(host._settings))
            identity = outcome.identity
            if identity is None:
                return False, labels["invalid"]
            if outcome.state == NEW and not save_identity(identity):
                return False, labels["invalid"]

            plan = activation_plan(host._settings, key)
            if plan == WRONG_KEY:
                return False, labels.get("already_active", labels["invalid"])
            if plan == ACTIVATE:
                if not activate_license_key(
                    key, host._settings, installation_hash=identity.installation_hash
                ):
                    return False, labels["invalid"]
                # Kept the moment it is granted, and before anything else can
                # fail. Everything after this is repeatable; this is not.
                save_settings(host._settings)

            # Whatever the service last said was about some other licence.
            # obtain_receipt records the new answer either way, but clearing it
            # first means the window is never showing a refusal about a key
            # that has just been replaced.
            note_outcome("")
            invalidate_pro_cache()
            result = obtain_receipt(
                host._settings, identity, now=datetime.now(UTC)
            )
            invalidate_pro_cache()
            if result == ISSUED:
                return True, labels["activated"]
            if result in ("invalid", "revoked"):
                return False, labels["invalid"]
            # Activated, and not yet vouched for. The licence is safe on this
            # machine; what is missing is one conversation with the service.
            return False, labels.get("needs_internet", labels["invalid"])

        def open_checkout() -> bool:
            url = APP_CHECKOUT_URL.strip()
            if not url:
                return False
            return QDesktopServices.openUrl(QUrl(url))

        def deactivate() -> tuple[bool, str]:
            if deactivate_license(host._settings):
                save_settings(host._settings)
                note_outcome("")
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
            # At once, and not at the next hourly wake-up. Whatever the line
            # said a moment ago was about the licence that is no longer here.
            host._show_license_status()

        def on_deactivated() -> None:
            host._apply_localized_texts()
            host._log(host._tr("license.deactivated_log"))
            host._show_license_status()

        overlay.activated.connect(on_activated)
        overlay.deactivated.connect(on_deactivated)
        overlay.closed.connect(lambda: setattr(self, "_license_overlay", None))
        overlay.open()
