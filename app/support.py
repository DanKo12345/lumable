"""Pure helpers for device-compatibility support: the in-app catalog of
supported controllers and the prefilled GitHub issue used to report an
unsupported one. No Qt here so it stays easily testable."""

from __future__ import annotations

from urllib.parse import urlencode

from app.app_info import APP_VERSION

# Where "Report device" sends the user. The diagnostics report is copied to the
# clipboard separately; the issue body just prompts them to paste it, so the URL
# stays short (well under GitHub's length cap).
GITHUB_NEW_ISSUE_URL = "https://github.com/DanKo12345/lumable/issues/new"


def supported_controllers() -> list[dict[str, str]]:
    """The controller families LumaBLE speaks, built from the live driver list
    so it can never drift out of sync with what actually works."""
    from app.ble_drivers import DRIVERS  # lazy: keeps the URL builder bleak-free

    catalog: list[dict[str, str]] = []
    for driver in DRIVERS:
        tokens = tuple(getattr(driver, "name_tokens", ()) or ())
        aliases = ", ".join(dict.fromkeys(str(t).upper() for t in tokens if t))
        catalog.append(
            {
                "id": str(getattr(driver, "id", "")),
                "name": str(getattr(driver, "display_name", "")),
                "transport": str(getattr(driver, "transport", "BLE") or "BLE"),
                "aliases": aliases,
                "notes": str(getattr(driver, "protocol_notes", "") or ""),
            }
        )
    return catalog


def build_unsupported_report_url(
    *,
    device_name: str = "",
    driver_hint: str = "",
    base_url: str = GITHUB_NEW_ISSUE_URL,
) -> str:
    """Prefilled GitHub 'new issue' URL for reporting a controller LumaBLE
    doesn't support yet. Carries the app version and the device name; the full
    diagnostics report is copied to the clipboard by the caller, and the body
    prompts the user to paste it (kept out of the URL to avoid the length cap)."""
    name = (device_name or "").strip() or "unknown device"
    title = f"Add controller support: {name}"
    body_lines = [
        f"LumaBLE version: {APP_VERSION}",
        f"Device name: {name}",
    ]
    hint = (driver_hint or "").strip()
    if hint:
        body_lines.append(f"Detected protocol: {hint}")
    body_lines += [
        "",
        "The diagnostics report is on my clipboard — pasting it below:",
        "",
        "<paste diagnostics report here>",
    ]
    query = urlencode({"title": title, "body": "\n".join(body_lines)})
    return f"{base_url}?{query}"
