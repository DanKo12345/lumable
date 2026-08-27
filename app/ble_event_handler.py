from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from PySide6.QtCore import QObject, QSignalBlocker, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.device_names import device_display_name, sanitize_device_name, validate_extra_addresses
from app.scan_choices import (
    KIND_BACK,
    KIND_DEVICE,
    KIND_SHOW_UNKNOWN,
    address_of,
    back_choice,
    device_choice,
    find_device,
    heading_choice,
    kind_of,
    normalize_address,
    notice_choice,
    show_unknown_choice,
)
from app.scan_ranking import GROUP_SUPPORTED, GROUP_TRUSTED, GROUP_UNKNOWN, group_of, rank
from app.signal_quality import measure
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
        self._scan_auto_connect = True
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

    # Which address the person is in the middle of choosing, if any. Empty
    # unless a deliberate act is in flight; see :meth:`_store_trusted`.
    _pending_trusted_primary = ""
    _pending_trusted_mirror = ""
    # Whether the picker is currently showing the devices no driver claims, and
    # which strip to put back when it stops.
    _showing_unknown = False
    _selected_before_unknown = ""

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
        self._select_primary_in_combo(address, display)
        self._sync_last_device_hint(name=display, address=address)
        self._sync_sidebar_connection_hint(display)
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
            device = find_device(host._devices, address_of(combo.itemData(index)))
            if device is not None:
                combo.setItemText(index, self._device_label(device))

    def _select_primary_in_combo(self, address: str, name: str = "") -> None:
        """Make the discovery field agree with the connected primary.

        The field also contains scan candidates, including extra strips. Merely
        relabelling those entries leaves whichever candidate happened to be
        selected looking like the active controller after a role swap.
        """
        host = self._host
        combo = getattr(host, "device_combo", None)
        address = str(address).strip()
        if combo is None or not address:
            return
        index = self._index_of_address(address)
        if index < 0:
            device = next(
                (
                    item
                    for item in host._devices
                    if str(item.get("address", "")).strip() == address
                ),
                None,
            )
            if device is None:
                device = {
                    "name": str(name or address).strip(),
                    "address": address,
                    "rssi": "-",
                }
                host._devices.append(device)
            with self._quiet_picker():
                combo.addItem(self._device_label(device), device_choice(address))
            index = self._index_of_address(address)
        if index >= 0:
            with self._quiet_picker():
                combo.setCurrentIndex(index)
        host._sync_connect_buttons()

    def start_scan(self, _checked: bool = False, *, auto_connect: bool = True) -> bool:
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
        self._scan_auto_connect = bool(auto_connect)
        # A new search answers the question the last offer was about.
        host._offer_report = False
        host._scan_in_progress = True
        host._devices = []
        with self._quiet_picker():
            host.device_combo.clear()
            host.device_combo.addItem(host._tr("device.choice.scan_placeholder"), notice_choice())
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

    def _index_of_address(self, address: str) -> int:
        """Where the row for this controller sits, or -1."""
        combo = getattr(self._host, "device_combo", None)
        wanted = normalize_address(address)
        if combo is None or not wanted:
            return -1
        for index in range(combo.count()):
            if address_of(combo.itemData(index)) == wanted:
                return index
        return -1

    def _first_device_index(self) -> int:
        """The first row that stands for a strip, or 0 if there is none.

        What "the top of the list" means once the list has headings in it. Row
        zero is a heading whenever both groups are present, and a picker resting
        on a heading answers Connect with "choose a controller" — an instruction
        to do the thing the person just did.
        """
        combo = getattr(self._host, "device_combo", None)
        if combo is None:
            return 0
        for index in range(combo.count()):
            if kind_of(combo.itemData(index)) == KIND_DEVICE:
                return index
        return 0

    def _selected_scan_device(self) -> dict | None:
        """The controller the highlighted row stands for, or ``None``.

        The single place this question is answered. It is asked of the row, not
        of its position: the field also holds rows that are not controllers at
        all, and a position that lines up with the list today lines up with a
        different controller as soon as one of those appears above it.
        """
        combo = getattr(self._host, "device_combo", None)
        if combo is None:
            return None
        return find_device(self._host._devices, address_of(combo.currentData()))

    def handle_connect(self) -> None:
        host = self._host
        if host._scan_in_progress:
            self.show_error(host._tr("error.wait_scan"))
            return
        if host._connect_in_progress:
            self.show_error(host._tr("error.wait_connect"))
            return
        if not host._devices:
            self.show_error(host._tr("error.find_first"))
            return
        device = self._selected_scan_device()
        if device is None:
            self.show_error(host._tr("error.select_controller_first"))
            return
        if host._inspect_in_progress:
            self.show_error(host._tr("error.wait_inspect"))
            return
        host._device_problem = ""  # a new attempt clears the last complaint
        # A new attempt replaces whatever the last one was waiting for, so a
        # result that arrives late for an abandoned address cannot be taken as
        # the answer to this one.
        self._clear_pending_trust()
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
        # Set immediately before the attempt, and only here: this is the one
        # path that begins with somebody choosing a strip from the list.
        self._pending_trusted_primary = normalize_address(device["address"])
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
            # Cleared before anything else is asked. Something that cannot be an
            # address is rubbish in the file whoever put it there, and leaving
            # it because it also happens to be untrusted would keep it forever.
            host._settings["last_device_address"] = ""
            host._settings["last_device_name"] = ""
            save_settings(host._settings)
            self._sync_last_device_hint()
            return
        if not self._is_trusted(address):
            # Remembered is not chosen. The address here is whatever was
            # connected last, and this app connects on its own — so on a day
            # when a strip was switched off, what got remembered may be the
            # neighbour's. Reaching for it unprompted at every launch is the
            # difference between a convenience and lighting someone else's room.
            return
        name = str(host._settings.get("last_device_name", "")).strip()
        display_name = name or address
        host._devices = [{"name": display_name, "address": address, "rssi": "-"}]
        with self._quiet_picker():
            host.device_combo.clear()
            host.device_combo.addItem(self._device_label(host._devices[0]), device_choice(address))
            host.device_combo.setCurrentIndex(0)
        host._connect_in_progress = True
        host.device_status.setText(host._tr("device.status.connecting"))
        self._sync_last_device_hint(name=display_name, address=address, autoconnecting=True)
        host._sync_connect_buttons()
        self.log(host._tr("status.autoconnecting", name=display_name, address=address))
        host._ble.connect_to_address(address)

    @contextmanager
    def _quiet_picker(self):
        """Rebuild the picker without it reporting each row as a decision.

        ``currentIndexChanged`` is connected straight through, and the very
        first row added to an empty box becomes the current one. Adding "Back"
        as the first row of the unrecognised list therefore announced that Back
        had been chosen — while the list was still being built — and the rest of
        the rows landed in a box that was already being rebuilt underneath them.

        A stand-in that is not a real widget has no signals to silence, and says
        so by not being a ``QObject``.
        """
        combo = getattr(self._host, "device_combo", None)
        if not isinstance(combo, QObject):
            yield combo
            return
        blocker = QSignalBlocker(combo)
        try:
            yield combo
        finally:
            blocker.unblock()

    def _clear_pending_trust(self) -> None:
        """Forget which address a person was in the middle of choosing.

        Called on every ending there is — success, refusal, cancellation, a new
        attempt, and the end of a compatibility check. A pending address left
        behind is a promise waiting for whichever connection happens next, and
        the connection that happens next may be an automatic one to a strip
        nobody chose.
        """
        self._pending_trusted_primary = ""
        self._pending_trusted_mirror = ""

    def _store_trusted(self, address: str) -> bool:
        """Record that this person chose this strip. Returns whether it changed.

        The single door. Trust is granted by an act — pressing Connect, pressing
        Add strip — and never by an address merely turning up connected, because
        the app opens a connection on its own and the strip it finds when yours
        is switched off is not yours.
        """
        host = self._host
        wanted = normalize_address(address)
        if not wanted or not isinstance(host._settings, dict):
            return False
        trusted = validate_extra_addresses(host._settings.get("trusted_device_addresses", []))
        if wanted in trusted:
            return False
        trusted.append(wanted)
        host._settings["trusted_device_addresses"] = trusted
        save_settings(host._settings)
        return True

    def _is_trusted(self, address: str) -> bool:
        return normalize_address(address) in set(self._trusted_addresses())

    def _trusted_addresses(self) -> list[str]:
        settings = self._host._settings
        if not isinstance(settings, dict):
            return []
        return validate_extra_addresses(settings.get("trusted_device_addresses", []))

    def _ranked(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Scan results in the order they should be offered.

        Ordered here rather than where the scan happens, because this is the
        first place that knows which strips this person has actually chosen.
        The adapter can only tell a recognised controller from an unrecognised
        one; it has no idea which of them is yours.
        """
        return [ranked.device for ranked in rank(devices, trusted=self._trusted_addresses())]

    def _fill_strip_rows(self) -> None:
        """The ordinary list: the strips, under the names of their groups.

        Unrecognised devices are one row rather than a dozen. They are almost
        never what somebody is looking for, and a picker whose top half is a
        neighbour's headphones is a picker people stop reading.
        """
        host = self._host
        combo = host.device_combo
        combo.clear()
        trusted = self._trusted_addresses()
        grouped: dict[str, list[dict[str, Any]]] = {
            GROUP_TRUSTED: [],
            GROUP_SUPPORTED: [],
            GROUP_UNKNOWN: [],
        }
        for device in host._devices:
            grouped[group_of(device, trusted)].append(device)
        mine = grouped[GROUP_TRUSTED]
        others = grouped[GROUP_SUPPORTED]
        unknown = grouped[GROUP_UNKNOWN]
        for heading, group in (
            ("device.group.trusted", mine),
            ("device.group.nearby", others),
        ):
            if not group:
                continue
            # A heading only earns its row when both groups exist; on its own it
            # is a label for the only thing on screen.
            if mine and others:
                combo.addItem(host._tr(heading), heading_choice())
            for device in group:
                combo.addItem(self._device_label(device), device_choice(device["address"]))
        if unknown:
            combo.addItem(
                host._tr("device.group.unknown", count=len(unknown)), show_unknown_choice()
            )

    def _fill_unknown_rows(self) -> None:
        """The devices no driver claims, with the way back at the top.

        They keep everything they had: a name, an address, how well they were
        heard, and the action that reads their services — which is the only
        route by which a driver for one of them ever gets written.
        """
        host = self._host
        combo = host.device_combo
        combo.clear()
        combo.addItem(host._tr("device.group.back"), back_choice())
        trusted = self._trusted_addresses()
        for device in host._devices:
            # By group, not by recognition: a strip this person has used for
            # months stays under "My strips" on a day when its advertisement
            # arrives too thin for a driver to claim it, rather than being
            # filed away with the neighbours' headphones.
            if group_of(device, trusted) == GROUP_UNKNOWN:
                combo.addItem(self._device_label(device), device_choice(device["address"]))

    def _show_unknown_devices(self, showing: bool) -> None:
        """Swap the picker between the strips and the rest.

        The strip that was highlighted is remembered and put back, because
        looking at what else is in the room is not a change of mind about which
        strip to connect to.
        """
        host = self._host
        with self._quiet_picker():
            if showing:
                self._selected_before_unknown = address_of(host.device_combo.currentData())
                self._showing_unknown = True
                self._fill_unknown_rows()
                # The first device, not the way out. Leaving "Back" selected
                # means choosing it changes nothing — a combo box reports a
                # *change* of row, and that row was already the current one, so
                # the way out would have been unreachable by clicking it.
                combo_index = next(
                    (
                        index
                        for index in range(host.device_combo.count())
                        if kind_of(host.device_combo.itemData(index)) == KIND_DEVICE
                    ),
                    0,
                )
            else:
                self._showing_unknown = False
                self._fill_strip_rows()
                restored = self._index_of_address(self._selected_before_unknown)
                # The strip that was highlighted may be gone: a scan can have
                # replaced the list while the other devices were open.
                combo_index = restored if restored >= 0 else self._first_device_index()
            # Inside the same silence: setting the index is the other half of
            # the rebuild, not a person choosing something.
            host.device_combo.setCurrentIndex(combo_index)
        host._sync_connect_buttons()

    def on_choice_activated(self) -> None:
        """A row was picked. Only some rows are things to pick.

        Called for every change of selection, so it must be quiet about the
        ordinary case: a strip being highlighted is not an event, it is the
        picker doing its job.
        """
        combo = getattr(self._host, "device_combo", None)
        if combo is None:
            return
        kind = kind_of(combo.currentData())
        if kind == KIND_SHOW_UNKNOWN:
            self._show_unknown_devices(True)
        elif kind == KIND_BACK:
            self._show_unknown_devices(False)

    def populate_devices(self, devices: list[dict[str, Any]]) -> None:
        host = self._host
        auto_connect = self._scan_auto_connect
        self._scan_auto_connect = True
        host._scan_in_progress = False
        if getattr(self, "_mirror_scan_pending", False):
            # This scan was triggered by "Add strip" while already connected —
            # don't touch the primary connect flow, just add the found mirror.
            self._mirror_scan_pending = False
            self._set_mirror_searching(False)
            self._handle_mirror_scan_result(devices)
            return
        devices = self._ranked(devices)
        host._devices = devices
        self._showing_unknown = False
        # Silent for the whole rebuild. Every row added to an emptied box can
        # become the current one, and some rows *mean* something when chosen —
        # a scan that found only unrecognised devices puts one of those first,
        # so filling the list announced a choice nobody made, halfway through
        # filling it. It came out right by the accident of toggling twice.
        with self._quiet_picker():
            host.device_combo.clear()
            if not devices:
                host.device_combo.addItem(host._tr("device.choice.not_found"), notice_choice())
                host.device_status.setText(host._tr("device.status.not_found"))
                host._offer_report = True
                self._sync_last_device_hint()
                self._sync_device_onboarding_hint()
                host._sync_connect_buttons()
                return
            self._fill_strip_rows()
            preferred = host._settings.get("last_device_address", "")
            preferred_index = self._index_of_address(preferred)
            host.device_combo.setCurrentIndex(
                preferred_index if preferred_index >= 0 else self._first_device_index()
            )
        supported = [device for device in devices if device.get("supported", True)]
        preferred_device = find_device(devices, preferred) if preferred_index >= 0 else None
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
        # A scan with several supported controllers is a choice, even when one
        # of them was used last time. Startup autoconnect already handles the
        # remembered address directly; reconnecting it here would make a manual
        # search ignore the closest-first list before the user can choose.
        # Only a strip already chosen is opened without being asked for. One
        # supported controller in range is not evidence that it is yours: it is
        # evidence that yours is the only one switched on, or that it is not.
        automatic = (
            supported[0]
            if auto_connect and len(supported) == 1 and self._is_trusted(supported[0].get("address"))
            else None
        )
        if automatic is not None:
            device = automatic
            index = self._index_of_address(device["address"])
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
            # Only unrecognised devices nearby — invite the user to probe one,
            # and offer the report, which is the other half of that invitation:
            # a check tells them their device is not supported, and the report
            # is the thing that can change that.
            host.device_status.setText(host._tr("device.status.found_unknown"))
            host._offer_report = True
            host._sync_connect_buttons()

    def on_connected_changed(self, connected: bool, address: str) -> None:
        host = self._host
        was_connected = host._is_connected
        host._is_connected = connected
        host._connect_in_progress = False
        # The strip just went away: stop any running stream so it doesn't keep
        # writing to a dead connection (and so nothing auto-resumes on reconnect).
        if was_connected and not connected:
            lost = getattr(host, "note_link_lost", None)
            if callable(lost):
                lost()
            # No primary to mirror: stop chasing the extras until it is back.
            self._cancel_all_restores()
        elif connected and not was_connected:
            # A run that was on its way to a strip may resume — but not with
            # anything it was holding when the link broke.
            back = getattr(host, "note_link_back", None)
            if callable(back):
                back()
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
        name = self._device_name_for_address(address) or address or "" if connected else ""
        self._sync_sidebar_connection_hint(name)
        sync_power_button = getattr(host, "_sync_power_button", None)
        if callable(sync_power_button):
            sync_power_button()
        host._sync_connect_buttons()
        host._refresh_effect_names()
        host._refresh_quick_mode_buttons()
        if connected and _is_plausible_ble_address(address):
            # The pending address is consumed here whatever happens next, so a
            # result that belongs to an attempt already abandoned cannot grant
            # trust to the address that replaced it.
            chosen = self._pending_trusted_primary
            self._clear_pending_trust()
            if chosen and chosen == normalize_address(address):
                self._store_trusted(address)
            self._select_primary_in_combo(
                address,
                self._device_name_for_address(address) or address,
            )
            if self._is_trusted(address):
                host._settings["last_device_address"] = address
                device_name = self._device_name_for_address(address)
                if device_name and device_name != address:
                    host._settings["last_device_name"] = device_name
                self._sync_last_device_hint(name=device_name or address, address=address)
                save_settings(host._settings)
            else:
                # Connected, and shown as connected, but not written down. An
                # address arriving here has not necessarily been chosen — a
                # reconnect, a restore or an automatic attempt all land on this
                # line — and remembering it would make the next launch reach for
                # it unprompted.
                self._sync_last_device_hint()
            # The primary is up: bring the remembered extras back (queued, so an
            # unreachable one never delays the window or the primary).
            self._restore_saved_extras(address)
        elif not host._connect_in_progress:
            self._sync_last_device_hint()
        self._sync_device_onboarding_hint()

    def _sync_sidebar_connection_hint(self, name: str) -> None:
        """Keep the sidebar's connected device aligned with the live primary."""
        host = self._host
        hint = getattr(host, "device_status_hint", None)
        if hint is None:
            return
        text = str(name).strip() if host._is_connected else host._tr("device.connect_hint")
        hint.setText(text)
        wanted = bool(text) if host._is_connected else True
        apply_hint = getattr(host, "_set_status_hint_visible", None)
        if callable(apply_hint):
            apply_hint(wanted)  # compact sidebar may override on a short window
        else:
            hint.setVisible(wanted)

    def _device_name_for_address(self, address: str) -> str:
        custom = self._device_names().get(str(address).strip(), "")
        if custom:
            return custom
        for device in self._host._devices:
            if str(device.get("address", "")).strip() == address:
                return str(device.get("name", "")).strip()
        return str(self._host._settings.get("last_device_name", "")).strip()

    def _signal_text(self, device: dict[str, Any]) -> str:
        """How this device's signal reads, in words. Empty if nothing was heard.

        Deliberately says nothing about distance. Transmit power differs between
        controllers and sensitivity between adapters, so the same room gives
        different figures on different machines — "strong signal" is defensible
        where "nearest" is not.
        """
        quality = measure(device.get("rssi_samples"))
        if quality.median is None and not device.get("rssi_samples"):
            return ""
        return self._host._tr(f"device.signal.{quality.level}")

    def _device_label(self, device: dict[str, Any]) -> str:
        address = str(device.get("address", "")).strip()
        # Prefer the user's custom name, else the advertised name.
        name = self._display_name(address, str(device.get("name", "")).strip())
        parts: list[str] = []
        # Skip the name when it's just the address again (avoids "MAC | MAC").
        if name and name != address:
            parts.append(name)
        if address:
            parts.append(address)
        # Words, not decibels. "RSSI -67" is a number almost nobody can act on,
        # and the two useful facts inside it — how good the signal is, and
        # whether we heard enough to say — are what the words carry. The figure
        # itself is kept, in the diagnostics report, where somebody debugging
        # wants it.
        signal = self._signal_text(device)
        if signal:
            parts.append(signal)
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
        self._scan_auto_connect = True
        # A refusal or a cancellation ends the attempt as surely as a success.
        self._clear_pending_trust()
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
        primary = str(host._settings.get("last_device_address", "")).strip().upper()
        mirrors = {str(item).strip().upper() for item in host._ble.mirror_addresses()}

        def is_candidate(device: dict[str, Any]) -> bool:
            address = str(device.get("address", "")).strip().upper()
            return bool(address) and bool(device.get("supported", True)) and address != primary and address not in mirrors

        candidates = [device for device in host._devices if is_candidate(device)]
        if not candidates:
            # Nothing else to mirror — guide the user to scan with the other strip on.
            self.show_error(host._tr("device.mirror_none"))
            return
        # Respect an explicit pick in the list; otherwise auto-pick when there's
        # only one other strip, or ask the user to choose when several.
        selected = self._selected_scan_device()
        if selected is not None and is_candidate(selected):
            chosen = selected
        elif len(candidates) == 1:
            chosen = candidates[0]
        else:
            self.show_error(host._tr("device.mirror_pick_first"))
            return
        address = str(chosen.get("address", "")).strip()
        self._pending_trusted_mirror = normalize_address(address)
        host._ble.add_mirror_device(address)

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
        primary = str(host._settings.get("last_device_address", "")).strip().upper()
        mirrors = {str(item).strip().upper() for item in host._ble.mirror_addresses()}
        for device in host._devices:
            address = str(device.get("address", "")).strip().upper()
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
        devices = self._ranked(devices)
        host._devices = devices
        with self._quiet_picker():
            host.device_combo.clear()
            for device in devices:
                host.device_combo.addItem(self._device_label(device), device_choice(device["address"]))
        host._sync_connect_buttons()
        # A mirror scan temporarily borrows the discovery field. If it found
        # nothing new (including when it only rediscovered an existing extra),
        # put the connected primary back instead of leaving the field empty or
        # pointing at a strip that is already listed below.
        if not self._has_mirror_candidate():
            primary = str(host._settings.get("last_device_address", "")).strip()
            self._select_primary_in_combo(
                primary,
                self._device_name_for_address(primary) or primary,
            )
        self.add_selected_as_mirror()

    def refresh_mirror_list(self, addresses: list[str]) -> None:
        host = self._host
        # Anything live is remembered; the reverse is not true, so the list is
        # "live first, then the remembered ones that aren't up right now".
        self._remember_extras(addresses)
        live = {item.strip().upper() for item in addresses}
        # Granted only once the strip is really there. A press that ended in an
        # error adds nothing, and the silent restore of a saved extra adds
        # nothing either — that one was already chosen, on the day it was added.
        wanted = self._pending_trusted_mirror
        if wanted and wanted in live:
            self._pending_trusted_mirror = ""
            self._store_trusted(wanted)
        for address in live:
            self._cancel_restore(address)  # it is up; stop the retry schedule
        primary = str(host._settings.get("last_device_address", "")).strip().upper()
        if getattr(host, "_is_connected", False) and primary:
            self._select_primary_in_combo(
                primary,
                self._device_name_for_address(primary) or primary,
            )
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
