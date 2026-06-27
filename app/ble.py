from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterable
from concurrent.futures import CancelledError

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from PySide6.QtCore import QObject, Signal

from app.ble_drivers import EFFECTS, detect_connected_driver, detect_scan_driver
from app.ble_drivers.base import LedBleDriver, clamp
from app.localization import localization_manager

CONNECT_TIMEOUT_SECONDS = 10.0
FIND_DEVICE_TIMEOUT_SECONDS = 8.0
WRITE_TIMEOUT_SECONDS = 3.0
WRITE_RETRY_ATTEMPTS = 2
WRITE_RETRY_DELAY_SECONDS = 0.12
# Reconnect with escalating back-off instead of giving up after a few seconds,
# so a strip that was switched off at the wall for a while still re-pairs when
# it comes back. Delays (seconds) per attempt; the last value repeats.
RECONNECT_ATTEMPTS = 12
RECONNECT_BACKOFF_SECONDS = (2.0, 3.0, 5.0, 8.0, 12.0, 20.0)


class ProtocolCompatibilityError(RuntimeError):
    pass


class ConnectionLostError(RuntimeError):
    pass


BLE_OPERATION_ERRORS = (asyncio.TimeoutError, BleakError, ConnectionLostError, OSError, ProtocolCompatibilityError, RuntimeError)
DRIVER_CAPABILITY_ERRORS = (AttributeError, LookupError, NotImplementedError, TypeError, ValueError)

# Name fragments that strongly suggest a cheap BLE LED controller, used to flag
# unrecognised-but-plausible devices during a scan so the user can report them.
_LED_NAME_HINTS = (
    "led", "rgb", "ble", "strip", "light", "lamp", "neon", "glow",
    "triones", "ledble", "lednet", "elk", "melk", "magic", "banlanx",
    "ihoment", "govee", "minger", "wled", "sp1", "sp6", "qhm", "isp",
)


def _looks_like_led_controller(name: str, service_uuids: Iterable[str]) -> bool:
    """Heuristic: does this unrecognised device look like an LED controller?

    Matches on common name fragments or the 0xFFxx vendor service range these
    clones use, so we surface likely controllers without listing every phone.
    """
    lowered = (name or "").strip().lower()
    if lowered and any(hint in lowered for hint in _LED_NAME_HINTS):
        return True
    for uuid in service_uuids:
        text = str(uuid).lower()
        if text.startswith("0000ff") or (len(text) == 4 and text.startswith("ff")):
            return True
    return False


class BleController(QObject):
    status_changed = Signal(str)
    devices_discovered = Signal(list)
    connected_changed = Signal(bool, str)
    error_occurred = Signal(str)
    shutdown_finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._client: BleakClient | None = None
        self._device: BLEDevice | None = None
        self._driver: LedBleDriver | None = None
        self._scan_driver_hints: dict[str, str] = {}
        self._write_characteristic: BleakGATTCharacteristic | None = None
        self._write_characteristics: list[BleakGATTCharacteristic] = []
        self._last_red = 88
        self._last_green = 182
        self._last_blue = 255
        self._last_brightness = 100
        self._current_effect_code = 0
        # Tracks whether the user wants the strip on, so a scene can be restored
        # after an unexpected reconnect (e.g. the strip was power-cycled).
        self._desired_power_on = False
        self._shutdown_started = False
        self._manual_disconnect_requested = False
        self._operation_lock = asyncio.Lock()
        self._preferred_payload_indices: dict[tuple[str, tuple[tuple[int, ...], ...]], int] = {}
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_address = ""
        self._ble_history: list[dict[str, str]] = []
        self._last_ble_error = ""
        self._stream_busy = False
        # Unrecognised-but-plausible LED controllers seen in the last scan, kept
        # so the diagnostics report can list them for adding driver support.
        self._unknown_devices: list[dict[str, str]] = []

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            self._drain_pending_tasks()
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    def shutdown(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        if self._client is not None:
            future = asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)
            future.result(timeout=5)
        self._loop.call_soon_threadsafe(self._loop.stop)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)

    def shutdown_async(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True

        if not self._loop.is_running():
            self.shutdown_finished.emit()
            return

        if self._client is None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self.shutdown_finished.emit()
            return

        future = asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)

        def _finish(_future) -> None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self.shutdown_finished.emit()

        future.add_done_callback(_finish)

    def _submit(self, coroutine) -> None:
        if self._shutdown_started or not self._loop.is_running():
            coroutine.close()
            return

        wrapper = self._run_serialized(coroutine)
        try:
            future = asyncio.run_coroutine_threadsafe(wrapper, self._loop)
        except RuntimeError:
            wrapper.close()
            coroutine.close()
            return
        future.add_done_callback(self._handle_future)

    async def _run_serialized(self, coroutine):
        coroutine_started = False
        try:
            async with self._operation_lock:
                coroutine_started = True
                return await coroutine
        finally:
            if not coroutine_started:
                coroutine.close()

    def _handle_future(self, future) -> None:
        try:
            future.result()
        except CancelledError:
            return
        except BLE_OPERATION_ERRORS as exc:  # pragma: no cover
            message = self._exception_message(exc)
            self._set_last_ble_exception(exc)
            self.error_occurred.emit(message)
            self.status_changed.emit(f"BLE error: {message}")
        except Exception as exc:  # pragma: no cover
            message = self._exception_message(exc)
            self._set_last_ble_exception(exc)
            self.error_occurred.emit(message)
            self.status_changed.emit(f"BLE error: {message}")

    @staticmethod
    def _exception_message(exc: Exception) -> str:
        message = str(exc).strip()
        if message:
            return message
        return localization_manager.t("error.ble_unknown_detail", error_type=exc.__class__.__name__)

    def _drain_pending_tasks(self) -> None:
        pending = [task for task in asyncio.all_tasks(self._loop) if not task.done()]
        if not pending:
            return
        for task in pending:
            task.cancel()
        self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

    def scan(self) -> None:
        self.status_changed.emit(localization_manager.status_ble_event("scan_start"))
        self._submit(self._scan())

    def connect_to_address(self, address: str) -> None:
        if self._client is not None and self._client.is_connected and self._device is not None and self._device.address == address:
            self.status_changed.emit(localization_manager.status_ble_event("already_connected", address=address))
            self.connected_changed.emit(True, address)
            return
        self._manual_disconnect_requested = False
        self._cancel_reconnect()
        self.status_changed.emit(localization_manager.status_ble_event("connecting", address=address))
        self._submit(self._connect(address))

    def disconnect(self) -> None:
        self._manual_disconnect_requested = True
        self._cancel_reconnect()
        self._submit(self._disconnect())

    def set_power(self, enabled: bool, *, restore_state: bool = True) -> None:
        self._desired_power_on = bool(enabled)
        self._submit(self._set_power(enabled, restore_state=restore_state))

    def set_color(self, red: int, green: int, blue: int) -> None:
        self._last_red = clamp(red, 0, 255)
        self._last_green = clamp(green, 0, 255)
        self._last_blue = clamp(blue, 0, 255)
        self._desired_power_on = True
        self._submit(self._set_color(red, green, blue))

    def set_color_stream(self, red: int, green: int, blue: int) -> None:
        """Fast colour-only write for live streaming (ambient sync, etc.).

        Drops the frame if a previous stream write is still in flight, so the
        slow BLE link never backs up; writes colour only (no brightness, no
        forced delay); and is logged quietly to avoid flooding the session log.
        """
        if self._stream_busy:
            return
        self._last_red = clamp(red, 0, 255)
        self._last_green = clamp(green, 0, 255)
        self._last_blue = clamp(blue, 0, 255)
        self._desired_power_on = True
        self._stream_busy = True
        self._submit_stream(self._set_color_stream(self._last_red, self._last_green, self._last_blue))

    def _submit_stream(self, coroutine) -> None:
        if self._shutdown_started or not self._loop.is_running():
            coroutine.close()
            self._stream_busy = False
            return
        wrapper = self._run_serialized(coroutine)
        try:
            future = asyncio.run_coroutine_threadsafe(wrapper, self._loop)
        except RuntimeError:
            wrapper.close()
            coroutine.close()
            self._stream_busy = False
            return

        def _done(completed) -> None:
            self._stream_busy = False
            try:
                completed.result()
            except Exception:
                # Streaming frames are best-effort; never spam logs/errors.
                pass

        future.add_done_callback(_done)

    def set_brightness(self, value: int) -> None:
        self._last_brightness = clamp(value, 0, 100)
        self._desired_power_on = True
        if self._driver is not None:
            self._driver.remember_brightness(self._last_brightness)
        self._submit(self._set_brightness(value))

    def set_static_color(self, red: int, green: int, blue: int, brightness: int) -> None:
        self._last_red = clamp(red, 0, 255)
        self._last_green = clamp(green, 0, 255)
        self._last_blue = clamp(blue, 0, 255)
        self._last_brightness = clamp(brightness, 0, 100)
        self._desired_power_on = True
        if self._driver is not None:
            self._driver.remember_brightness(self._last_brightness)
        self._submit(
            self._set_static_color(
                self._last_red,
                self._last_green,
                self._last_blue,
                self._last_brightness,
            )
        )

    def set_effect(self, code: int) -> None:
        self._desired_power_on = True
        self._submit(self._set_effect(code))

    def set_effect_with_speed(self, code: int, speed: int) -> None:
        self._desired_power_on = True
        self._submit(self._set_effect_with_speed(code, speed))

    def set_effect_speed(self, value: int) -> None:
        self._submit(self._set_effect_speed(value))

    def supports_effect_code(self, code: int) -> bool:
        if int(code) == 0:
            return True
        if self._driver is None:
            return True
        return self._driver.effect_payload(int(code)) is not None

    def supports_effect_speed(self) -> bool:
        if self._driver is None:
            return True
        return self._driver.supports_effect_speed()

    def effect_presets(self):
        if self._driver is not None and self._driver.effects:
            return self._driver.effects
        return EFFECTS

    def diagnostics_snapshot(self) -> dict:
        driver = self._driver
        device = self._device
        selected = self._write_characteristic
        candidates = self._write_characteristics or ([selected] if selected is not None else [])
        return {
            "connected": bool(self._client is not None and self._client.is_connected),
            "device": {
                "name": (device.name or "").strip() if device is not None else "",
                "address": device.address if device is not None else "",
                "rssi": getattr(device, "rssi", "") if device is not None else "",
            },
            "driver": {
                "id": driver.id if driver is not None else "",
                "name": driver.display_name if driver is not None else "",
                "transport": getattr(driver, "transport", "") if driver is not None else "",
                "notes": getattr(driver, "protocol_notes", "") if driver is not None else "",
            },
            "write": {
                "selected_uuid": str(selected.uuid) if selected is not None else "",
                "selected_properties": list(selected.properties) if selected is not None else [],
                "candidates": [
                    {
                        "uuid": str(characteristic.uuid),
                        "properties": list(characteristic.properties),
                    }
                    for characteristic in candidates
                    if characteristic is not None
                ],
            },
            "commands": self._driver_command_support(),
            "history": {
                "last_error": getattr(self, "_last_ble_error", ""),
                "last_command": self._last_history_item("command"),
                "events": list(getattr(self, "_ble_history", [])),
            },
            "nearby_unknown": list(getattr(self, "_unknown_devices", [])),
        }

    def _record_ble_history(self, event: str, **details: object) -> None:
        history = getattr(self, "_ble_history", None)
        if history is None:
            self._ble_history = []
            history = self._ble_history
        clean_item = {"event": str(event)}
        for key, value in details.items():
            clean_item[str(key)] = str(value).strip()
        history.append(clean_item)
        del history[:-40]

    def _last_history_item(self, event: str) -> dict[str, str]:
        for item in reversed(getattr(self, "_ble_history", [])):
            if item.get("event") == event:
                return dict(item)
        return {}

    def _set_last_ble_error(self, message: str) -> None:
        clean_message = self._exception_message(RuntimeError(message)) if message else ""
        self._last_ble_error = clean_message
        if clean_message:
            self._record_ble_history("error", message=clean_message)

    def _set_last_ble_exception(self, exc: Exception) -> None:
        clean_message = self._exception_message(exc)
        self._last_ble_error = clean_message
        if clean_message:
            self._record_ble_history("error", message=clean_message, error_type=exc.__class__.__name__)

    def _clear_last_ble_error(self) -> None:
        self._last_ble_error = ""

    def _driver_command_support(self) -> dict:
        driver = self._driver
        if driver is None:
            return {
                "power": False,
                "color": False,
                "brightness": False,
                "effects": 0,
                "speed": False,
            }
        brightness = False
        speed = False
        try:
            brightness = bool(driver.brightness_payloads(50))
        except DRIVER_CAPABILITY_ERRORS:
            brightness = False
        try:
            speed = driver.supports_effect_speed()
        except DRIVER_CAPABILITY_ERRORS:
            speed = False
        return {
            "power": True,
            "color": True,
            "brightness": brightness,
            "effects": len([effect for effect in driver.effects if effect.code != 0]),
            "speed": speed,
        }

    async def _scan(self) -> None:
        devices = await BleakScanner.discover(timeout=5.0, return_adv=True)
        results: list[dict[str, str]] = []
        unknown: list[dict[str, str]] = []
        self._scan_driver_hints.clear()
        for _, (device, advertisement) in devices.items():
            name = device.name or advertisement.local_name or "Unknown BLE Device"
            service_uuids = [uuid.lower() for uuid in (advertisement.service_uuids or [])]
            driver = detect_scan_driver(name, service_uuids)
            if driver is not None:
                self._scan_driver_hints[device.address] = driver.id
                results.append(
                    {
                        "name": name,
                        "address": device.address,
                        "rssi": str(advertisement.rssi),
                        "driver": driver.display_name,
                        "supported": True,
                    }
                )
            elif _looks_like_led_controller(name, service_uuids):
                unknown.append(
                    {
                        "name": name,
                        "address": device.address,
                        "rssi": str(advertisement.rssi),
                        "services": ", ".join(service_uuids) or "-",
                        "supported": False,
                    }
                )

        self._unknown_devices = unknown[:12]
        # Surface unknown-but-plausible controllers in the same list so the user
        # can pick one and try to connect; a failed connect yields a full GATT
        # diagnostic that makes adding a driver possible.
        self.devices_discovered.emit(results + self._unknown_devices)
        if results:
            self.status_changed.emit(localization_manager.status_ble_event("scan_finished_found", count=len(results)))
        elif self._unknown_devices:
            self.status_changed.emit(
                localization_manager.status_ble_event("scan_finished_unknown", count=len(self._unknown_devices))
            )
        else:
            self.status_changed.emit(localization_manager.status_ble_event("scan_finished_none"))

    async def _set_power(self, enabled: bool, *, restore_state: bool = True) -> None:
        driver = self._require_driver()
        await self._write_many(
            driver.power_payloads(enabled),
            localization_manager.status_ble_event("power", enabled=enabled),
        )
        if enabled and restore_state:
            await asyncio.sleep(0.12)
            await self._write_many(
                driver.brightness_payloads(self._last_brightness),
                localization_manager.status_ble_event("brightness_restore", value=self._last_brightness),
            )
            await asyncio.sleep(0.08)
            await self._write_many(
                driver.color_payloads(self._last_red, self._last_green, self._last_blue),
                localization_manager.status_ble_event(
                    "color_restore",
                    red=self._last_red,
                    green=self._last_green,
                    blue=self._last_blue,
                ),
            )

    async def _set_color(self, red: int, green: int, blue: int) -> None:
        driver = self._require_driver()
        await self._write_many(
            driver.color_payloads(red, green, blue),
            localization_manager.status_ble_event("color_set", red=red, green=green, blue=blue),
        )

    async def _set_color_stream(self, red: int, green: int, blue: int) -> None:
        driver = self._require_driver()
        await self._write_many(driver.color_payloads(red, green, blue), "", quiet=True)

    async def _set_brightness(self, value: int) -> None:
        driver = self._require_driver()
        payloads = driver.brightness_payloads(value)
        if payloads:
            await self._write_many(
                payloads,
                localization_manager.status_ble_event("brightness_set", value=value),
            )
            return
        await self._write_many(
            driver.color_payloads(self._last_red, self._last_green, self._last_blue),
            localization_manager.status_ble_event(
                "color_set",
                red=self._last_red,
                green=self._last_green,
                blue=self._last_blue,
            ),
        )

    async def _set_static_color(self, red: int, green: int, blue: int, brightness: int) -> None:
        self._current_effect_code = 0
        try:
            await self._set_brightness(brightness)
            await asyncio.sleep(0.05)
        except RuntimeError:
            # Some BLEDOM-compatible clones reject standalone brightness writes.
            # Applying RGB should still work, so do not block the color command.
            pass
        await self._set_color(red, green, blue)

    async def _set_effect(self, code: int) -> None:
        if code == 0:
            self._current_effect_code = 0
            self.status_changed.emit(localization_manager.status_ble_event("static_color_mode"))
            return
        payload = self._require_driver().effect_payload(code)
        if payload is None:
            raise RuntimeError("Built-in effects are not supported by this controller yet.")
        await self._write(payload, localization_manager.status_ble_event("effect_applied", code=f"{code:02X}"))
        # Some BLEDOM clones ignore the first effect command when switching from
        # another running effect (e.g. fade → rainbow). A quiet re-send makes the
        # switch reliable without spamming the log.
        await asyncio.sleep(0.08)
        try:
            await self._write(payload, "", quiet=True)
        except BLE_OPERATION_ERRORS:
            pass
        self._current_effect_code = int(code)

    async def _set_effect_with_speed(self, code: int, speed: int) -> None:
        driver = self._require_driver()
        if code == 0:
            await self._set_effect(code)
            return
        combined_builder = getattr(driver, "effect_payload_with_speed", None)
        combined_payload = combined_builder(code, speed) if combined_builder is not None else driver.effect_payload(code)
        default_payload = driver.effect_payload(code)
        if combined_payload is not None and combined_payload != default_payload:
            await self._write(combined_payload, localization_manager.status_ble_event("effect_applied", code=f"{code:02X}"))
            self._current_effect_code = int(code)
            return
        await self._set_effect(code)
        await asyncio.sleep(0.04)
        payload = driver.speed_payload(speed)
        if payload is not None:
            await self._write(payload, localization_manager.status_ble_event("effect_speed_set", value=speed))

    async def _set_effect_speed(self, value: int) -> None:
        driver = self._require_driver()
        current_effect_code = getattr(self, "_current_effect_code", 0)
        if current_effect_code:
            combined_builder = getattr(driver, "effect_payload_with_speed", None)
            combined_payload = combined_builder(current_effect_code, value) if combined_builder is not None else driver.effect_payload(current_effect_code)
            default_payload = driver.effect_payload(current_effect_code)
            if combined_payload is not None and combined_payload != default_payload:
                await self._write(combined_payload, localization_manager.status_ble_event("effect_speed_set", value=value))
                return
        payload = driver.speed_payload(value)
        if payload is None:
            raise RuntimeError("Built-in effects are not supported by this controller yet.")
        await self._write(payload, localization_manager.status_ble_event("effect_speed_set", value=value))

    async def _connect(self, address: str, *, from_reconnect: bool = False) -> None:
        await self._disconnect(cancel_reconnect=not from_reconnect)
        preferred_driver_id = self._scan_driver_hints.get(address)
        device = await asyncio.wait_for(
            BleakScanner.find_device_by_address(address, timeout=FIND_DEVICE_TIMEOUT_SECONDS),
            timeout=FIND_DEVICE_TIMEOUT_SECONDS + 2.0,
        )
        if device is None:
            raise RuntimeError("Device not found. Make sure it is powered on and nearby.")

        client = BleakClient(device, disconnected_callback=self._handle_unexpected_disconnect)
        await asyncio.wait_for(client.connect(), timeout=CONNECT_TIMEOUT_SECONDS)
        services = client.services
        driver = detect_connected_driver(device.name or "", services, preferred_id=preferred_driver_id)
        if driver is None:
            await client.disconnect()
            # Keep the full technical detail (services + characteristics) in the
            # diagnostics history for driver work, but show the user a friendly,
            # actionable line instead of the raw GATT dump.
            diagnostic = self._protocol_detection_diagnostic(device, services, preferred_driver_id)
            self._record_ble_history("protocol_mismatch", details=diagnostic)
            raise ProtocolCompatibilityError(localization_manager.t("error.controller_unsupported"))
        driver.reset_runtime_state()
        if hasattr(driver, "configure_for_device"):
            driver.configure_for_device(device.name or "")
        driver.remember_brightness(self._last_brightness)
        characteristic = driver.pick_write_characteristic(services)
        if characteristic is None:
            await client.disconnect()
            raise RuntimeError("No writable GATT characteristic was found on this device.")

        self._client = client
        self._device = device
        self._driver = driver
        self._write_characteristic = characteristic
        self._write_characteristics = driver.collect_write_characteristics(services)
        self._reconnect_address = address
        self._manual_disconnect_requested = False
        self._clear_last_ble_error()
        self.connected_changed.emit(True, address)
        self.status_changed.emit(
            localization_manager.status_ble_event(
                "driver_selected",
                driver=driver.display_name,
            )
        )
        self.status_changed.emit(
            localization_manager.status_ble_event(
                "connected_via",
                    name=(device.name or "").strip() or address,
                uuid=str(characteristic.uuid),
            )
        )
        if self._write_characteristics:
            uuids = ", ".join(str(item.uuid) for item in self._write_characteristics)
            self.status_changed.emit(localization_manager.status_ble_event("candidate_characteristics", uuids=uuids))

    async def _disconnect(self, *, cancel_reconnect: bool = True) -> None:
        if cancel_reconnect:
            self._cancel_reconnect()
        if self._client is not None:
            try:
                await self._client.disconnect()
            finally:
                self._clear_connection_state()
                self.connected_changed.emit(False, "")
                self.status_changed.emit(localization_manager.status_ble_event("disconnected"))

    def _clear_connection_state(self) -> None:
        self._client = None
        self._device = None
        self._driver = None
        self._write_characteristic = None
        self._write_characteristics = []
        self._preferred_payload_indices = {}

    def _cancel_reconnect(self) -> None:
        task = self._reconnect_task
        if task is not None and not task.done():
            task.cancel()
        self._reconnect_task = None

    def _handle_unexpected_disconnect(self, client) -> None:
        if self._shutdown_started or self._manual_disconnect_requested:
            return
        if not self._loop.is_running():
            return
        self._loop.call_soon_threadsafe(self._on_unexpected_disconnect, client)

    def _on_unexpected_disconnect(self, client) -> None:
        if self._shutdown_started or self._manual_disconnect_requested or client is not self._client:
            return
        self._start_reconnect_after_connection_loss()

    def _start_reconnect_after_connection_loss(self) -> None:
        if self._shutdown_started or self._manual_disconnect_requested:
            return
        device = self._device
        address = device.address if device is not None else self._reconnect_address
        name = (device.name or "").strip() if device is not None else ""
        if self._client is not None:
            self._clear_connection_state()
            self.connected_changed.emit(False, "")
            self._set_last_ble_error("BLE connection was lost. Reconnecting to the last controller...")
            self.status_changed.emit(
                localization_manager.status_ble_event("unexpected_disconnect", name=name or address, address=address)
            )
        if address and (self._reconnect_task is None or self._reconnect_task.done()):
            self._reconnect_address = address
            self._reconnect_task = self._loop.create_task(self._reconnect(address))

    @staticmethod
    def _reconnect_delay(attempt: int) -> float:
        index = min(attempt - 1, len(RECONNECT_BACKOFF_SECONDS) - 1)
        return RECONNECT_BACKOFF_SECONDS[index]

    async def _reconnect(self, address: str) -> None:
        for attempt in range(1, RECONNECT_ATTEMPTS + 1):
            if self._shutdown_started or self._manual_disconnect_requested:
                return
            await asyncio.sleep(self._reconnect_delay(attempt))
            if self._shutdown_started or self._manual_disconnect_requested:
                return
            self.status_changed.emit(
                localization_manager.status_ble_event(
                    "reconnect_attempt",
                    address=address,
                    attempt=attempt,
                    total=RECONNECT_ATTEMPTS,
                )
            )
            try:
                await self._connect(address, from_reconnect=True)
            except BLE_OPERATION_ERRORS as exc:
                message = self._exception_message(exc)
                self._set_last_ble_exception(exc)
                self.status_changed.emit(
                    localization_manager.status_ble_event(
                        "reconnect_failed_attempt",
                        address=address,
                        attempt=attempt,
                        total=RECONNECT_ATTEMPTS,
                        error=message,
                    )
                )
                continue
            self.status_changed.emit(localization_manager.status_ble_event("reconnect_success", address=address))
            await self._restore_state_after_reconnect()
            return
        self.status_changed.emit(localization_manager.status_ble_event("reconnect_give_up", address=address))

    async def _restore_state_after_reconnect(self) -> None:
        """After re-pairing, put the strip back the way the user left it.

        A power-cycled controller comes back in its own default state, so we
        re-apply the last power/brightness/colour (and effect, if one was
        running) to match what the app shows.
        """
        try:
            if not self._desired_power_on:
                await self._set_power(False)
                return
            await self._set_power(True, restore_state=True)
            if self._current_effect_code:
                await asyncio.sleep(0.08)
                await self._set_effect(self._current_effect_code)
        except BLE_OPERATION_ERRORS as exc:
            self._set_last_ble_exception(exc)

    def _require_driver(self) -> LedBleDriver:
        if self._driver is None:
            raise RuntimeError("Connect to the LED strip first.")
        return self._driver

    async def _write(self, payload: bytes, description: str, *, quiet: bool = False) -> None:
        if self._client is None or self._write_characteristic is None:
            raise RuntimeError("Connect to the LED strip first.")
        if not bool(getattr(self._client, "is_connected", True)):
            self._start_reconnect_after_connection_loss()
            self._set_last_ble_error("BLE connection was lost. Reconnecting to the last controller...")
            raise ConnectionLostError("BLE connection was lost. Reconnecting to the last controller...")

        written_to: list[str] = []
        last_error: Exception | None = None

        for characteristic in self._ordered_write_candidates():
            error = await self._write_to_characteristic(characteristic, payload)
            if error is None:
                written_to.append(str(characteristic.uuid))
            else:
                last_error = error

        if not written_to:
            if last_error is not None:
                self._set_last_ble_exception(last_error)
                if not quiet:
                    self.status_changed.emit(
                        localization_manager.status_ble_event("write_failed", error=self._exception_message(last_error))
                    )
            raise ProtocolCompatibilityError("Command could not be written to any compatible GATT characteristic.")

        if quiet:
            return
        self._record_ble_history(
            "command",
            description=description,
            payload=payload.hex(" "),
            targets=", ".join(written_to),
        )
        self.status_changed.emit(f"{description} ({payload.hex(' ')}) -> {', '.join(written_to)}")

    async def _write_to_characteristic(self, characteristic, payload: bytes) -> Exception | None:
        """Try writing payload to one characteristic with retry + response-mode fallback.
        Returns None on success, or the last exception on failure."""
        properties = {prop.lower() for prop in characteristic.properties}
        prefer_response = "write" in properties and "write-without-response" not in properties
        last_error: Exception | None = None

        for attempt in range(WRITE_RETRY_ATTEMPTS + 1):
            error = await self._write_attempt(characteristic, payload, prefer_response)
            if error is None:
                return None
            # Retry with flipped response mode before giving up on this attempt
            error = await self._write_attempt(characteristic, payload, not prefer_response)
            if error is None:
                return None
            last_error = error
            if attempt < WRITE_RETRY_ATTEMPTS:
                self._emit_write_retry(characteristic, payload, attempt + 1, last_error)
                await asyncio.sleep(WRITE_RETRY_DELAY_SECONDS)

        return last_error

    async def _write_attempt(self, characteristic, payload: bytes, response: bool) -> Exception | None:
        """Single GATT write attempt. Returns None on success, exception on failure."""
        client = self._client
        if client is None:
            return ConnectionLostError("BLE connection was lost. Reconnecting to the last controller...")
        try:
            await asyncio.wait_for(
                client.write_gatt_char(characteristic, payload, response=response),
                timeout=WRITE_TIMEOUT_SECONDS,
            )
            return None
        except BLE_OPERATION_ERRORS as exc:
            return exc

    def _emit_write_retry(self, characteristic, payload: bytes, attempt: int, exc: Exception) -> None:
        self._record_ble_history(
            "retry",
            uuid=str(characteristic.uuid),
            attempt=attempt,
            total=WRITE_RETRY_ATTEMPTS,
            error=self._exception_message(exc),
            error_type=exc.__class__.__name__,
            payload=payload.hex(" "),
        )
        self.status_changed.emit(
            localization_manager.status_ble_event(
                "write_retry",
                uuid=str(characteristic.uuid),
                attempt=attempt,
                total=WRITE_RETRY_ATTEMPTS,
                error=self._exception_message(exc),
            )
        )

    def _protocol_detection_diagnostic(self, device: BLEDevice, services, preferred_driver_id: str | None = None) -> str:
        service_uuids = [str(service.uuid).lower() for service in services]
        characteristic_uuids = [
            str(characteristic.uuid).lower()
            for service in services
            for characteristic in service.characteristics
        ]
        return (
            "Device was found and matched a known controller family, but the command protocol differs. "
            f"Device: {(device.name or '').strip() or '-'} ({device.address or '-'}). "
            f"Expected driver: {preferred_driver_id or '-'}. "
            f"Services: {', '.join(service_uuids) or '-'}. "
            f"Characteristics: {', '.join(characteristic_uuids) or '-'}."
        )

    def _ordered_write_candidates(self) -> list[BleakGATTCharacteristic]:
        selected = self._write_characteristic
        raw_candidates = self._write_characteristics or ([selected] if selected is not None else [])
        ordered: list[BleakGATTCharacteristic] = []
        seen: set[str] = set()
        if selected is not None:
            raw_candidates = [selected, *raw_candidates]
        for characteristic in raw_candidates:
            if characteristic is None:
                continue
            properties = {prop.lower() for prop in characteristic.properties}
            if not {"write", "write-without-response"} & properties:
                continue
            uuid = str(characteristic.uuid)
            if uuid in seen:
                continue
            ordered.append(characteristic)
            seen.add(uuid)
        return ordered

    async def _write_many(self, payloads: list[bytes], description: str, *, quiet: bool = False) -> None:
        if self._client is None or self._write_characteristic is None:
            raise RuntimeError("Connect to the LED strip first.")

        if not payloads:
            raise RuntimeError("Command could not be sent with any known protocol.")

        cache_key = (
            self._driver.id if self._driver is not None else "unknown",
            tuple(self._payload_signature(payload) for payload in payloads),
        )
        preferred_index = self._preferred_payload_indices.get(cache_key)
        ordered_payloads = list(enumerate(payloads))
        if preferred_index is not None and 0 <= preferred_index < len(payloads):
            ordered_payloads = [(preferred_index, payloads[preferred_index])] + [
                item for item in ordered_payloads if item[0] != preferred_index
            ]

        last_error: Exception | None = None
        for payload_index, payload in ordered_payloads:
            try:
                await self._write(payload, description, quiet=quiet)
                self._preferred_payload_indices[cache_key] = payload_index
                if self._driver is not None and hasattr(self._driver, "remember_working_payload"):
                    self._driver.remember_working_payload(payload)
                return
            except BLE_OPERATION_ERRORS as exc:
                if isinstance(exc, ConnectionLostError):
                    raise
                last_error = exc
                continue

        if last_error is not None:
            if isinstance(last_error, ConnectionLostError):
                raise last_error
            if isinstance(last_error, ProtocolCompatibilityError):
                diagnostic = self._protocol_mismatch_diagnostic(payloads)
                if not quiet:
                    self._set_last_ble_error(diagnostic)
                    self._record_ble_history("protocol_mismatch", details=diagnostic)
                    self.status_changed.emit(diagnostic)
                raise ProtocolCompatibilityError(diagnostic) from last_error
            raise RuntimeError("Command could not be sent with any known protocol.") from last_error
        raise RuntimeError("Command could not be sent with any known protocol.")

    def _protocol_mismatch_diagnostic(self, payloads: list[bytes]) -> str:
        snapshot = self.diagnostics_snapshot()
        device = snapshot.get("device", {})
        driver = snapshot.get("driver", {})
        write = snapshot.get("write", {})
        candidates = write.get("candidates", [])
        candidate_text = ", ".join(str(item.get("uuid", "")) for item in candidates) or "-"
        payload_text = " | ".join(payload.hex(" ") for payload in payloads) or "-"
        return (
            "Device was found and matched a known controller family, but the command protocol differs. "
            f"Device: {device.get('name') or '-'} ({device.get('address') or '-'}). "
            f"Driver: {driver.get('name') or driver.get('id') or '-'}. "
            f"Selected write characteristic: {write.get('selected_uuid') or '-'}. "
            f"Candidate write characteristics: {candidate_text}. "
            f"Tried payloads: {payload_text}."
        )

    @staticmethod
    def _payload_signature(payload: bytes) -> tuple[int, ...]:
        if len(payload) >= 9 and payload[0] == 0x7E:
            return (len(payload), payload[0], payload[2])
        if len(payload) == 7 and payload[0] == 0x56:
            return (len(payload), payload[0], payload[-2], payload[-1])
        if len(payload) == 3 and payload[0] == 0xCC:
            return (len(payload), payload[0], payload[2])
        if len(payload) >= 2:
            return (len(payload), payload[0], payload[1])
        return (len(payload), *payload)
