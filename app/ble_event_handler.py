from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.device_names import device_display_name, sanitize_device_name, validate_extra_addresses
from app.storage import save_settings
from app.types import BleEventHost
from app.widgets import LiquidButton, ProfileConfirmOverlay, ProfileRenameOverlay

# Widening gaps for re-reaching a remembered strip that was switched off.
# Bounded: after the last one it stays saved and joins on the next connect.
RESTORE_BACKOFF_SECONDS = (10, 30, 60, 120)


def _is_plausible_ble_address(address: str) -> bool:
    text = str(address).strip()
    if not text:
        return False
    parts = text.split(":")
    if len(parts) == 6:
        hex_digits = set("0123456789abcdefABCDEF")
        return all(len(part) == 2 and all(char in hex_digits for char in part) for part in parts)
    return len(text) >= 12


class BleEventHandler:
    def __init__(self, host: BleEventHost) -> None:
        self._host = host
        self._mirror_scan_pending = False
        self._mirror_search_phase = 0
        # MainWindow is a QObject in production, while the small unit-test host
        # deliberately is not. Keep the timer parented in the app without making
        # the non-Qt handler tests depend on a widget fixture.
        self._mirror_search_timer = QTimer(host if isinstance(host, QObject) else None)
        self._mirror_search_timer.setInterval(420)
        self._mirror_search_timer.timeout.connect(self._animate_mirror_search)
        self._rename_overlay: ProfileRenameOverlay | None = None
        self._promote_overlay: ProfileConfirmOverlay | None = None
        # One pending retry timer per remembered strip that is not up yet.
        self._restore_timers: dict[str, QTimer] = {}

    def _set_mirror_searching(self, searching: bool) -> None:
        """Give the secondary-strip search its own visible progress state."""
        host = self._host
        heading = getattr(host, "device_mirrors_heading", None)
        button = getattr(host, "add_mirror_button", None)
        if searching:
            self._mirror_search_phase = 1
            if heading is not None:
                heading.setText(f"{host._tr('device.mirror_searching')}{'.' * self._mirror_search_phase}")
            if button is not None:
                button.setEnabled(False)
            self._mirror_search_timer.start()
            return
        self._mirror_search_timer.stop()
        if heading is not None:
            heading.setText(host._tr("device.mirrors_section"))
        if button is not None:
            button.setEnabled(bool(host._is_connected))

    def _animate_mirror_search(self) -> None:
        if not self._mirror_scan_pending:
            self._mirror_search_timer.stop()
            return
        self._mirror_search_phase = self._mirror_search_phase % 3 + 1
        heading = getattr(self._host, "device_mirrors_heading", None)
        if heading is not None:
            heading.setText(f"{self._host._tr('device.mirror_searching')}{'.' * self._mirror_search_phase}")

    # ── remembered extra strips ───────────────────────────────────────
    # Only addresses are stored (names live in device_names, the driver is
    # re-detected), so a multi-strip setup — and the groups and scenes built on
    # it — survives a restart instead of silently shrinking to one strip.
    def _saved_extras(self) -> list[str]:
        settings = self._host._settings
        if not isinstance(settings, dict):
            return []
        return validate_extra_addresses(settings.get("extra_device_addresses", []))

    def _store_extras(self, addresses: list[str]) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        cleaned = validate_extra_addresses(addresses)
        if cleaned == self._saved_extras():
            return  # nothing changed — don't churn the settings file
        host._settings["extra_device_addresses"] = cleaned
        save_settings(host._settings)

    def _remember_extras(self, live: list[str]) -> None:
        """Union, never subtract: losing the link (which emits an empty list)
        must not erase what the user deliberately added."""
        saved = self._saved_extras()
        merged = saved + [item for item in validate_extra_addresses(live) if item not in saved]
        self._store_extras(merged)

    def _forget_extra(self, address: str) -> None:
        wanted = str(address).strip().upper()
        self._store_extras([item for item in self._saved_extras() if item != wanted])

    def _remove_extra(self, address: str) -> None:
        """"Remove" means disconnect *and* forget — otherwise it would come back
        on the next launch."""
        wanted = str(address).strip().upper()
        self._cancel_restore(address)  # stop chasing a strip the user dropped
        self._forget_extra(address)
        self._host._ble.remove_mirror_device(address)
        # An offline strip has no live connection, so remove_mirror_device
        # returns without emitting anything — refresh here or its row lingers.
        # The disconnect is queued, so the live list still names this strip:
        # filter it out, otherwise the refresh would remember it again and the
        # removal would silently undo itself.
        live = [
            item for item in self._host._ble.mirror_addresses() if item.strip().upper() != wanted
        ]
        self.refresh_mirror_list(live)

    def _restore_saved_extras(self, primary_address: str) -> None:
        """Bring remembered extras back up after the primary connected.

        Runs on every successful primary connect, not just at startup: a
        reconnect tears every extra link down, so restoring only once would
        quietly leave the user with a single strip after the first dropout.
        """
        host = self._host
        saved = self._saved_extras()
        if not saved:
            return
        primary = str(primary_address).strip().upper()
        live = {item.strip().upper() for item in host._ble.mirror_addresses()}
        for address in saved:
            if address == primary or address in live:
                continue
            self._cancel_restore(address)  # a fresh primary link restarts the schedule
            host._ble.restore_mirror_device(address)
            self._schedule_restore(address, 1)
        # Render the remembered strips right away: on a cold start with an
        # unavailable one nothing else would emit mirrors_changed, so the row
        # would never appear.
        self.refresh_mirror_list(host._ble.mirror_addresses())

    # ── bounded retry for a remembered strip that is not up yet ───────
    def _schedule_restore(self, address: str, attempt: int) -> None:
        """Queue the next attempt for one strip, with a widening gap.

        A strip switched on a minute after launch has to join by itself —
        otherwise the "saved, will connect" promise is a lie. Bounded on
        purpose: after the last gap it stays remembered and joins on the next
        primary connect instead of scanning forever.
        """
        if attempt >= len(RESTORE_BACKOFF_SECONDS):
            self._restore_timers.pop(address, None)
            return
        host = self._host
        timer = QTimer(host if isinstance(host, QObject) else None)
        timer.setSingleShot(True)
        timer.setInterval(RESTORE_BACKOFF_SECONDS[attempt] * 1000)
        timer.timeout.connect(lambda a=address, n=attempt: self._retry_restore(a, n))
        self._restore_timers[address] = timer
        timer.start()

    def _retry_restore(self, address: str, attempt: int) -> None:
        host = self._host
        self._restore_timers.pop(address, None)
        if address not in self._saved_extras():
            return  # removed while waiting
        if not getattr(host, "_is_connected", False):
            return  # no primary to mirror; the next connect restarts this
        if address in {item.strip().upper() for item in host._ble.mirror_addresses()}:
            return  # it joined already
        host._ble.restore_mirror_device(address)
        self._schedule_restore(address, attempt + 1)

    def _cancel_restore(self, address: str) -> None:
        timer = self._restore_timers.pop(str(address).strip().upper(), None)
        if timer is not None:
            timer.stop()

    def _cancel_all_restores(self) -> None:
        for timer in list(self._restore_timers.values()):
            timer.stop()
        self._restore_timers.clear()

    def _device_names(self) -> dict[str, str]:
        names = self._host._settings.get("device_names") if isinstance(self._host._settings, dict) else {}
        return names if isinstance(names, dict) else {}

    def _display_name(self, address: str, advertised: str = "") -> str:
        return device_display_name(address, advertised, self._device_names())

    def rename_device(self, address: str) -> None:
        host = self._host
        address = str(address).strip()
        if not address or self._rename_overlay is not None:
            return
        overlay = ProfileRenameOverlay(
            {
                "title": host._tr("device.rename_title"),
                "prompt": host._tr("device.rename_prompt"),
                "cancel": host._tr("dialog.cancel"),
                "ok": host._tr("dialog.ok"),
            },
            self._device_names().get(address, ""),
            host,
        )
        self._rename_overlay = overlay
        overlay.nameSelected.connect(lambda text, a=address: self._apply_device_name(a, text))
        overlay.closed.connect(lambda: setattr(self, "_rename_overlay", None))
        overlay.open()

    def promote_device(self, address: str, name: str = "") -> None:
        """Ask before swapping which strip is the main one."""
        host = self._host
        address = str(address).strip()
        if not address or self._promote_overlay is not None:
            return
        label = name or self._display_name(address)
        current = str(host._settings.get("last_device_address", "")).strip()
        current_label = self._display_name(current) if current else ""
        overlay = ProfileConfirmOverlay(
            {
                "title": host._tr("device.make_primary"),
                "message": host._tr("device.make_primary_confirm", name=label),
                "cancel": host._tr("dialog.cancel"),
                "confirm": host._tr("device.make_primary"),
            },
            host,
            # The user means one of two things: swap roles (both strips stay
            # lit) or switch over (the old one goes dark). Ask instead of
            # silently picking the first, but default to it so the existing
            # behaviour is unchanged for anyone who just confirms.
            toggle_label=host._tr("device.keep_old_primary", name=current_label or "—"),
            toggle_checked=True,
        )
        self._promote_overlay = overlay
        overlay.confirmed.connect(
            lambda a=address, o=overlay: host._ble.promote_mirror_to_primary(
                a, keep_old_as_extra=o.toggle_checked()
            )
        )
        overlay.closed.connect(lambda: setattr(self, "_promote_overlay", None))
        overlay.open()

    def on_primary_changed(self, address: str, name: str) -> None:
        """The main strip swapped places with a mirror — follow it everywhere."""
        host = self._host
        address = str(address).strip()
        if not address:
            return
        display = self._display_name(address, str(name or "").strip())
        if isinstance(host._settings, dict):
            host._settings["last_device_address"] = address
            host._settings["last_device_name"] = display
            save_settings(host._settings)
        # The roles just swapped: the new primary stops being an extra, and the
        # old one joins the extras when it was kept connected. Offline extras
        # that were saved earlier stay remembered.
        saved = [item for item in self._saved_extras() if item != address.strip().upper()]
        for item in validate_extra_addresses(host._ble.mirror_addresses()):
            if item not in saved:
                saved.append(item)
        self._store_extras(saved)
        self._relabel_device_combo()
        self._sync_last_device_hint(name=display, address=address)
        self.refresh_mirror_list(host._ble.mirror_addresses())
        # Scene targets ("primary"/groups) and the group member chips are keyed
        # off the current primary, so they have to be rebuilt too.
        scene_ui = getattr(host, "_scene_ui", None)
        if scene_ui is not None:
            scene_ui.refresh()

    def _apply_device_name(self, address: str, text: str) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        names = dict(self._device_names())
        clean = sanitize_device_name(text)
        if clean:
            names[address] = clean
        else:
            names.pop(address, None)
        host._settings["device_names"] = names
        save_settings(host._settings)
        # Reflect the new name wherever the device is shown.
        self._relabel_device_combo()
        self._sync_last_device_hint()
        self.refresh_mirror_list(host._ble.mirror_addresses())

    def _relabel_device_combo(self) -> None:
        host = self._host
        combo = getattr(host, "device_combo", None)
        if combo is None:
            return
        for index in range(combo.count()):
            address = combo.itemData(index)
            if not address:
                continue
            for device in host._devices:
                if str(device.get("address", "")).strip() == str(address).strip():
                    combo.setItemText(index, self._device_label(device))
                    break

    def start_scan(self) -> bool:
        host = self._host
        if host._is_connected:
            self.show_error(host._tr("error.disconnect_before_scan"))
            return False
        if host._connect_in_progress:
            self.show_error(host._tr("error.wait_inspect") if host._inspect_in_progress
                            else host._tr("error.wait_connect"))
            return False
        if host._inspect_in_progress:
            self.show_error(host._tr("error.wait_inspect"))
            return False
        # A new scan replaces the device list the running check was about, so any
        # result still on its way is no longer answering a question we have.
        host._inspection_token += 1
        host._clear_device_problem()
        host._scan_in_progress = True
        host._devices = []
        host.device_combo.clear()
        host.device_combo.addItem(host._tr("device.choice.scan_placeholder"))
        host.device_status.setText(host._tr("device.status.scanning"))
        self._sync_last_device_hint()
        self._sync_device_onboarding_hint()
        host._sync_connect_buttons()
        host._ble.scan()
        return True

    def connect_or_scan(self) -> None:
        """Use an existing scan result before starting the scanner again.

        The compact status card is the app's one-click connection entry point.
        Once a scan has populated and selected a controller, clicking that card
        again must connect it rather than throwing the result away and scanning
        forever.
        """
        host = self._host
        if host._devices and not host._scan_in_progress:
            self.handle_connect()
            return
        self.start_scan()

    def handle_connect(self) -> None:
        host = self._host
        if host._scan_in_progress:
            self.show_error(host._tr("error.wait_scan"))
            return
        if host._connect_in_progress:
            self.show_error(host._tr("error.wait_connect"))
            return
        index = host.device_combo.currentIndex()
        if not host._devices:
            self.show_error(host._tr("error.find_first"))
            return
        if index < 0 or index >= len(host._devices):
            self.show_error(host._tr("error.select_controller_first"))
            return
        if host._inspect_in_progress:
            self.show_error(host._tr("error.wait_inspect"))
            return
        host._device_problem = ""  # a new attempt clears the last complaint
        device = host._devices[index]
        if device.get("supported", True) is False:
            # Never the ordinary connect path for a device no driver claims:
            # that would mean writing a guessed protocol to unknown hardware.
            host._inspect_in_progress = True
            host._inspection_token += 1
            host._sync_connect_buttons()
            host._ble.inspect_device(
                device["address"], device.get("name", ""), token=host._inspection_token
            )
            return
        host._connect_in_progress = True
        host.device_status.setText(host._tr("device.status.connecting"))
        host._sync_connect_buttons()
        host._ble.connect_to_address(device["address"])

    def start_autoconnect(self) -> None:
        host = self._host
        if host._is_connected or host._scan_in_progress or host._connect_in_progress:
            return
        address = str(host._settings.get("last_device_address", "")).strip()
        if not address:
            return
        if not _is_plausible_ble_address(address):
            host._settings["last_device_address"] = ""
            host._settings["last_device_name"] = ""
            save_settings(host._settings)
            self._sync_last_device_hint()
            return
        name = str(host._settings.get("last_device_name", "")).strip()
        display_name = name or address
        host._devices = [{"name": display_name, "address": address, "rssi": "-"}]
        host.device_combo.clear()
        host.device_combo.addItem(self._device_label(host._devices[0]), address)
        host.device_combo.setCurrentIndex(0)
        host._connect_in_progress = True
        host.device_status.setText(host._tr("device.status.connecting"))
        self._sync_last_device_hint(name=display_name, address=address, autoconnecting=True)
        host._sync_connect_buttons()
        self.log(host._tr("status.autoconnecting", name=display_name, address=address))
        host._ble.connect_to_address(address)

    def populate_devices(self, devices: list[dict[str, Any]]) -> None:
        host = self._host
        host._scan_in_progress = False
        if getattr(self, "_mirror_scan_pending", False):
            # This scan was triggered by "Add strip" while already connected —
            # don't touch the primary connect flow, just add the found mirror.
            self._mirror_scan_pending = False
            self._set_mirror_searching(False)
            self._handle_mirror_scan_result(devices)
            return
        host._devices = devices
        host.device_combo.clear()
        if not devices:
            host.device_combo.addItem(host._tr("device.choice.not_found"))
            host.device_status.setText(host._tr("device.status.not_found"))
            self._sync_last_device_hint()
            self._sync_device_onboarding_hint()
            host._sync_connect_buttons()
            return
        for device in devices:
            host.device_combo.addItem(self._device_label(device), device["address"])
        supported = [device for device in devices if device.get("supported", True)]
        preferred = host._settings.get("last_device_address", "")
        preferred_index = host.device_combo.findData(preferred) if preferred else -1
        host.device_combo.setCurrentIndex(preferred_index if preferred_index >= 0 else 0)
        preferred_device = devices[preferred_index] if preferred_index >= 0 else None
        if preferred_device is not None:
            self._sync_last_device_hint(
                name=str(preferred_device.get("name", "")).strip(),
                address=str(preferred_device.get("address", "")).strip(),
            )
        else:
            self._sync_last_device_hint()
        self._sync_device_onboarding_hint()
        host._sync_connect_buttons()
        # Auto-connect when exactly one *supported* controller is found, even if
        # unrecognised BLE devices are also nearby (there usually are several).
        # Unknown devices are never auto-connected — the user picks one to probe.
        automatic = (
            preferred_device
            if preferred_device is not None and preferred_device.get("supported", True)
            else supported[0] if len(supported) == 1 else None
        )
        if automatic is not None:
            device = automatic
            index = host.device_combo.findData(device["address"])
            if index >= 0:
                host.device_combo.setCurrentIndex(index)
            self.log(host._tr("status.autofound_connecting", name=device["name"], address=device["address"]))
            host._connect_in_progress = True
            host.device_status.setText(host._tr("device.status.connecting"))
            self._sync_last_device_hint(name=str(device.get("name", "")).strip(), address=str(device.get("address", "")).strip(), autoconnecting=True)
            self._sync_device_onboarding_hint()
            host._sync_connect_buttons()
            host._ble.connect_to_address(device["address"])
        elif supported:
            host.device_status.setText(host._tr("device.status.found_many", count=len(supported)))
        else:
            # Only unrecognised devices nearby — invite the user to probe one.
            host.device_status.setText(host._tr("device.status.found_unknown"))

    def on_connected_changed(self, connected: bool, address: str) -> None:
        host = self._host
        was_connected = host._is_connected
        host._is_connected = connected
        host._connect_in_progress = False
        # The strip just went away: stop any running stream so it doesn't keep
        # writing to a dead connection (and so nothing auto-resumes on reconnect).
        if was_connected and not connected:
            stop_all = getattr(host, "stop_all_streams", None)
            if callable(stop_all):
                stop_all()
            # No primary to mirror: stop chasing the extras until it is back.
            self._cancel_all_restores()
        add_mirror = getattr(host, "add_mirror_button", None)
        if add_mirror is not None:
            add_mirror.setEnabled(connected)
        host.device_status.setText(host._tr("device.status.connected") if connected else host._tr("device.status.not_connected"))
        primary_meta = getattr(host, "device_primary_meta", None)
        if primary_meta is not None:
            if connected:
                name = self._device_name_for_address(address) or address or ""
                primary_meta.setText(f"{name}  |  {address}" if name and address and name != address else name)
            else:
                primary_meta.setText(host._tr("device.primary_empty"))
        update_dot = getattr(host, "_update_status_dot", None)
        if callable(update_dot):
            update_dot()
        hint = getattr(host, "device_status_hint", None)
        if hint is not None:
            if connected:
                name = self._device_name_for_address(address) or address or ""
                hint.setText(name)
                wanted = bool(name)
            else:
                hint.setText(host._tr("device.connect_hint"))
                wanted = True
            apply_hint = getattr(host, "_set_status_hint_visible", None)
            if callable(apply_hint):
                apply_hint(wanted)  # compact sidebar may override on a short window
            else:
                hint.setVisible(wanted)
        sync_power_button = getattr(host, "_sync_power_button", None)
        if callable(sync_power_button):
            sync_power_button()
        host._sync_connect_buttons()
        host._refresh_effect_names()
        host._refresh_quick_mode_buttons()
        if connected and _is_plausible_ble_address(address):
            if address and host.device_combo.findData(address) < 0:
                display_name = self._device_name_for_address(address) or address
                device = {"name": display_name, "address": address, "rssi": "-"}
                host._devices = [device]
                host.device_combo.clear()
                host.device_combo.addItem(self._device_label(device), address)
                host.device_combo.setCurrentIndex(0)
            host._settings["last_device_address"] = address
            device_name = self._device_name_for_address(address)
            if device_name and device_name != address:
                host._settings["last_device_name"] = device_name
            self._sync_last_device_hint(name=device_name or address, address=address)
            save_settings(host._settings)
            # The primary is up: bring the remembered extras back (queued, so an
            # unreachable one never delays the window or the primary).
            self._restore_saved_extras(address)
        elif not host._connect_in_progress:
            self._sync_last_device_hint()
        self._sync_device_onboarding_hint()

    def _device_name_for_address(self, address: str) -> str:
        custom = self._device_names().get(str(address).strip(), "")
        if custom:
            return custom
        for device in self._host._devices:
            if str(device.get("address", "")).strip() == address:
                return str(device.get("name", "")).strip()
        return str(self._host._settings.get("last_device_name", "")).strip()

    def _device_label(self, device: dict[str, Any]) -> str:
        address = str(device.get("address", "")).strip()
        # Prefer the user's custom name, else the advertised name.
        name = self._display_name(address, str(device.get("name", "")).strip())
        rssi = str(device.get("rssi", "")).strip()
        parts: list[str] = []
        # Skip the name when it's just the address again (avoids "MAC | MAC").
        if name and name != address:
            parts.append(name)
        if address:
            parts.append(address)
        # Only show RSSI when there's a real reading (not the "-" placeholder).
        if rssi and rssi != "-":
            parts.append(f"RSSI {rssi}")
        label = "  |  ".join(parts) if parts else address
        # Flag controllers we don't recognise yet so the choice is clear.
        if device.get("supported", True) is False:
            label = f"{label}  ·  {self._host._tr('device.unsupported_tag')}"
        return label

    def _sync_last_device_hint(
        self,
        *,
        name: str | None = None,
        address: str | None = None,
        autoconnecting: bool = False,
    ) -> None:
        label = getattr(self._host, "last_device_label", None)
        if label is None:
            return
        host = self._host
        resolved_address = str(address if address is not None else host._settings.get("last_device_address", "")).strip()
        resolved_name = str(name if name is not None else host._settings.get("last_device_name", "")).strip()
        if not resolved_address:
            label.setText(host._tr("device.last.none"))
            self._sync_device_onboarding_hint()
            return
        # When there's no distinct name (it equals the address), use the plain
        # variant so the line isn't "MAC / MAC".
        has_name = bool(resolved_name) and resolved_name != resolved_address
        if autoconnecting:
            key = "device.last.autoconnecting" if has_name else "device.last.autoconnecting_plain"
        else:
            key = "device.last" if has_name else "device.last_plain"
        label.setText(host._tr(key, name=resolved_name, address=resolved_address))
        self._sync_device_onboarding_hint()

    def _sync_device_onboarding_hint(self) -> None:
        label = getattr(self._host, "device_onboarding_label", None)
        if label is None:
            return
        host = self._host
        has_last_device = bool(str(host._settings.get("last_device_address", "")).strip())
        should_show = not any((
            has_last_device,
            host._is_connected,
            host._scan_in_progress,
            host._connect_in_progress,
            bool(host._devices),
        ))
        label.setText(host._tr("device.onboarding_hint"))
        label.setVisible(should_show)

    def show_error(self, message: str) -> None:
        if self._mirror_scan_pending:
            self._mirror_scan_pending = False
            self._set_mirror_searching(False)
        self._host._connect_in_progress = False
        self._host._scan_in_progress = False
        if not self._host._is_connected:
            self._host.device_status.setText(self._host._tr("device.status.not_connected"))
        self._sync_last_device_hint()
        self._host._sync_connect_buttons()
        self._host._ui_feedback.show_error(message)

    def log(self, message: str) -> None:
        self._host._ui_feedback.log(message)

    def add_selected_as_mirror(self) -> None:
        host = self._host
        if not host._is_connected:
            return
        primary = str(host._settings.get("last_device_address", "")).strip()
        mirrors = set(host._ble.mirror_addresses())

        def is_candidate(device: dict[str, Any]) -> bool:
            address = str(device.get("address", "")).strip()
            return bool(address) and bool(device.get("supported", True)) and address != primary and address not in mirrors

        candidates = [device for device in host._devices if is_candidate(device)]
        if not candidates:
            # Nothing else to mirror — guide the user to scan with the other strip on.
            self.show_error(host._tr("device.mirror_none"))
            return
        # Respect an explicit pick in the list; otherwise auto-pick when there's
        # only one other strip, or ask the user to choose when several.
        index = host.device_combo.currentIndex()
        if 0 <= index < len(host._devices) and is_candidate(host._devices[index]):
            chosen = host._devices[index]
        elif len(candidates) == 1:
            chosen = candidates[0]
        else:
            self.show_error(host._tr("device.mirror_pick_first"))
            return
        host._ble.add_mirror_device(str(chosen.get("address", "")).strip())

    def request_add_mirror(self) -> None:
        """Entry point for the 'Add strip' button: add a known second strip, or
        scan for one first (the scan button is disabled while connected)."""
        host = self._host
        if not host._is_connected:
            return
        if self._has_mirror_candidate():
            self.add_selected_as_mirror()
            return
        self.start_mirror_scan()

    def _has_mirror_candidate(self) -> bool:
        host = self._host
        primary = str(host._settings.get("last_device_address", "")).strip()
        mirrors = set(host._ble.mirror_addresses())
        for device in host._devices:
            address = str(device.get("address", "")).strip()
            if address and device.get("supported", True) and address != primary and address not in mirrors:
                return True
        return False

    def start_mirror_scan(self) -> None:
        host = self._host
        if not host._is_connected or host._connect_in_progress or host._scan_in_progress:
            return
        self._mirror_scan_pending = True
        host._scan_in_progress = True
        self._set_mirror_searching(True)
        self.log(host._tr("device.mirror_scanning"))
        host._ble.scan()

    def _handle_mirror_scan_result(self, devices: list[dict[str, Any]]) -> None:
        host = self._host
        host._devices = devices
        host.device_combo.clear()
        for device in devices:
            host.device_combo.addItem(self._device_label(device), device["address"])
        host._sync_connect_buttons()
        self.add_selected_as_mirror()

    def refresh_mirror_list(self, addresses: list[str]) -> None:
        host = self._host
        # Anything live is remembered; the reverse is not true, so the list is
        # "live first, then the remembered ones that aren't up right now".
        self._remember_extras(addresses)
        live = {item.strip().upper() for item in addresses}
        for address in live:
            self._cancel_restore(address)  # it is up; stop the retry schedule
        primary = str(host._settings.get("last_device_address", "")).strip().upper()
        offline = [item for item in self._saved_extras() if item not in live and item != primary]
        rows = [(item, True) for item in addresses] + [(item, False) for item in offline]

        container = getattr(host, "mirror_list_container", None)
        layout = getattr(host, "mirror_list_layout", None)
        if container is None or layout is None:
            return
        # The rows own buttons created through host._button(), which registers
        # them for theme refreshes. Drop them from that registry before
        # deleting, or the next theme switch calls update() on dead C++ objects.
        buttons_registry = getattr(host, "_buttons", None)
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            if buttons_registry is not None:
                for button in widget.findChildren(LiquidButton):
                    if button in buttons_registry:
                        buttons_registry.remove(button)
            widget.deleteLater()
        for address, connected in rows:
            advertised = ""
            for device in host._devices:
                if str(device.get("address", "")).strip() == address:
                    advertised = str(device.get("name", "")).strip()
                    break
            name = self._display_name(address, advertised)
            row = QWidget()
            row.setObjectName("deviceStripRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(host._sz(14), host._sz(9), host._sz(12), host._sz(9))
            row_layout.setSpacing(8)
            info = QVBoxLayout()
            info.setSpacing(host._sz(2))
            label = QLabel(name)
            label.setObjectName("deviceStripTitle")
            state = host._tr("device.strip_connected" if connected else "device.strip_offline")
            address_label = QLabel(f"{address}  |  {state}")
            address_label.setObjectName("deviceStripMeta")
            info.addWidget(label)
            info.addWidget(address_label)
            # Swap roles with the main strip — both links stay up. Only makes
            # sense for a strip that is actually connected.
            promote = host._button(host._tr("device.make_primary"), "ghost")
            promote.setEnabled(connected)
            promote.clicked.connect(lambda _checked=False, a=address, n=name: self.promote_device(a, n))
            rename = host._button(host._tr("device.rename"), "ghost")
            rename.clicked.connect(lambda _checked=False, a=address: self.rename_device(a))
            remove = host._button(host._tr("device.mirror_remove"), "ghost")
            remove.clicked.connect(lambda _checked=False, a=address: self._remove_extra(a))
            row_layout.addLayout(info, 1)
            row_layout.addWidget(promote)
            row_layout.addWidget(rename)
            row_layout.addWidget(remove)
            layout.addWidget(row)
        container.setVisible(bool(rows))
        # Show the "how to add one" hint exactly when the list is empty.
        empty_label = getattr(host, "mirror_empty_label", None)
        if empty_label is not None:
            empty_label.setVisible(not rows)
