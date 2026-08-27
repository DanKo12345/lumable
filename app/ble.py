from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
from datetime import datetime
from itertools import count
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from PySide6.QtCore import QObject, Qt, Signal

from app.app_info import APP_VERSION
from app.ble_drivers import (
    EFFECTS,
    detect_connected_driver,
    detect_scan_driver,
    get_driver_by_id,
    probe_driver_candidates,
)
from app.ble_drivers.base import LedBleDriver, clamp
from app.ble_reliability import WritePacer, classify_disconnect, reconnect_delay
from app.ble_routing import plan_targets, swap_primary
from app.color_fade import color_distance, fade_frames
from app.known_signatures import identify_record
from app.localization import localization_manager
from app.scan_observations import ScanObservations
from app.scan_ranking import by_signal
from app.scan_snapshot import (
    AdvertisementRecord,
    ScanSnapshot,
    is_possible_controller,
)

CONNECT_TIMEOUT_SECONDS = 10.0
FIND_DEVICE_TIMEOUT_SECONDS = 8.0
# How long a scan listens. Unchanged from what it always was — what changed is
# that the whole five seconds are now kept rather than summarised by whichever
# advertisement happened to arrive last.
SCAN_SECONDS = 5.0
WRITE_TIMEOUT_SECONDS = 3.0
WRITE_RETRY_ATTEMPTS = 2
WRITE_RETRY_DELAY_SECONDS = 0.12
# Reconnect with escalating back-off instead of giving up after a few seconds,
# so a strip that was switched off at the wall for a while still re-pairs when
# it comes back. Delays (seconds) per attempt; the last value repeats.
RECONNECT_ATTEMPTS = 12
# The backoff ladder itself lives in app.ble_reliability; here we only choose how
# much to spread retries so several strips don't reconnect in lockstep.
RECONNECT_JITTER = 0.25

# Smooth colour transitions: number of intermediate frames written when applying
# a new scene, and the minimum jump (per colour channel, or in brightness %) that
# triggers a fade — smaller changes, like nudging a slider, apply instantly.
FADE_STEPS = 7
FADE_MIN_DELTA = 36
FADE_MIN_BRIGHTNESS_DELTA = 6


class ProtocolCompatibilityError(RuntimeError):
    pass


class ConnectionLostError(RuntimeError):
    pass


BLE_OPERATION_ERRORS = (asyncio.TimeoutError, BleakError, ConnectionLostError, OSError, ProtocolCompatibilityError, RuntimeError)
DRIVER_CAPABILITY_ERRORS = (AttributeError, LookupError, NotImplementedError, TypeError, ValueError)

@dataclass
class DeviceConnection:
    """One live BLE controller connection: the client plus the driver and the
    write characteristic(s) chosen for it.

    Each connected controller owns its own driver (different clones speak
    different protocols), so commands are turned into payloads per connection.
    This is the unit a future multi-device list is built from; today there is
    exactly one.
    """

    address: str
    client: BleakClient
    device: BLEDevice
    driver: LedBleDriver
    write_characteristic: BleakGATTCharacteristic
    write_characteristics: list[BleakGATTCharacteristic] = field(default_factory=list)
    preferred_payload_indices: dict = field(default_factory=dict)
    # Pacing is per link: each controller floods on its own connection, so a
    # shared pacer would needlessly serialise writes across strips.
    pacer: WritePacer = field(default_factory=WritePacer)


# Outcome codes for a tracked operation.
RESULT_SUCCESS = "success"
RESULT_CANCELLED = "cancelled"
RESULT_UNAVAILABLE = "unavailable"  # nothing was written: no target, or refused
RESULT_BLE_ERROR = "ble_error"
RESULT_SHUTDOWN = "shutdown"

# Returned by a command that found no device to write to. Distinct from None so
# a coroutine that simply returns nothing is not mistaken for a missing target.
NO_TARGET = object()


@dataclass
class _OperationState:
    """Everything known about one tracked operation, in a single object.

    Kept together so the registry can be emptied in one step: separate
    dictionaries for results, readiness and delivery grew without bound and made
    "exactly once" a matter of thread timing.
    """

    future: Any = None
    # Set once the command holds the serialized section. Before that a cancel
    # can drop it outright; after, cancelling the future would release the lock
    # while a write is still on its way, letting the next command overlap it.
    started: bool = False
    cancel_requested: bool = False
    delivered: bool = False


@dataclass(frozen=True)
class BleOperationResult:
    """How one tracked BLE command ended.

    ``ok`` means the coroutine finished without raising. For a
    write-without-response characteristic that is not an acknowledgement from
    the strip itself — it is the strongest confirmation the BLE stack offers.
    """

    operation_id: int
    ok: bool
    code: str
    message: str = ""


class BleController(QObject):
    status_changed = Signal(str)
    devices_discovered = Signal(list)
    connected_changed = Signal(bool, str)
    error_occurred = Signal(str)
    shutdown_finished = Signal()
    # Carries a BleOperationResult. An object rather than positional arguments so
    # fields can be added later without breaking every receiver.
    operation_finished = Signal(object)
    # Carries a GattInspection: what an unrecognised device exposes.
    inspection_finished = Signal(object)
    # Internal hop that makes delivery queued regardless of the emitting thread.
    _operation_ready = Signal(object)
    mirrors_changed = Signal(list)
    # An extra strip took over as the main one: (address, advertised name).
    primary_changed = Signal(str, str)
    # An unrecognised controller looks like it might be a known driver:
    # (address, driver_id, driver_display_name). Emitted before the unsupported
    # error so the UI can offer to try that driver.
    protocol_candidate_found = Signal(str, str, str)
    # Auto-reconnect progress for the UI: (address, attempt, total, delay_seconds)
    # emitted before each backoff wait, and give-up after the last attempt.
    reconnect_scheduled = Signal(str, int, int, float)
    reconnect_gave_up = Signal(str)
    # The link came back. Distinct from an attempt: a live-sync session wants to
    # know how many times the strip actually dropped out from under it.
    reconnect_succeeded = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._client: BleakClient | None = None
        self._device: BLEDevice | None = None
        self._driver: LedBleDriver | None = None
        self._scan_driver_hints: dict[str, str] = {}
        # What the last scan offered, kept for the report.
        self._last_scan_results: list[dict[str, Any]] = []
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
        # Tracked operations: automation needs to know whether a command really
        # finished, which the fire-and-forget path cannot tell it.
        self._operation_ids = count(1)
        self._operations: dict[int, _OperationState] = {}
        # One lock over the whole registry: results arrive on the BLE thread
        # while cancels come from the UI thread.
        self._operations_lock = threading.Lock()
        # Queued on purpose: emitting straight from _submit would run the slot
        # before the caller has the id it is meant to match.
        self._operation_ready.connect(self._deliver_operation, Qt.QueuedConnection)
        self._preferred_payload_indices: dict[tuple[str, tuple[tuple[int, ...], ...]], int] = {}
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_address = ""
        self._ble_history: list[dict[str, str]] = []
        self._last_ble_error = ""
        self._stream_busy = False
        # Reliability: keep discrete commands from arriving back-to-back, and
        # remember how long the last session lasted so a flapping link backs off
        # faster than one that dropped after a healthy run.
        self._pacer = WritePacer()
        self._session_started_at: float | None = None
        self._last_session_seconds: float | None = None
        self._last_disconnect_reason = ""
        # Unrecognised-but-plausible LED controllers seen in the last scan, kept
        # so the diagnostics report can list them for adding driver support.
        self._unknown_devices: list[dict[str, str]] = []
        # Everything the last scan saw, filtering included, for a snapshot the
        # user can attach to an issue.
        self._scan_snapshot = ScanSnapshot()
        # Extra controllers driven in mirror with the primary (multi-device).
        # The primary write path is untouched; commands fan out to these too.
        self._mirror_connections: list[DeviceConnection] = []
        # Bumped by every colour/brightness command so an in-flight fade can tell
        # it was superseded and stop (latest target wins, no laggy backlog).
        self._fade_seq = 0

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

    def _submit(self, coroutine, *, tracked: bool = False) -> int | None:
        """Queue a BLE command. With ``tracked``, returns an id and reports back.

        Untracked is the historical behaviour: fire and forget, errors surfaced
        through ``error_occurred`` only. Tracked callers get exactly one
        ``operation_finished`` for the id, in every branch below — automation
        cannot confirm a rule as applied without that.

        The result is always delivered through a queued connection, so a slot
        never runs before this call returns and the caller has the id.
        """
        operation_id = next(self._operation_ids) if tracked else None
        if operation_id is not None:
            with self._operations_lock:
                self._operations[operation_id] = _OperationState()

        if self._shutdown_started or not self._loop.is_running():
            coroutine.close()
            self._finish_operation(operation_id, False, RESULT_SHUTDOWN)
            return operation_id

        wrapper = self._run_serialized(coroutine, operation_id)
        try:
            future = asyncio.run_coroutine_threadsafe(wrapper, self._loop)
        except RuntimeError as exc:
            wrapper.close()
            coroutine.close()
            self._finish_operation(operation_id, False, RESULT_UNAVAILABLE, str(exc))
            return operation_id

        if operation_id is not None:
            with self._operations_lock:
                state = self._operations.get(operation_id)
                if state is not None:
                    state.future = future
        future.add_done_callback(lambda done: self._handle_future(done, operation_id))
        return operation_id

    def _finish_operation(
        self, operation_id: int | None, ok: bool, code: str, message: str = ""
    ) -> None:
        """Record and deliver the outcome once. Later calls for the id do nothing.

        The whole check-and-set happens under the lock: the BLE thread's done
        callback and a cancel from the UI thread can arrive together, and
        "exactly once" must not depend on which wins.
        """
        if operation_id is None:
            return
        with self._operations_lock:
            state = self._operations.get(operation_id)
            if state is None or state.delivered:
                return
            state.delivered = True
            if state.cancel_requested and ok:
                # It finished, but the user had already asked us to stop, so the
                # result must not be counted as a rule doing its job.
                ok, code = False, RESULT_CANCELLED
            result = BleOperationResult(
                operation_id=operation_id, ok=ok, code=code, message=message
            )
            self._operations.pop(operation_id, None)
        self._operation_ready.emit(result)

    def _deliver_operation(self, result: object) -> None:
        """Queued slot: runs on this object's thread, after _submit returned."""
        self.operation_finished.emit(result)

    def cancel_operation(self, operation_id: int) -> bool:
        """Ask a tracked operation to stop. False when it is already finished.

        A command still waiting for the command lock is dropped outright. One
        that is already running is asked to stop *cooperatively*: its future is
        left alone so it keeps the lock until the write in progress finishes,
        and the next command therefore starts after it rather than alongside it.
        Nothing already handed to the BLE stack is recalled, and nothing is
        undone.
        """
        with self._operations_lock:
            state = self._operations.get(operation_id)
            if state is None or state.delivered:
                return False
            state.cancel_requested = True
            future = None if state.started else state.future
        if future is not None and future.cancel():
            # It never started, so no done callback will report for it.
            self._finish_operation(operation_id, False, RESULT_CANCELLED)
        return True

    def _mark_operation_started(self, operation_id: int | None) -> None:
        if operation_id is None:
            return
        with self._operations_lock:
            state = self._operations.get(operation_id)
            if state is not None:
                state.started = True

    def is_cancel_requested(self, operation_id: int) -> bool:
        """For multi-step commands: stop before starting the next step."""
        with self._operations_lock:
            state = self._operations.get(operation_id)
            return bool(state is not None and state.cancel_requested)

    async def _run_serialized(self, coroutine, operation_id: int | None = None):
        coroutine_started = False
        try:
            async with self._operation_lock:
                coroutine_started = True
                self._mark_operation_started(operation_id)
                return await coroutine
        finally:
            if not coroutine_started:
                coroutine.close()

    def _handle_future(self, future, operation_id: int | None = None) -> None:
        try:
            outcome = future.result()
        except CancelledError:
            self._finish_operation(operation_id, False, RESULT_CANCELLED)
            return
        except BLE_OPERATION_ERRORS as exc:  # pragma: no cover
            message = self._exception_message(exc)
            self._set_last_ble_exception(exc)
            self._finish_operation(operation_id, False, RESULT_BLE_ERROR, message)
            self.error_occurred.emit(message)
            self.status_changed.emit(f"BLE error: {message}")
            return
        except Exception as exc:  # pragma: no cover
            message = self._exception_message(exc)
            self._set_last_ble_exception(exc)
            self._finish_operation(operation_id, False, RESULT_BLE_ERROR, message)
            self.error_occurred.emit(message)
            self.status_changed.emit(f"BLE error: {message}")
            return
        # A command that found no target wrote nothing, so it is not a success —
        # an addressed operation whose strip vanished must not confirm a rule.
        if outcome is NO_TARGET:
            self._finish_operation(operation_id, False, RESULT_UNAVAILABLE)
            return
        self._finish_operation(operation_id, True, RESULT_SUCCESS)

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

    def connect_to_address(self, address: str, *, force_driver_id: str | None = None) -> None:
        if self._client is not None and self._client.is_connected and self._device is not None and self._device.address == address:
            self.status_changed.emit(localization_manager.status_ble_event("already_connected", address=address))
            self.connected_changed.emit(True, address)
            return
        self._manual_disconnect_requested = False
        self._cancel_reconnect()
        self.status_changed.emit(localization_manager.status_ble_event("connecting", address=address))
        self._submit(self._connect(address, force_driver_id=force_driver_id))

    def disconnect(self) -> None:
        self._manual_disconnect_requested = True
        self._cancel_reconnect()
        self._submit(self._disconnect())

    def add_mirror_device(self, address: str) -> None:
        """Connect an extra controller driven in mirror with the primary."""
        self._submit(self._add_mirror(address))

    def restore_mirror_device(self, address: str) -> None:
        """Reconnect a remembered extra strip after the primary came up.

        Unlike ``add_mirror_device`` a failure here is quiet: a strip that is
        simply switched off must not raise an error dialog on every launch or
        every reconnect — it just stays listed as unavailable.
        """
        self._submit(self._restore_mirror(address))

    def remove_mirror_device(self, address: str) -> None:
        self._submit(self._remove_mirror(address))

    def promote_mirror_to_primary(self, address: str, *, keep_old_as_extra: bool = True) -> None:
        """Make an extra strip the main one.

        ``keep_old_as_extra`` (the default) swaps roles: both links stay up and
        the previous main strip keeps following the light as an extra. When it
        is False the previous main strip is disconnected instead, so only the
        new one remains. Either way this is a single queued operation — never a
        swap followed by a separate removal, which would leave a window where a
        light command could reach a strip the user just dropped.
        """
        self._submit(self._promote_mirror(address, keep_old_as_extra=keep_old_as_extra))

    def mirror_addresses(self) -> list[str]:
        return [conn.address for conn in self._mirror_connections]

    def _primary_address(self) -> str:
        return self._device.address if self._device is not None else ""

    # ── addressed writes (target a subset of strips without side effects) ──
    # These deliberately do NOT reuse set_color()/set_power(): those mutate the
    # shared _last_* caches and run power-restore logic. Here we write only to the
    # chosen connections, using each connection's own driver (mixed drivers work),
    # and only sync the primary caches when the primary is among the targets.
    def set_color_for_addresses(self, red: int, green: int, blue: int, addresses: list[str] | None) -> None:
        self._submit(self._set_color_for_addresses(red, green, blue, addresses))

    def set_power_for_addresses(self, enabled: bool, addresses: list[str] | None) -> None:
        self._submit(self._set_power_for_addresses(enabled, addresses))

    def set_brightness_for_addresses(self, value: int, addresses: list[str] | None) -> None:
        self._submit(self._set_brightness_for_addresses(value, addresses))

    def set_effect_for_addresses(self, code: int, speed: int | None, addresses: list[str] | None) -> None:
        self._submit(self._set_effect_for_addresses(code, speed, addresses))

    # ── tracked variants ───────────────────────────────────────────────
    # Separate methods rather than a flag on the existing ones: the UI and the
    # Local API keep their fire-and-forget contract untouched, and only
    # automation pays for tracking. Each runs the very same coroutine, so no
    # BLE logic is duplicated here.

    def primary_address(self) -> str:
        """Address of the main strip, for a rule that targets it alone."""
        return self._primary_address()

    # One address per tracked operation, deliberately. A tracked call covering
    # several strips would report success as soon as *any* of them accepted the
    # write, hiding a scene that only half applied. Singular targets make each
    # strip its own step, so a mirror that refused becomes a failed step and the
    # scene reports partial instead of done. Callers wanting "all strips" expand
    # that to concrete addresses first.

    @staticmethod
    def _single_target(address: str) -> list[str]:
        if not isinstance(address, str) or not address.strip():
            raise ValueError("a tracked command needs exactly one strip address")
        return [address]

    def set_power_for_address_tracked(self, enabled: bool, address: str) -> int:
        return self._submit(
            self._set_power_for_addresses(enabled, self._single_target(address)), tracked=True
        )

    def set_color_for_address_tracked(self, red: int, green: int, blue: int, address: str) -> int:
        return self._submit(
            self._set_color_for_addresses(red, green, blue, self._single_target(address)),
            tracked=True,
        )

    def set_brightness_for_address_tracked(self, value: int, address: str) -> int:
        return self._submit(
            self._set_brightness_for_addresses(value, self._single_target(address)), tracked=True
        )

    def set_effect_for_address_tracked(self, code: int, speed: int | None, address: str) -> int:
        return self._submit(
            self._set_effect_for_addresses(code, speed, self._single_target(address)), tracked=True
        )

    def set_power(self, enabled: bool, *, restore_state: bool = True) -> None:
        self._fade_seq = getattr(self, "_fade_seq", 0) + 1
        self._desired_power_on = bool(enabled)
        self._submit(self._set_power(enabled, restore_state=restore_state))

    def set_color(self, red: int, green: int, blue: int) -> None:
        self._fade_seq = getattr(self, "_fade_seq", 0) + 1
        self._last_red = clamp(red, 0, 255)
        self._last_green = clamp(green, 0, 255)
        self._last_blue = clamp(blue, 0, 255)
        self._desired_power_on = True
        self._submit(self._set_color(red, green, blue))

    def set_color_stream(
        self,
        red: int,
        green: int,
        blue: int,
        observer: Callable[[bool], None] | None = None,
    ) -> bool:
        """Fast colour-only write for live streaming (ambient sync, etc.).

        Drops the frame if a previous stream write is still in flight, so the
        slow BLE link never backs up; writes colour only (no brightness, no
        forced delay); and is logged quietly to avoid flooding the session log.

        Returns whether the write was accepted. A dropped frame is not a failed
        one, and callers measuring the link must be able to tell them apart.
        ``observer`` is called exactly once with the outcome of an accepted
        write, on the BLE loop thread.
        """
        self._fade_seq = getattr(self, "_fade_seq", 0) + 1
        if self._stream_busy:
            return False
        self._last_red = clamp(red, 0, 255)
        self._last_green = clamp(green, 0, 255)
        self._last_blue = clamp(blue, 0, 255)
        self._desired_power_on = True
        self._stream_busy = True
        return self._submit_stream(
            self._set_color_stream(self._last_red, self._last_green, self._last_blue),
            observer=observer,
        )

    def _submit_stream(self, coroutine, observer: Callable[[bool], None] | None = None) -> bool:
        """Run a streaming write. Returns whether it was accepted.

        The optional observer is the only addition for callers that measure the
        link; without one this behaves exactly as before, which is what every
        other mode relies on.
        """
        if self._shutdown_started or not self._loop.is_running():
            coroutine.close()
            self._stream_busy = False
            return False
        # Streaming frames are best-effort and never tracked: they are replaced
        # by the next frame, so there is nothing for an automation to confirm.
        wrapper = self._run_serialized(coroutine)
        try:
            future = asyncio.run_coroutine_threadsafe(wrapper, self._loop)
        except RuntimeError:
            wrapper.close()
            coroutine.close()
            self._stream_busy = False
            return False

        def _done(completed) -> None:
            self._stream_busy = False
            ok = True
            try:
                completed.result()
            except Exception:
                # Streaming frames are best-effort; never spam logs/errors.
                ok = False
            if observer is not None:
                # Exactly once per accepted write, whichever way it ended.
                observer(ok)

        future.add_done_callback(_done)
        return True

    def set_brightness(self, value: int) -> None:
        self._last_brightness = clamp(value, 0, 100)
        self._desired_power_on = True
        if self._driver is not None:
            self._driver.remember_brightness(self._last_brightness)
        self._submit(self._set_brightness(value))

    def set_static_color(self, red: int, green: int, blue: int, brightness: int) -> None:
        self._fade_seq = getattr(self, "_fade_seq", 0) + 1
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

    def set_color_fade(self, red: int, green: int, blue: int, brightness: int) -> None:
        """Apply a static colour with a short smooth transition from the current
        colour. Small changes (a slider nudge) snap instantly; bigger scene jumps
        animate. Falls back to an instant apply when the change is tiny.
        """
        red, green, blue = clamp(red, 0, 255), clamp(green, 0, 255), clamp(blue, 0, 255)
        brightness = clamp(brightness, 0, 100)
        self._fade_seq = getattr(self, "_fade_seq", 0) + 1
        start = (self._last_red, self._last_green, self._last_blue)
        end = (red, green, blue)
        start_brightness = self._last_brightness
        color_jump = color_distance(start, end) >= FADE_MIN_DELTA
        brightness_jump = abs(start_brightness - brightness) >= FADE_MIN_BRIGHTNESS_DELTA
        if not color_jump and not brightness_jump:
            self.set_static_color(red, green, blue, brightness)
            return
        self._last_red, self._last_green, self._last_blue = end
        self._last_brightness = brightness
        self._desired_power_on = True
        if self._driver is not None:
            self._driver.remember_brightness(brightness)
        self._submit(self._fade_to(start, end, start_brightness, brightness, self._fade_seq))

    def set_effect(self, code: int) -> None:
        self._fade_seq = getattr(self, "_fade_seq", 0) + 1
        self._desired_power_on = True
        self._submit(self._set_effect(code))

    def set_effect_with_speed(self, code: int, speed: int) -> None:
        self._fade_seq = getattr(self, "_fade_seq", 0) + 1
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

    def active_driver_id(self) -> str:
        """The id of the driver currently bound to the connection ('' if none),
        used to look up static hardware capabilities."""
        return self._driver.id if self._driver is not None else ""

    def _driver_for_address(self, address: str | None) -> LedBleDriver | None:
        """The driver of one connected strip — the primary or a mirror. Each
        controller owns its own driver, so a group can mix protocols."""
        wanted = str(address or "").strip()
        if not wanted:
            return None
        if wanted == self._primary_address():
            return self._driver
        for conn in self._mirror_connections:
            if conn.address == wanted:
                return conn.driver
        return None

    def driver_id_for_address(self, address: str | None) -> str:
        driver = self._driver_for_address(address)
        return driver.id if driver is not None else ""

    def supports_effect_speed_for_address(self, address: str | None) -> bool:
        driver = self._driver_for_address(address)
        if driver is None:
            return True
        try:
            return bool(driver.supports_effect_speed())
        except DRIVER_CAPABILITY_ERRORS:
            return True

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
            # Every strip the app drives, not just the main one: a report that
            # showed only the primary made multi-strip issues invisible.
            "strips": [
                {
                    "role": "primary",
                    "name": (device.name or "").strip() if device is not None else "",
                    "address": device.address if device is not None else "",
                    "connected": bool(self._client is not None and self._client.is_connected),
                }
            ]
            + [
                {
                    "role": "extra",
                    "name": (conn.device.name or "").strip() if conn.device is not None else "",
                    "address": conn.address,
                    "connected": bool(conn.client is not None and conn.client.is_connected),
                }
                # getattr: the snapshot is also built from partially
                # constructed controllers (diagnostics on a failed connect).
                for conn in (getattr(self, "_mirror_connections", None) or [])
            ],
            "history": {
                "last_error": getattr(self, "_last_ble_error", ""),
                "last_disconnect_reason": getattr(self, "_last_disconnect_reason", ""),
                "last_session_seconds": getattr(self, "_last_session_seconds", None),
                "last_command": self._last_history_item("command"),
                "events": list(getattr(self, "_ble_history", [])),
            },
            "nearby_unknown": list(getattr(self, "_unknown_devices", [])),
            # Everything the last scan offered, recognised or not. The
            # unrecognised list alone answers "why is my device missing"; it
            # cannot answer "why did it pick that one", because the strips being
            # compared are exactly the ones it leaves out.
            "nearby_scan": list(getattr(self, "_last_scan_results", [])),
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

    # ── read-only compatibility check ──────────────────────────────────
    def inspect_device(self, address: str, name: str = "", *, token: int = 0) -> None:
        """Look at what an unrecognised device offers, without touching it.

        Deliberately not the normal connect path. Nothing is written, no driver
        is chosen, and none of the controller's own state — client, driver,
        write characteristic, colour caches — is touched, so a device we do not
        understand can be examined without its lights changing or a wrong
        protocol being tried on it.
        """
        self._submit(self._inspect_device(address, name, token))

    async def _inspect_device(self, address: str, name: str = "", token: int = 0):
        from app.scan_snapshot import GattCharacteristic, GattInspection, GattService

        services: list[GattService] = []
        error = ""
        client = BleakClient(address)
        try:
            await client.connect()
            for service in client.services:
                characteristics = tuple(
                    GattCharacteristic(
                        uuid=str(characteristic.uuid).lower(),
                        properties=tuple(str(prop) for prop in characteristic.properties),
                    )
                    for characteristic in service.characteristics
                )
                services.append(
                    GattService(uuid=str(service.uuid).lower(), characteristics=characteristics)
                )
        except Exception as exc:
            error = self._exception_message(exc)
        finally:
            # Always let go: an inspection that held the link would block the
            # device from being used by anything else, including its own app.
            try:
                await client.disconnect()
            except Exception:
                pass

        inspection = GattInspection(
            address=address, name=name, services=tuple(services), error=error, token=token
        )
        self._scan_snapshot = ScanSnapshot(
            records=self._scan_snapshot.records,
            inspections=(*self._scan_snapshot.inspections, inspection),
            captured_at=self._scan_snapshot.captured_at,
            app_version=self._scan_snapshot.app_version,
            note=self._scan_snapshot.note,
        )
        self.inspection_finished.emit(inspection)
        return None

    def scan_snapshot(self) -> ScanSnapshot:
        """Everything the last scan saw, for export from diagnostics."""
        return self._scan_snapshot

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
            # Asked, not exercised: the old probe built a real 50% payload, and
            # drivers that remember the last brightness would then apply it to
            # the next colour command — so merely rendering the card changed the
            # light.
            brightness = bool(driver.supports_brightness())
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

    async def _listen_for_advertisements(self) -> ScanObservations:
        """Hear out a whole scan, keeping every advertisement it brings.

        ``discover()`` returned one advertisement per device — the last one —
        and the five seconds of listening produced a single reading each. The
        readings vary by several dB from one moment to the next, so a distant
        strip that happened to send a strong one outranked a close one that did
        not, and no amount of care further down could recover what was never
        kept.

        The scanner is stopped by leaving the block, on every path out of it
        including an exception and a cancellation. A scanner left running holds
        the adapter, and the next scan on a machine whose adapter is already
        busy is the one that finds nothing at all.
        """
        seen = ScanObservations()
        async with BleakScanner(detection_callback=seen.observe):
            await asyncio.sleep(SCAN_SECONDS)
        return seen

    async def _scan(self) -> None:
        # Nothing is decided or announced until the scanner has stopped. A list
        # that reorders itself while advertisements arrive moves the row a
        # person is reaching for, and the reading it reorders on is the noisy
        # single one this exists to stop trusting.
        seen = await self._listen_for_advertisements()
        results: list[dict[str, Any]] = []
        unknown: list[dict[str, Any]] = []
        captured: list[AdvertisementRecord] = []
        self._scan_driver_hints.clear()
        for observed in seen.devices():
            record = observed.record
            captured.append(record)
            handle = observed.handle
            address = str(getattr(handle, "address", "") or observed.address)
            name = record.name or "Unknown BLE Device"
            service_uuids = list(record.service_uuids)
            driver = detect_scan_driver(name, service_uuids)
            known = identify_record(record)
            if driver is not None:
                self._scan_driver_hints[address] = driver.id
                results.append(
                    {
                        "name": name,
                        "address": address,
                        "rssi": str(record.rssi if record.rssi is not None else ""),
                        "rssi_samples": observed.rssi_samples,
                        "driver": driver.display_name,
                        "supported": True,
                    }
                )
            elif known is not None or is_possible_controller(record):
                # Judged on the *captured* record, not on `name` above: that one
                # has already been given the "Unknown BLE Device" placeholder,
                # and the old heuristic matched the "ble" in it — which offered
                # every anonymous device in radio range as a possible strip.
                # A device we can name but not drive: the signature is known,
                # the command protocol is not verified. Naming it is far more
                # useful than "unknown device" and far more honest than
                # pretending it works.
                unknown.append(
                    {
                        "name": name,
                        "address": address,
                        "rssi": str(record.rssi if record.rssi is not None else ""),
                        "rssi_samples": observed.rssi_samples,
                        "services": ", ".join(service_uuids) or "-",
                        "supported": False,
                        "known_name": known.display_name if known is not None else "",
                    }
                )

        # Ordered on the median of everything heard, not on whichever reading
        # arrived last. The trusted group is applied further up, where what this
        # person has chosen is known; here the two lists only need to be in a
        # settled order — the cap below decides which unrecognised devices
        # survive, and deciding that on one noisy reading is how a strip that
        # was in the room fails to appear at all.
        results = by_signal(results)
        unknown = by_signal(unknown)
        self._unknown_devices = unknown[:12]
        self._last_scan_results = results + self._unknown_devices
        # Replaces the previous capture rather than accumulating: a snapshot
        # describes one scan, and a stale device from ten minutes ago in the
        # file would send a driver author chasing hardware that has left.
        self._scan_snapshot = ScanSnapshot(
            records=tuple(captured),
            captured_at=datetime.now().isoformat(timespec="seconds"),
            app_version=APP_VERSION,
        )
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
        await self._fan_out(lambda d: d.power_payloads(enabled))
        if enabled and restore_state:
            await asyncio.sleep(0.12)
            await self._write_many(
                driver.brightness_payloads(self._last_brightness),
                localization_manager.status_ble_event("brightness_restore", value=self._last_brightness),
            )
            await self._fan_out(lambda d: d.brightness_payloads(self._last_brightness))
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
            await self._fan_out(lambda d: d.color_payloads(self._last_red, self._last_green, self._last_blue))

    async def _set_color(self, red: int, green: int, blue: int) -> None:
        driver = self._require_driver()
        await self._write_many(
            driver.color_payloads(red, green, blue),
            localization_manager.status_ble_event("color_set", red=red, green=green, blue=blue),
        )
        await self._fan_out(lambda d: d.color_payloads(red, green, blue))

    async def _set_color_stream(self, red: int, green: int, blue: int) -> None:
        # Live frames (screen sync, music, DIY, fades): exempt from pacing — they
        # already self-throttle by dropping frames when a write is in flight.
        driver = self._require_driver()
        await self._write_many(driver.color_payloads(red, green, blue), "", quiet=True, stream=True)
        await self._fan_out(lambda d: d.color_payloads(red, green, blue), stream=True)

    # ── addressed write implementations ────────────────────────────────
    def _plan_addresses(self, addresses: list[str] | None) -> dict:
        return plan_targets(addresses, self._primary_address(), self.mirror_addresses())

    def _targeted_mirrors(self, plan: dict) -> list[DeviceConnection]:
        chosen = set(plan["mirrors"])
        return [conn for conn in self._mirror_connections if conn.address in chosen]

    def _primary_writable(self, plan: dict) -> bool:
        return bool(plan["primary"]) and self._client is not None and self._write_characteristic is not None

    async def _set_color_for_addresses(self, red: int, green: int, blue: int, addresses: list[str] | None):
        red, green, blue = clamp(red, 0, 255), clamp(green, 0, 255), clamp(blue, 0, 255)
        plan = self._plan_addresses(addresses)
        wrote_primary = False
        wrote_mirror = False
        if self._primary_writable(plan):
            await self._write_many(self._require_driver().color_payloads(red, green, blue), "", quiet=True)
            wrote_primary = True
        for conn in self._targeted_mirrors(plan):
            wrote_mirror |= await self._mirror_write_payloads(
                conn, conn.driver.color_payloads(red, green, blue)
            )
        # Only a write that happened may update the cache: the plan says where
        # the command was aimed, not that anything got there.
        if plan["sync_primary"] and wrote_primary:
            self._last_red, self._last_green, self._last_blue = red, green, blue
        return None if wrote_primary or wrote_mirror else NO_TARGET

    async def _set_power_for_addresses(self, enabled: bool, addresses: list[str] | None):
        enabled = bool(enabled)
        plan = self._plan_addresses(addresses)
        wrote_primary = False
        wrote_mirror = False
        if self._primary_writable(plan):
            await self._write_many(self._require_driver().power_payloads(enabled), "", quiet=True)
            wrote_primary = True
        for conn in self._targeted_mirrors(plan):
            wrote_mirror |= await self._mirror_write_payloads(
                conn, conn.driver.power_payloads(enabled)
            )
        if plan["sync_primary"] and wrote_primary:
            # Reconnect restores the *desired* power state. Without this an
            # addressed power write to the primary would be undone by the next
            # dropped-link recovery, flipping the strip back against the scene.
            self._desired_power_on = enabled
        return None if wrote_primary or wrote_mirror else NO_TARGET

    async def _set_brightness_for_addresses(self, value: int, addresses: list[str] | None):
        value = clamp(value, 0, 100)
        plan = self._plan_addresses(addresses)
        red, green, blue = self._last_red, self._last_green, self._last_blue
        wrote_primary = False
        wrote_mirror = False
        if self._primary_writable(plan):
            driver = self._require_driver()
            payloads = driver.brightness_payloads(value) or driver.color_payloads(red, green, blue)
            await self._write_many(payloads, "", quiet=True)
            wrote_primary = True
        for conn in self._targeted_mirrors(plan):
            payloads = conn.driver.brightness_payloads(value) or conn.driver.color_payloads(red, green, blue)
            wrote_mirror |= await self._mirror_write_payloads(conn, payloads)
        if plan["sync_primary"] and wrote_primary:
            self._last_brightness = value
        return None if wrote_primary or wrote_mirror else NO_TARGET

    async def _set_effect_for_addresses(self, code: int, speed: int | None, addresses: list[str] | None):
        code = int(code)
        plan = self._plan_addresses(addresses)

        def build(driver) -> bytes | None:
            payload = driver.effect_payload_with_speed(code, speed) if speed is not None else None
            return payload or driver.effect_payload(code)

        wrote_primary = False
        wrote_mirror = False
        if self._primary_writable(plan):
            payload = build(self._require_driver())
            if payload is not None:
                await self._write_many([payload], "", quiet=True)
                wrote_primary = True
        for conn in self._targeted_mirrors(plan):
            payload = build(conn.driver)
            if payload is not None:
                wrote_mirror |= await self._mirror_write_payloads(conn, [payload])
        # A driver with no payload for this effect wrote nothing, so the
        # command did not happen — however willing the plan was.
        if plan["sync_primary"] and wrote_primary:
            self._current_effect_code = code
        return None if wrote_primary or wrote_mirror else NO_TARGET

    async def _set_brightness(self, value: int) -> None:
        driver = self._require_driver()
        payloads = driver.brightness_payloads(value)
        if payloads:
            await self._write_many(
                payloads,
                localization_manager.status_ble_event("brightness_set", value=value),
            )
            # Mirror brightness, falling back to colour for drivers without it.
            await self._fan_out(
                lambda d: d.brightness_payloads(value)
                or d.color_payloads(self._last_red, self._last_green, self._last_blue)
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
        await self._fan_out(lambda d: d.color_payloads(self._last_red, self._last_green, self._last_blue))

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

    async def _fade_to(
        self,
        start: tuple[int, int, int],
        end: tuple[int, int, int],
        start_brightness: int,
        end_brightness: int,
        seq: int,
    ) -> None:
        """Stream a short interpolation of colour (and brightness, when it also
        changes) from start to end, then lock in the final scene. Aborts early if
        a newer command bumped ``_fade_seq`` (latest target wins). The BLE write
        rate paces the fade; mirrors follow the per-frame colour writes.
        """
        self._current_effect_code = 0
        fade_brightness = start_brightness != end_brightness
        if not fade_brightness:
            # Brightness isn't changing — set it once, then fade only the colour.
            try:
                await self._set_brightness(end_brightness)
                await asyncio.sleep(0.04)
            except RuntimeError:
                pass
        frames = fade_frames(start, end, FADE_STEPS)
        total = len(frames)
        for index, frame in enumerate(frames[:-1], start=1):
            if seq != self._fade_seq:
                return  # a newer colour/brightness command superseded this fade
            try:
                if fade_brightness and self._driver is not None:
                    value = round(start_brightness + (end_brightness - start_brightness) * (index / total))
                    payloads = self._driver.brightness_payloads(value)
                    if payloads:
                        await self._write_many(payloads, "", quiet=True, stream=True)
                await self._set_color_stream(*frame)
            except BLE_OPERATION_ERRORS:
                break
        if seq != self._fade_seq:
            return
        if fade_brightness:
            try:
                await self._set_brightness(end_brightness)
                await asyncio.sleep(0.03)
            except RuntimeError:
                pass
        await self._set_color(*end)

    async def _set_effect(self, code: int) -> None:
        if code == 0:
            self._current_effect_code = 0
            self.status_changed.emit(localization_manager.status_ble_event("static_color_mode"))
            return
        payload = self._require_driver().effect_payload(code)
        if payload is None:
            raise RuntimeError("Built-in effects are not supported by this controller yet.")
        await self._write(payload, localization_manager.status_ble_event("effect_applied", code=f"{code:02X}"))
        # Mirror the same effect code (best-effort; identical controllers match).
        await self._fan_out(lambda d: d.effect_payload(code))
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

    async def _establish_connection(
        self,
        address: str,
        preferred_driver_id: str | None,
        *,
        force_driver_id: str | None = None,
        offer_candidates: bool = False,
    ) -> DeviceConnection:
        """Find, connect to and identify a controller, returning a ready
        DeviceConnection. Shared by the primary connect path and (later)
        additional mirror devices. Raises on any failure (the caller cleans up).

        ``force_driver_id`` bypasses auto-detection and drives the device with a
        specific driver (used when the user accepts a "try as X" suggestion).
        When ``offer_candidates`` is set and nothing matches, the best safe guess
        is emitted via ``protocol_candidate_found`` before the unsupported error.
        """
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
        if driver is None and force_driver_id:
            # The user chose to try a specific driver on this unrecognised device.
            forced = get_driver_by_id(force_driver_id)
            if forced is not None and forced.pick_write_characteristic(services) is not None:
                driver = forced
        if driver is None:
            await client.disconnect()
            # Keep the full technical detail (services + characteristics) in the
            # diagnostics history for driver work, but show the user a friendly,
            # actionable line instead of the raw GATT dump.
            diagnostic = self._protocol_detection_diagnostic(device, services, preferred_driver_id)
            self._record_ble_history("protocol_mismatch", details=diagnostic)
            if offer_candidates and not force_driver_id:
                candidates = probe_driver_candidates(device.name or "", services)
                if candidates:
                    best = candidates[0]
                    self.protocol_candidate_found.emit(address, best.driver_id, best.display_name)
            raise ProtocolCompatibilityError(localization_manager.t("error.controller_unsupported"))
        driver.reset_runtime_state()
        if hasattr(driver, "configure_for_device"):
            driver.configure_for_device(device.name or "")
        driver.remember_brightness(self._last_brightness)
        characteristic = driver.pick_write_characteristic(services)
        if characteristic is None:
            await client.disconnect()
            raise RuntimeError("No writable GATT characteristic was found on this device.")
        return DeviceConnection(
            address=address,
            client=client,
            device=device,
            driver=driver,
            write_characteristic=characteristic,
            write_characteristics=driver.collect_write_characteristics(services),
        )

    # --- Mirror (multi-device) -------------------------------------------
    async def _restore_mirror(self, address: str) -> None:
        try:
            await self._add_mirror(address, quiet=True)
        except Exception:
            # Best effort by design — see restore_mirror_device().
            self.status_changed.emit(
                localization_manager.status_ble_event("mirror_unavailable", address=address)
            )
            # Nothing joined the set, but the UI still has to re-render so the
            # strip shows up as saved-but-unavailable.
            self.mirrors_changed.emit(self.mirror_addresses())

    async def _add_mirror(self, address: str, *, quiet: bool = False) -> None:
        if self._client is None:
            # A restore that lost its primary while queued must stay silent:
            # error_occurred puts a modal dialog on screen.
            if not quiet:
                self.error_occurred.emit(localization_manager.t("error.mirror_no_primary"))
            return
        primary_address = self._device.address if self._device is not None else ""
        if address == primary_address or any(conn.address == address for conn in self._mirror_connections):
            return
        hint = self._scan_driver_hints.get(address)
        conn = await self._establish_connection(address, hint)
        # The primary can drop (or be swapped) while this await was pending.
        # Attaching an extra to a setup that no longer exists would leave a
        # stray live link nothing drives, so hand it back instead.
        current_primary = self._device.address if self._device is not None else ""
        if self._client is None or current_primary != primary_address:
            try:
                await conn.client.disconnect()
            except Exception:
                pass
            return
        self._mirror_connections.append(conn)
        self.status_changed.emit(
            localization_manager.status_ble_event(
                "mirror_added",
                name=(conn.device.name or "").strip() or address,
                address=address,
            )
        )
        self.mirrors_changed.emit(self.mirror_addresses())
        await self._sync_mirror(conn)

    async def _remove_mirror(self, address: str) -> None:
        conn = next((c for c in self._mirror_connections if c.address == address), None)
        if conn is None:
            return
        self._mirror_connections.remove(conn)
        try:
            await conn.client.disconnect()
        except BLE_OPERATION_ERRORS:
            pass
        self.status_changed.emit(localization_manager.status_ble_event("mirror_removed", address=address))
        self.mirrors_changed.emit(self.mirror_addresses())

    async def _promote_mirror(self, address: str, *, keep_old_as_extra: bool = True) -> None:
        if self._client is None or self._device is None or self._driver is None:
            return
        # Park the live primary as a connection object so the swap is a plain
        # exchange of roles — no disconnect, no re-pairing, no flicker.
        current = DeviceConnection(
            address=self._primary_address(),
            client=self._client,
            device=self._device,
            driver=self._driver,
            write_characteristic=self._write_characteristic,
            write_characteristics=list(self._write_characteristics),
            preferred_payload_indices=dict(self._preferred_payload_indices),
            pacer=self._pacer,
        )
        swapped = swap_primary(current, list(self._mirror_connections), address)
        if swapped is None:
            return
        promoted, mirrors = swapped

        # "Switch" rather than "swap": drop the old primary from the mirror set
        # in the same operation, before any further light command can fan out.
        dropped = None
        if not keep_old_as_extra:
            mirrors = [conn for conn in mirrors if conn is not current]
            dropped = current

        self._mirror_connections = list(mirrors)
        self._client = promoted.client
        self._device = promoted.device
        self._driver = promoted.driver
        self._write_characteristic = promoted.write_characteristic
        self._write_characteristics = list(promoted.write_characteristics)
        self._preferred_payload_indices = dict(promoted.preferred_payload_indices)
        self._pacer = promoted.pacer
        # Reconnect must now chase the new main strip, not the old one.
        self._reconnect_address = promoted.address

        # Tear the dropped link down only after the roles are already in place,
        # so nothing can be written to it in between.
        if dropped is not None:
            try:
                await dropped.client.disconnect()
            except Exception:
                pass

        name = (promoted.device.name or "").strip() if promoted.device is not None else ""
        self.mirrors_changed.emit(self.mirror_addresses())
        self.primary_changed.emit(promoted.address, name)
        # Spell out what happened to the strip that used to be the main one —
        # "X is now primary" alone left users wondering why the other one still
        # lit up (it keeps mirroring) or went dark (it was dropped).
        old_name = (current.device.name or "").strip() if current.device is not None else ""
        self.status_changed.emit(
            localization_manager.status_ble_event(
                "primary_changed_kept" if keep_old_as_extra else "primary_changed_dropped",
                name=name or promoted.address,
                address=promoted.address,
                old_name=old_name or current.address,
            )
        )

    async def _disconnect_all_mirrors(self) -> None:
        mirrors = getattr(self, "_mirror_connections", None) or []
        self._mirror_connections = []
        for conn in mirrors:
            try:
                await conn.client.disconnect()
            except BLE_OPERATION_ERRORS:
                pass
        if mirrors:
            self.mirrors_changed.emit([])

    async def _sync_mirror(self, conn: DeviceConnection) -> None:
        """Bring a freshly added mirror in line with the current strip state."""
        try:
            if not self._desired_power_on:
                await self._mirror_write_payloads(conn, conn.driver.power_payloads(False))
                return
            await self._mirror_write_payloads(conn, conn.driver.power_payloads(True))
            await asyncio.sleep(0.1)
            await self._mirror_write_payloads(conn, conn.driver.brightness_payloads(self._last_brightness))
            await asyncio.sleep(0.06)
            if self._current_effect_code:
                payload = conn.driver.effect_payload(self._current_effect_code)
                if payload is not None:
                    await self._mirror_write_payloads(conn, [payload])
                    return
            await self._mirror_write_payloads(
                conn, conn.driver.color_payloads(self._last_red, self._last_green, self._last_blue)
            )
        except BLE_OPERATION_ERRORS + DRIVER_CAPABILITY_ERRORS:
            pass

    async def _fan_out(self, build, *, stream: bool = False) -> None:
        """Run ``build(driver)`` for each mirror and write the result. No-op (and
        zero cost) when there are no mirrors, so the single-device path is
        unaffected. ``build`` returns a payload, a list of variants, or None.
        """
        mirrors = getattr(self, "_mirror_connections", None)
        if not mirrors:
            return
        for conn in list(mirrors):
            try:
                result = build(conn.driver)
            except DRIVER_CAPABILITY_ERRORS:
                continue
            if result is None:
                continue
            if isinstance(result, (bytes, bytearray)):
                payloads = [bytes(result)]
            elif isinstance(result, (list, tuple)):
                payloads = [payload for payload in result if payload is not None]
            else:
                continue
            try:
                await self._mirror_write_payloads(conn, payloads, stream=stream)
            except BLE_OPERATION_ERRORS:
                continue

    async def _mirror_write_payloads(self, conn: DeviceConnection, payloads, *, stream: bool = False) -> bool:
        """Best-effort write of one payload variant to a mirror; failures swallowed.

        Returns True only when a write actually succeeded. Fire-and-forget
        callers ignore it, but a tracked command must not report success for a
        mirror that had nothing to send, no writable characteristic, or refused
        every attempt — the executor above trusts this verdict and cannot see
        past it.

        Paced on that mirror's own link unless this is a streaming/fade frame."""
        if not payloads:
            return False
        if not stream:
            wait = conn.pacer.reserve()
            if wait > 0:
                await asyncio.sleep(wait)
        for payload in payloads:
            for characteristic in self._connection_candidates(conn):
                properties = {prop.lower() for prop in characteristic.properties}
                prefer_response = "write" in properties and "write-without-response" not in properties
                if await self._write_attempt(characteristic, payload, prefer_response, client=conn.client) is None:
                    return True
                if await self._write_attempt(characteristic, payload, not prefer_response, client=conn.client) is None:
                    return True
        return False

    @staticmethod
    def _connection_candidates(conn: DeviceConnection) -> list:
        raw = conn.write_characteristics or ([conn.write_characteristic] if conn.write_characteristic is not None else [])
        ordered: list = []
        seen: set[str] = set()
        for characteristic in raw:
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

    async def _connect(self, address: str, *, from_reconnect: bool = False, force_driver_id: str | None = None) -> None:
        await self._disconnect(cancel_reconnect=not from_reconnect)
        preferred_driver_id = self._scan_driver_hints.get(address)
        connection = await self._establish_connection(
            address, preferred_driver_id, force_driver_id=force_driver_id, offer_candidates=True
        )

        self._client = connection.client
        self._device = connection.device
        self._driver = connection.driver
        self._write_characteristic = connection.write_characteristic
        self._write_characteristics = connection.write_characteristics
        self._reconnect_address = address
        self._manual_disconnect_requested = False
        self._clear_last_ble_error()
        # Fresh link: start timing this session and forget the old write pacing.
        self._session_started_at = time.monotonic()
        self._pacer.reset()
        self.connected_changed.emit(True, address)
        self.status_changed.emit(
            localization_manager.status_ble_event(
                "driver_selected",
                driver=connection.driver.display_name,
            )
        )
        self.status_changed.emit(
            localization_manager.status_ble_event(
                "connected_via",
                name=(connection.device.name or "").strip() or address,
                uuid=str(connection.write_characteristic.uuid),
            )
        )
        if self._write_characteristics:
            uuids = ", ".join(str(item.uuid) for item in self._write_characteristics)
            self.status_changed.emit(localization_manager.status_ble_event("candidate_characteristics", uuids=uuids))

    async def _disconnect(self, *, cancel_reconnect: bool = True) -> None:
        if cancel_reconnect:
            self._cancel_reconnect()
        await self._disconnect_all_mirrors()
        if self._client is not None:
            try:
                await self._client.disconnect()
            finally:
                self._close_session(manual=True)
                self._clear_connection_state()
                self.connected_changed.emit(False, "")
                self.status_changed.emit(localization_manager.status_ble_event("disconnected"))

    def _close_session(self, *, manual: bool) -> None:
        """Record how long the link lasted and why it ended. The duration feeds
        the adaptive reconnect backoff; the reason is shown to the user."""
        started = getattr(self, "_session_started_at", None)
        self._last_session_seconds = (time.monotonic() - started) if started is not None else None
        self._session_started_at = None
        self._last_disconnect_reason = classify_disconnect(
            manual=manual,
            error_text=getattr(self, "_last_ble_error", ""),
            session_seconds=self._last_session_seconds,
        )

    def last_disconnect_reason(self) -> str:
        """Stable reason code for the last dropped link ('' if never dropped)."""
        return getattr(self, "_last_disconnect_reason", "")

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
        if self._shutdown_started:
            return
        if client is self._client:
            if self._manual_disconnect_requested:
                return
            self._start_reconnect_after_connection_loss()
            return
        # A mirror dropped: forget it (no auto-reconnect for mirrors in v1).
        for conn in list(getattr(self, "_mirror_connections", None) or []):
            if conn.client is client:
                self._mirror_connections.remove(conn)
                self.status_changed.emit(localization_manager.status_ble_event("mirror_lost", address=conn.address))
                self.mirrors_changed.emit(self.mirror_addresses())
                return

    def _start_reconnect_after_connection_loss(self) -> None:
        if self._shutdown_started or self._manual_disconnect_requested:
            return
        device = self._device
        address = device.address if device is not None else self._reconnect_address
        name = (device.name or "").strip() if device is not None else ""
        if self._client is not None:
            self._close_session(manual=False)
            self._clear_connection_state()
            self.connected_changed.emit(False, "")
            self._set_last_ble_error("BLE connection was lost. Reconnecting to the last controller...")
            self.status_changed.emit(
                localization_manager.status_ble_event("unexpected_disconnect", name=name or address, address=address)
            )
        if address and (self._reconnect_task is None or self._reconnect_task.done()):
            self._reconnect_address = address
            self._reconnect_task = self._loop.create_task(self._reconnect(address))

    def _reconnect_delay(self, attempt: int) -> float:
        # Adaptive: a link that keeps dropping seconds after it reconnects backs
        # off faster, and jitter keeps several strips from retrying in lockstep.
        return reconnect_delay(
            attempt,
            last_session_seconds=getattr(self, "_last_session_seconds", None),
            jitter=RECONNECT_JITTER,
        )

    async def _reconnect(self, address: str) -> None:
        for attempt in range(1, RECONNECT_ATTEMPTS + 1):
            if self._shutdown_started or self._manual_disconnect_requested:
                return
            delay = self._reconnect_delay(attempt)
            self.reconnect_scheduled.emit(address, attempt, RECONNECT_ATTEMPTS, float(delay))
            await asyncio.sleep(delay)
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
            self.reconnect_succeeded.emit(address)
            await self._restore_state_after_reconnect()
            return
        self.status_changed.emit(localization_manager.status_ble_event("reconnect_give_up", address=address))
        self.reconnect_gave_up.emit(address)

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

    async def _write(self, payload: bytes, description: str, *, quiet: bool = False, stream: bool = False) -> None:
        if self._client is None or self._write_characteristic is None:
            raise RuntimeError("Connect to the LED strip first.")
        if not bool(getattr(self._client, "is_connected", True)):
            self._start_reconnect_after_connection_loss()
            self._set_last_ble_error("BLE connection was lost. Reconnecting to the last controller...")
            raise ConnectionLostError("BLE connection was lost. Reconnecting to the last controller...")

        # Pace discrete commands so cheap controllers don't get them back-to-back
        # (they silently drop or garble those). ``stream`` — not ``quiet`` — is the
        # exemption: streaming/fade frames already self-throttle by dropping
        # frames, and pacing them would cost smoothness. ``quiet`` only silences
        # the log, so quiet-but-discrete commands (scenes, addressed writes) are
        # still paced.
        if not stream:
            pacer = getattr(self, "_pacer", None)
            if pacer is None:
                pacer = WritePacer()
                self._pacer = pacer
            wait = pacer.reserve()
            if wait > 0:
                await asyncio.sleep(wait)

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

    async def _write_attempt(self, characteristic, payload: bytes, response: bool, *, client=None) -> Exception | None:
        """Single GATT write attempt. Returns None on success, exception on failure.

        ``client`` defaults to the primary connection; a mirror connection passes
        its own client so the same helper drives every controller.
        """
        target = client if client is not None else self._client
        if target is None:
            return ConnectionLostError("BLE connection was lost. Reconnecting to the last controller...")
        try:
            await asyncio.wait_for(
                target.write_gatt_char(characteristic, payload, response=response),
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

    async def _write_many(
        self, payloads: list[bytes], description: str, *, quiet: bool = False, stream: bool = False
    ) -> None:
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
                await self._write(payload, description, quiet=quiet, stream=stream)
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
