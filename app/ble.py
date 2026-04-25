from __future__ import annotations

import asyncio
import threading
from PySide6.QtCore import QObject, Signal
from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from app.ble_drivers import EFFECTS, detect_connected_driver, detect_scan_driver
from app.ble_drivers.base import LedBleDriver, clamp
from app.localization import localization_manager


class BleController(QObject):
    status_changed = Signal(str)
    devices_discovered = Signal(list)
    connected_changed = Signal(bool, str)
    error_occurred = Signal(str)

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

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def shutdown(self) -> None:
        if self._client is not None:
            future = asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)
            future.result(timeout=5)
        self._loop.call_soon_threadsafe(self._loop.stop)

    def _submit(self, coroutine) -> None:
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        future.add_done_callback(self._handle_future)

    def _handle_future(self, future) -> None:
        try:
            future.result()
        except Exception as exc:  # pragma: no cover
            self.error_occurred.emit(str(exc))
            self.status_changed.emit(f"BLE error: {exc}")

    def scan(self) -> None:
        self.status_changed.emit(localization_manager.status_ble_event("scan_start"))
        self._submit(self._scan())

    def connect_to_address(self, address: str) -> None:
        if self._client is not None and self._client.is_connected and self._device is not None and self._device.address == address:
            self.status_changed.emit(localization_manager.status_ble_event("already_connected", address=address))
            self.connected_changed.emit(True, address)
            return
        self.status_changed.emit(localization_manager.status_ble_event("connecting", address=address))
        self._submit(self._connect(address))

    def disconnect(self) -> None:
        self._submit(self._disconnect())

    def set_power(self, enabled: bool, *, restore_state: bool = True) -> None:
        self._submit(self._set_power(enabled, restore_state=restore_state))

    def set_color(self, red: int, green: int, blue: int) -> None:
        self._last_red = clamp(red, 0, 255)
        self._last_green = clamp(green, 0, 255)
        self._last_blue = clamp(blue, 0, 255)
        self._submit(self._set_color(red, green, blue))

    def set_brightness(self, value: int) -> None:
        self._last_brightness = clamp(value, 0, 100)
        if self._driver is not None:
            self._driver.remember_brightness(self._last_brightness)
        self._submit(self._set_brightness(value))

    def set_effect(self, code: int) -> None:
        self._submit(self._set_effect(code))

    def set_effect_with_speed(self, code: int, speed: int) -> None:
        self._submit(self._set_effect_with_speed(code, speed))

    def set_effect_speed(self, value: int) -> None:
        self._submit(self._set_effect_speed(value))

    def supports_effect_code(self, code: int) -> bool:
        if int(code) == 0:
            return True
        if self._driver is None:
            return True
        return self._driver.effect_payload(int(code)) is not None

    async def _scan(self) -> None:
        devices = await BleakScanner.discover(timeout=5.0, return_adv=True)
        results: list[dict[str, str]] = []
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
                    }
                )

        self.devices_discovered.emit(results)
        if results:
            self.status_changed.emit(localization_manager.status_ble_event("scan_finished_found", count=len(results)))
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

    async def _set_brightness(self, value: int) -> None:
        driver = self._require_driver()
        await self._write_many(
            driver.brightness_payloads(value),
            localization_manager.status_ble_event("brightness_set", value=value),
        )

    async def _set_effect(self, code: int) -> None:
        if code == 0:
            self.status_changed.emit(localization_manager.status_ble_event("static_color_mode"))
            return
        payload = self._require_driver().effect_payload(code)
        if payload is None:
            raise RuntimeError("Built-in effects are not supported by this controller yet.")
        await self._write(payload, localization_manager.status_ble_event("effect_applied", code=f"{code:02X}"))

    async def _set_effect_with_speed(self, code: int, speed: int) -> None:
        await self._set_effect(code)
        if code != 0:
            await asyncio.sleep(0.04)
            await self._set_effect_speed(speed)

    async def _set_effect_speed(self, value: int) -> None:
        payload = self._require_driver().speed_payload(value)
        if payload is None:
            raise RuntimeError("Built-in effects are not supported by this controller yet.")
        await self._write(payload, localization_manager.status_ble_event("effect_speed_set", value=value))

    async def _connect(self, address: str) -> None:
        await self._disconnect()
        device = await BleakScanner.find_device_by_address(address, timeout=8.0)
        if device is None:
            raise RuntimeError("Device not found. Make sure it is powered on and nearby.")

        client = BleakClient(device)
        await client.connect()
        services = client.services
        driver = detect_connected_driver(device.name or "", services, preferred_id=self._scan_driver_hints.get(address))
        if driver is None:
            await client.disconnect()
            raise RuntimeError("No supported controller protocol was detected on this device.")
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
                name=device.name or address,
                uuid=str(characteristic.uuid),
            )
        )
        if self._write_characteristics:
            uuids = ", ".join(str(item.uuid) for item in self._write_characteristics)
            self.status_changed.emit(localization_manager.status_ble_event("candidate_characteristics", uuids=uuids))

    async def _disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            finally:
                self._client = None
                self._device = None
                self._driver = None
                self._write_characteristic = None
                self._write_characteristics = []
                self.connected_changed.emit(False, "")
                self.status_changed.emit(localization_manager.status_ble_event("disconnected"))

    def _require_driver(self) -> LedBleDriver:
        if self._driver is None:
            raise RuntimeError("Connect to the LED strip first.")
        return self._driver

    async def _write(self, payload: bytes, description: str) -> None:
        if self._client is None or self._write_characteristic is None:
            raise RuntimeError("Connect to the LED strip first.")

        candidates = self._write_characteristics or [self._write_characteristic]
        written_to: list[str] = []

        for characteristic in candidates:
            properties = {prop.lower() for prop in characteristic.properties}
            prefer_response = "write" in properties and "write-without-response" not in properties
            try:
                await self._client.write_gatt_char(characteristic, payload, response=prefer_response)
                written_to.append(str(characteristic.uuid))
                continue
            except Exception:
                try:
                    await self._client.write_gatt_char(characteristic, payload, response=not prefer_response)
                    written_to.append(str(characteristic.uuid))
                except Exception:
                    continue

        if not written_to:
            raise RuntimeError("Command could not be written to any compatible GATT characteristic.")

        self.status_changed.emit(f"{description} ({payload.hex(' ')}) -> {', '.join(written_to)}")

    async def _write_many(self, payloads: list[bytes], description: str) -> None:
        if self._client is None or self._write_characteristic is None:
            raise RuntimeError("Connect to the LED strip first.")

        sent_any = False
        for payload in payloads:
            try:
                await self._write(payload, description)
                sent_any = True
            except Exception:
                continue

        if not sent_any:
            raise RuntimeError("Command could not be sent with any known protocol.")
