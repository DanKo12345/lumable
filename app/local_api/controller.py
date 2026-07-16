"""Owns the local API's lifecycle and its settings-card wiring.

Reads the ``api`` settings, keeps a token, starts/stops the HTTP server on the
right bind address, and reflects all of it in the settings UI. The server only
ever runs when the user has explicitly enabled it.
"""

from __future__ import annotations

import errno
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLineEdit

from app.local_api.backend import QtApiBackend
from app.local_api.config import (
    LAN_WARNING_MAX_SHOWN,
    detect_lan_ip,
    generate_token,
    is_loopback,
    resolve_bind_host,
    validate_api_settings,
)
from app.local_api.mobile_page import build_mobile_page
from app.local_api.pairing import PairingManager
from app.local_api.router import ApiRouter
from app.local_api.server import ApiServer
from app.local_api.sse import SseBroker
from app.storage import save_settings
from app.widgets.api_connect_overlay import ApiConnectOverlay
from app.widgets.lan_access_overlay import LanAccessOverlay
from app.widgets.pair_phone_overlay import PairPhoneOverlay

# Ready-to-paste Home Assistant config. __BASE__/__TOKEN__ are filled with the
# user's live values so there's nothing to edit. Kept as a plain template to
# avoid f-string brace-escaping around HA's {{ }} and the JSON payload.
_HA_TEMPLATE = """rest_command:
  lumable_power:
    url: "__BASE__/power"
    method: POST
    headers:
      Authorization: "Bearer __TOKEN__"
      Content-Type: "application/json"
    payload: '{"on": {{ on }}}'
  lumable_color:
    url: "__BASE__/color"
    method: POST
    headers:
      Authorization: "Bearer __TOKEN__"
      Content-Type: "application/json"
    payload: '{"r": {{ r }}, "g": {{ g }}, "b": {{ b }}}'

sensor:
  - platform: rest
    name: LumaBLE
    resource: "__BASE__/status"
    headers:
      Authorization: "Bearer __TOKEN__"
    value_template: "{{ 'on' if value_json.power else 'off' }}"
    json_attributes: [connected, power, brightness, color, mode]
    scan_interval: 5
"""

_CURL_TEMPLATE = (
    'curl.exe -X POST -H "Authorization: Bearer __TOKEN__" '
    '-H "Content-Type: application/json" -d "{\\"on\\":true}" __BASE__/power'
)


class LocalApiController:
    def __init__(self, host: Any) -> None:
        self._host = host
        self._backend: QtApiBackend | None = None
        self._server: ApiServer | None = None
        self._broker = SseBroker()
        self._pairing = PairingManager()
        self._poll: QTimer | None = None
        self._pair_overlay: PairPhoneOverlay | None = None
        self._pair_timer: QTimer | None = None
        self._lan_confirm_overlay: LanAccessOverlay | None = None

    # ── lifecycle ─────────────────────────────────────────────────────
    def start(self) -> None:
        self.apply_settings()

    def shutdown(self) -> None:
        self.stop()

    def _config(self) -> dict[str, Any]:
        raw = self._host._settings.get("api", {}) if isinstance(self._host._settings, dict) else {}
        return validate_api_settings(raw)

    def _persist(self, config: dict[str, Any]) -> None:
        if isinstance(self._host._settings, dict):
            self._host._settings["api"] = validate_api_settings(config)
            save_settings(self._host._settings)

    def apply_settings(self) -> None:
        self.stop()
        config = self._config()
        if not config["enabled"]:
            return
        if not config["token"]:
            config["token"] = generate_token()
            self._persist(config)
        if self._backend is None:
            self._backend = QtApiBackend(self._host)
        router = ApiRouter(
            self._backend,
            config["token"],
            session_authorizer=self._pairing.is_valid_session,
            pair_handler=self._pairing.pair,
        )
        server = ApiServer(
            router,
            host=resolve_bind_host(config),
            port=config["port"],
            broker=self._broker,
            mobile_page=build_mobile_page(self._mobile_labels(), language=self._host._language),
        )
        try:
            server.start()
        except OSError as exc:
            self._host._show_error(self._describe_bind_error(exc))
            return
        self._server = server
        self._start_polling()
        self._host._log(self._host._tr("api.started_log", url=self.base_url()))
        # Startup is deferred until the UI is ready. Refresh here as well as in
        # the button handlers so a persisted enabled API cannot remain visually
        # stuck on "Try again" after it has successfully bound its port.
        self.refresh()

    def _describe_bind_error(self, exc: OSError) -> str:
        host = self._host
        winerror = getattr(exc, "winerror", None)
        code = getattr(exc, "errno", None)
        if winerror == 10049 or code == errno.EADDRNOTAVAIL:
            return host._tr("api.error_bad_ip")
        if winerror == 10048 or code == errno.EADDRINUSE:
            return host._tr("api.error_port_busy")
        return host._tr("api.start_error", error=str(exc))

    def stop(self) -> None:
        if self._poll is not None:
            self._poll.stop()
        if self._server is not None:
            self._server.stop()
            self._server = None

    def _start_polling(self) -> None:
        # Push live state to SSE subscribers ~1x/sec (main-thread QTimer).
        if self._poll is None:
            self._poll = QTimer(self._host)
            self._poll.setInterval(1000)
            self._poll.timeout.connect(self._publish_status)
        self._publish_status()
        self._poll.start()

    def _publish_status(self) -> None:
        if self._backend is not None:
            self._broker.publish(self._backend.status())
        # Reflect phones pairing/dropping without waiting for a card interaction.
        self._refresh_phones()

    def is_running(self) -> bool:
        return self._server is not None and self._server.is_running()

    def base_url(self) -> str:
        config = self._config()
        return f"http://{resolve_bind_host(config)}:{config['port']}"

    # ── UI wiring ─────────────────────────────────────────────────────
    def wire(self) -> None:
        host = self._host
        host.api_enable_button.clicked.connect(self._on_toggle_enabled)
        host.api_copy_token_button.clicked.connect(self._copy_token)
        host.api_regenerate_button.clicked.connect(self._regenerate_token)
        host.api_port_field.editingFinished.connect(self._on_port_changed)
        host.api_lan_button.clicked.connect(self._on_toggle_lan)
        host.api_lan_host_field.editingFinished.connect(self._on_lan_host_changed)
        host.api_reveal_button.clicked.connect(self.refresh)
        host.api_advanced_toggle.clicked.connect(self._toggle_advanced)
        host.api_help_button.clicked.connect(self._show_connect_help)
        host.api_pair_button.clicked.connect(self._show_pair_phone)
        host.api_disconnect_phones_button.clicked.connect(self._disconnect_all_phones)
        self.refresh()

    def _disconnect_all_phones(self) -> None:
        # Drops every paired phone at once; each must re-pair with a fresh code.
        self._pairing.revoke_all()
        self.refresh()

    def _refresh_phones(self) -> None:
        host = self._host
        count = self._pairing.session_count() if self.is_running() else 0
        has_phones = count > 0
        host.api_phones_label.setText(host._tr("api.phones_connected", count=count))
        host.api_phones_label.setVisible(has_phones)
        host.api_disconnect_phones_button.setVisible(has_phones)

    def _show_pair_phone(self) -> None:
        host = self._host
        if self._pair_overlay is not None:
            return
        labels = {
            "title": host._tr("api.pair_title"),
            "steps": host._tr("api.pair_steps"),
            "code_caption": host._tr("api.pair_code_caption"),
            "ok": host._tr("dialog.ok"),
        }
        url = self._tools_base_url()
        display_url = url if host.api_reveal_button.isChecked() else self._masked_url(url)
        overlay = PairPhoneOverlay(
            labels,
            url,
            self.new_pairing_code(),
            host,
            display_url=display_url,
        )
        self._pair_overlay = overlay
        # Refresh the code before it expires while the window stays open.
        timer = QTimer(host)
        timer.setInterval(240_000)
        timer.timeout.connect(lambda: overlay.set_code(self.new_pairing_code()))
        timer.start()
        self._pair_timer = timer
        overlay.closed.connect(self._on_pair_closed)
        overlay.open()

    def _on_pair_closed(self) -> None:
        self._pair_overlay = None
        if self._pair_timer is not None:
            self._pair_timer.stop()
            self._pair_timer = None

    def _tools_base_url(self) -> str:
        config = self._config()
        return f"http://{resolve_bind_host(config)}:{config['port']}"

    def _show_connect_help(self) -> None:
        host = self._host
        if getattr(self, "_connect_overlay", None) is not None:
            return
        labels = {
            "title": host._tr("api.help_title"),
            "ha_title": host._tr("api.help_ha_title"),
            "ha_desc": host._tr("api.help_ha_desc"),
            "ha_copy": host._tr("api.help_ha_copy"),
            "scripts_title": host._tr("api.help_scripts_title"),
            "scripts_desc": host._tr("api.help_scripts_desc"),
            "scripts_copy": host._tr("api.help_scripts_copy"),
            "sd_title": host._tr("api.help_sd_title"),
            "sd_desc": host._tr("api.help_sd_desc"),
            "ok": host._tr("dialog.ok"),
        }
        overlay = ApiConnectOverlay(labels, host)
        self._connect_overlay = overlay
        overlay.copyHomeAssistant.connect(self._copy_ha_config)
        overlay.copyCurl.connect(self._copy_curl)
        overlay.closed.connect(lambda: setattr(self, "_connect_overlay", None))
        overlay.open()

    def _copy_ha_config(self) -> None:
        text = _HA_TEMPLATE.replace("__BASE__", self._tools_base_url()).replace("__TOKEN__", self._config()["token"])
        QApplication.clipboard().setText(text)
        self._host._log(self._host._tr("api.help_ha_copied"))

    def _copy_curl(self) -> None:
        text = _CURL_TEMPLATE.replace("__BASE__", self._tools_base_url()).replace("__TOKEN__", self._config()["token"])
        QApplication.clipboard().setText(text)
        self._host._log(self._host._tr("api.help_curl_copied"))

    def _toggle_advanced(self) -> None:
        host = self._host
        show = bool(host.api_advanced_toggle.isChecked())
        host.api_advanced_container.setVisible(show)
        host.api_advanced_toggle.setText(host._tr("api.advanced_hide" if show else "api.advanced"))

    def _on_toggle_enabled(self) -> None:
        config = self._config()
        config["enabled"] = bool(self._host.api_enable_button.isChecked())
        if not config["enabled"]:
            self._pairing.revoke_all()  # turning the API off drops paired phones
        self._persist(config)
        self.apply_settings()
        self.refresh()

    # ── phone pairing (used by the "Open on phone" UI) ────────────────
    def new_pairing_code(self) -> str:
        return self._pairing.new_code()

    def pairing_code(self) -> str:
        return self._pairing.current_code()

    def _on_port_changed(self) -> None:
        config = self._config()
        text = self._host.api_port_field.text().strip()
        try:
            config["port"] = int(text)
        except ValueError:
            pass
        self._persist(config)
        if self._config()["enabled"]:
            self.apply_settings()
        self.refresh()

    def _on_toggle_lan(self) -> None:
        config = self._config()
        turning_on = bool(self._host.api_lan_button.isChecked())
        if turning_on and not config["allow_lan"] and config["lan_warning_count"] < LAN_WARNING_MAX_SHOWN:
            # A LAN listener is powerful enough to deserve a deliberate second
            # step. Restore the real saved state while the confirmation is up.
            self._host.api_lan_button.setChecked(False)
            self._show_lan_confirmation()
            return
        self._set_lan_access(turning_on)

    def _show_lan_confirmation(self) -> None:
        if self._lan_confirm_overlay is not None:
            return
        host = self._host
        labels = {
            "title": host._tr("api.lan_confirm_title"),
            "body": host._tr("api.lan_confirm_body"),
            "note": host._tr("api.lan_confirm_note"),
            "cancel": host._tr("dialog.cancel"),
            "allow": host._tr("api.lan_confirm_allow"),
        }
        overlay = LanAccessOverlay(labels, host)
        self._lan_confirm_overlay = overlay
        overlay.accepted.connect(self._confirm_lan_access)
        overlay.closed.connect(self._on_lan_confirmation_closed)
        overlay.open()

    def _confirm_lan_access(self) -> None:
        config = self._config()
        config["lan_warning_count"] = min(LAN_WARNING_MAX_SHOWN, config["lan_warning_count"] + 1)
        self._persist(config)
        self._set_lan_access(True)

    def _on_lan_confirmation_closed(self) -> None:
        self._lan_confirm_overlay = None
        self.refresh()

    def _set_lan_access(self, enabled: bool) -> None:
        config = self._config()
        # Turning LAN on with no address yet? Auto-fill this PC's IP so the user
        # doesn't have to run ipconfig. If we can't find one (offline), don't
        # pretend LAN is on — revert and explain.
        if enabled and not config["lan_host"]:
            detected = detect_lan_ip()
            if not detected:
                self._host.api_lan_button.setChecked(False)
                self._host._show_error(self._host._tr("api.no_ip"))
                self.refresh()
                return
            config["lan_host"] = detected
        config["allow_lan"] = enabled
        # Consent is intentionally stored separately from the LAN preference:
        # a legacy config must not silently expose a fresh installation.
        config["lan_confirmed"] = enabled
        self._persist(config)
        if config["enabled"]:
            self.apply_settings()
        self.refresh()

    def _on_lan_host_changed(self) -> None:
        config = self._config()
        config["lan_host"] = self._host.api_lan_host_field.text().strip()
        self._persist(config)
        if config["enabled"]:
            self.apply_settings()
        self.refresh()

    def _copy_token(self) -> None:
        QApplication.clipboard().setText(self._config()["token"])
        self._host._log(self._host._tr("api.token_copied"))

    def _regenerate_token(self) -> None:
        config = self._config()
        config["token"] = generate_token()
        self._pairing.revoke_all()  # regenerating the token invalidates paired phones
        self._persist(config)
        self.apply_settings()
        self.refresh()

    def refresh(self) -> None:
        host = self._host
        config = self._config()
        running = self.is_running()
        # The button names the action, not the persisted preference.  A failed
        # start must never look like a successfully enabled API.
        host.api_enable_button.setChecked(running)
        if running:
            host.api_enable_button.setText(host._tr("api.disable"))
        elif config["enabled"]:
            host.api_enable_button.setText(host._tr("api.retry"))
        else:
            host.api_enable_button.setText(host._tr("api.off_button"))
        host.api_port_field.setText(str(config["port"]))
        host.api_token_field.setText(self._masked(config["token"]))
        host.api_lan_button.setChecked(config["allow_lan"])
        host.api_lan_host_field.setText(config["lan_host"])
        host.api_lan_host_field.setEnabled(config["allow_lan"])
        host.api_lan_warning.setVisible(config["allow_lan"])

        reveal = host.api_reveal_button.isChecked()
        loopback = is_loopback(resolve_bind_host(config))
        # The LAN IP is hidden by default (masked field + status) so it can't be
        # leaked on stream; the eye toggle reveals it, and only when it matters.
        host.api_lan_host_field.setEchoMode(QLineEdit.Normal if reveal else QLineEdit.Password)
        host.api_reveal_button.setVisible(bool(config["allow_lan"]))
        host.api_pair_button.setVisible(running and not loopback)
        host.api_reveal_button.set_icon_kind("eye-off" if reveal else "eye")
        host.api_reveal_button.setToolTip(host._tr("api.hide" if reveal else "api.reveal"))
        if running and loopback:
            host.api_status_label.setText(host._tr("api.local_only"))
        elif running and reveal:
            host.api_status_label.setText(host._tr("api.running", url=self.base_url()))
        elif running:
            host.api_status_label.setText(host._tr("api.running_masked"))
        elif config["enabled"]:
            host.api_status_label.setText(host._tr("api.start_failed"))
        else:
            host.api_status_label.setText(host._tr("api.status_off"))
        self._refresh_phones()

    def relocalize(self) -> None:
        # The remote is a static page served by the local API. Recreate the
        # server when its desktop language changes so the next phone refresh
        # receives the matching translations too.
        if self.is_running():
            self.apply_settings()
        self.refresh()

    def _mobile_labels(self) -> dict[str, str]:
        host = self._host
        keys = (
            "pair_prompt",
            "pair_connect",
            "pair_invalid",
            "pair_failed",
            "connected",
            "disconnected",
            "power_on",
            "power_off",
            "all_off",
            "pc_modes",
            "pc_screen",
            "pc_music",
            "pc_effect",
            "pc_diy",
            "pc_active",
            "pc_stop",
            "brightness",
            "colour",
            "quick_modes",
            "current_colour",
            "custom_colour",
            "recent_colours",
            "open_palette",
            "close_palette",
            "sent",
            "send_failed",
            "mode_unavailable",
            "mode_chill",
            "mode_gaming",
            "mode_night",
            "mode_rainbow",
        )
        return {key: host._tr(f"remote.{key}") for key in keys}

    @staticmethod
    def _masked(token: str) -> str:
        if not token:
            return ""
        if len(token) <= 8:
            return "•" * len(token)
        return f"{token[:4]}…{token[-4:]}"

    @staticmethod
    def _masked_url(url: str) -> str:
        """Hide the LAN host while keeping the scheme and port recognisable."""
        scheme, separator, host_port = url.partition("://")
        if not separator:
            return "••••••••"
        _, colon, port = host_port.rpartition(":")
        return f"{scheme}://••••••••{colon}{port}" if colon else f"{scheme}://••••••••"
