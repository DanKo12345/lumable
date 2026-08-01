"""One description of what the device card should show, computed in one place.

The card has to say five different things — supported, unknown, checking, error,
connected — and each of them is a combination of connection flags, the selected
scan result and the driver that claimed it. Deciding that inside the widget
would spread the same conditions across a dozen `setText` calls and let them
drift apart.

So the panel asks this module once and renders what it gets back. Everything
here is plain data: no Qt, no BLE, no translation. Labels are keys, resolved at
draw time like every other string in the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The five things the card can be saying.
STATE_IDLE = "idle"  # nothing found yet
STATE_SCANNING = "scanning"
STATE_SUPPORTED = "supported"  # a driver claims the selected device
STATE_UNKNOWN = "unknown"  # found, but no driver claims it
STATE_CHECKING = "checking"  # a read-only compatibility check is running
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_ERROR = "error"


@dataclass(frozen=True)
class DeviceViewState:
    """What to draw. Every field is either a translation key or plain data."""

    state: str = STATE_IDLE
    title_key: str = "device.status.not_connected"
    # Free text that is *not* translated: a device name, an address, a count.
    detail: str = ""
    driver_name: str = ""
    signal_rssi: int | None = None
    # Which action the primary button offers right now.
    action_key: str = "device.connect"
    action_enabled: bool = False
    # Rows of "label key -> value" for the capability list; empty means hide it.
    facts: tuple[tuple[str, str], ...] = field(default=())

    @property
    def is_unknown(self) -> bool:
        return self.state == STATE_UNKNOWN

    @property
    def is_busy(self) -> bool:
        return self.state in (STATE_SCANNING, STATE_CONNECTING, STATE_CHECKING)


def _as_signal(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _signal_of(device: dict[str, Any]) -> int | None:
    return _as_signal(device.get("rssi", ""))


def describe_device(
    *,
    connected: bool = False,
    scanning: bool = False,
    connecting: bool = False,
    checking: bool = False,
    error: str = "",
    selected: dict[str, Any] | None = None,
    connected_name: str = "",
    driver_name: str = "",
    connected_rssi: Any = None,
    capabilities: dict[str, Any] | None = None,
) -> DeviceViewState:
    """Fold every flag into the single thing the card should say.

    Order matters and encodes the priority the user expects: what is happening
    now beats what was found, and an error beats a stale success.
    """
    if connected:
        return DeviceViewState(
            state=STATE_CONNECTED,
            title_key="device.status.connected",
            detail=connected_name,
            driver_name=driver_name,
            signal_rssi=_as_signal(connected_rssi),
            action_key="device.disconnect",
            action_enabled=True,
            facts=_capability_facts(capabilities),
        )
    if checking:
        return DeviceViewState(
            state=STATE_CHECKING,
            title_key="device.status.checking",
            detail=(selected or {}).get("name", ""),
            action_key="device.inspect_running",
            action_enabled=False,
        )
    if connecting:
        return DeviceViewState(
            state=STATE_CONNECTING,
            title_key="device.status.connecting",
            detail=(selected or {}).get("name", ""),
            action_key="device.connect",
            action_enabled=False,
        )
    if scanning:
        return DeviceViewState(
            state=STATE_SCANNING, title_key="device.status.scanning", action_enabled=False
        )
    if error:
        # Carried as plain text: it is already a finished, human sentence, and
        # translating it again here would mean inventing a key per failure.
        return DeviceViewState(
            state=STATE_ERROR,
            title_key="device.status.problem",
            detail=error,
            action_key="device.connect",
            action_enabled=bool(selected),
        )
    if selected is None:
        return DeviceViewState()

    if selected.get("supported", True) is False:
        return DeviceViewState(
            state=STATE_UNKNOWN,
            title_key="device.status.unknown_selected",
            detail=str(selected.get("name", "")),
            signal_rssi=_signal_of(selected),
            action_key="device.inspect",
            action_enabled=True,
        )
    return DeviceViewState(
        state=STATE_SUPPORTED,
        title_key="device.status.supported_selected",
        detail=str(selected.get("name", "")),
        driver_name=str(selected.get("driver", "")),
        signal_rssi=_signal_of(selected),
        action_key="device.connect",
        action_enabled=True,
    )


def _capability_facts(capabilities: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    """What the connected controller can do, as label-key/value pairs.

    Only what is actually known: a controller that reports nothing shows no
    list at all rather than a column of dashes.
    """
    if not capabilities:
        return ()
    facts: list[tuple[str, str]] = []
    for key, label in (
        ("power", "device.fact.power"),
        ("color", "device.fact.color"),
        ("brightness", "device.fact.brightness"),
        ("effects", "device.fact.effects"),
    ):
        value = capabilities.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            facts.append((label, "device.fact.yes" if value else "device.fact.no"))
        else:
            facts.append((label, str(value)))
    return tuple(facts)
