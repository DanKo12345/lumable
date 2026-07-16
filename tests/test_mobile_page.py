from __future__ import annotations

from app.local_api.mobile_page import build_mobile_page


def test_mobile_page_embeds_requested_labels_and_language() -> None:
    page = build_mobile_page(
        {"brightness": "Luminosite", "pair_connect": "Connecter"}, language="fr"
    )

    assert '<html lang="fr">' in page
    assert '"brightness": "Luminosite"' in page
    assert '"pair_connect": "Connecter"' in page
    assert "__TEXT__" not in page


def test_mobile_page_keeps_fallback_labels_for_partial_translation() -> None:
    page = build_mobile_page({"brightness": "Helligkeit"})

    assert '"brightness": "Helligkeit"' in page
    assert '"power_on": "On"' in page


def test_mobile_page_includes_expandable_full_colour_palette() -> None:
    page = build_mobile_page(
        {
            "custom_colour": "Any colour",
            "open_palette": "Open palette",
            "close_palette": "Close palette",
        }
    )

    assert 'id="paletteToggle"' in page
    assert 'id="sv"' in page
    assert 'id="hue"' in page
    assert "function togglePalette()" in page
    assert "function setHue(value)" in page
    assert 'aria-expanded="false"' in page
    assert ".picker.open" in page
    assert "prefers-reduced-motion" in page
    assert '"custom_colour": "Any colour"' in page


def test_mobile_page_uses_sse_with_polling_fallback() -> None:
    page = build_mobile_page()

    # Live updates come over SSE (fetch stream on /events); polling is the fallback.
    assert 'fetch("/events"' in page
    assert "function startLive()" in page
    assert "function startPolling()" in page
    assert "ReadableStream" in page
    assert "setInterval(" in page  # the fallback poller is still present


def test_mobile_page_has_quiet_status_and_recent_colours() -> None:
    page = build_mobile_page({"sent": "Sent!", "send_failed": "Offline", "recent_colours": "Lately"})

    assert '"sent": "Sent!"' in page
    assert '"send_failed": "Offline"' in page
    assert '"recent_colours": "Lately"' in page
    assert 'id="toast"' in page          # non-modal command feedback
    assert 'id="recent"' in page         # recent-colours row
    assert "function pushRecent(" in page
    assert 'id="deviceName"' in page     # active strip name in the header


def test_mobile_page_has_pc_modes_with_active_state() -> None:
    page = build_mobile_page(
        {
            "pc_modes": "PC hub",
            "pc_screen": "Screen sync",
            "pc_active": "running",
            "all_off": "All off",
            "mode_unavailable": "Needs Pro or a strip",
        }
    )

    # Controls the PC's live modes, not just the strip — the real differentiator.
    assert 'fetch' in page and '/pc-mode' in page
    assert "async function pcMode(" in page
    assert "async function masterOff(" in page
    assert 'id="pcModes"' in page
    assert 'id="pcActive"' in page          # "<mode> active" + Stop
    assert '"pc_modes": "PC hub"' in page
    assert '"pc_screen": "Screen sync"' in page
    assert '"all_off": "All off"' in page
    # A refused start (HTTP 409) shows a specific reason, not a generic error.
    assert "error.status === 409" in page
    assert '"mode_unavailable": "Needs Pro or a strip"' in page
    assert "pc_mode_detail" in page  # shows which effect is running, not just "Effect"
