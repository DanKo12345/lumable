"""The 'Report device' action must copy the diagnostics to the clipboard and
open a prefilled GitHub issue. Clipboard and browser are mocked so no real
system services are touched."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import app.diagnostics_controller as dc
from app.diagnostics_controller import DiagnosticsController
from app.support import GITHUB_NEW_ISSUE_URL


class _Clipboard:
    def __init__(self) -> None:
        self.text: str | None = None

    def setText(self, text: str) -> None:
        self.text = text


class _FakeQApplication:
    _clip = _Clipboard()

    @classmethod
    def clipboard(cls) -> _Clipboard:
        return cls._clip


class _Ble:
    def diagnostics_snapshot(self) -> dict:
        return {"device": {"name": "ELK-BLEDOM", "address": "AA:BB"}, "driver": {"name": "BLEDOM"}}


class _Host:
    def __init__(self) -> None:
        self._ble = _Ble()
        self._settings: dict = {}
        self.logs: list[str] = []

    def _tr(self, key: str, **_kw: object) -> str:
        return key

    def _log(self, message: str) -> None:
        self.logs.append(message)


def test_report_unsupported_copies_report_and_opens_prefilled_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: dict[str, str] = {}
    monkeypatch.setattr(dc, "QApplication", _FakeQApplication)
    monkeypatch.setattr(
        dc.QDesktopServices,
        "openUrl",
        staticmethod(lambda url: bool(opened.__setitem__("url", url.toString()))),
    )
    # Don't depend on the full report format here — this test is about the wiring.
    monkeypatch.setattr(DiagnosticsController, "text", lambda self, include_crashes=False: "DIAGNOSTICS REPORT")

    ctrl = DiagnosticsController(_Host())
    ctrl.report_unsupported()

    # Diagnostics landed on the clipboard for pasting into the issue.
    assert _FakeQApplication._clip.text == "DIAGNOSTICS REPORT"
    # Browser opened a prefilled GitHub issue carrying the device name.
    assert opened["url"].startswith(GITHUB_NEW_ISSUE_URL)
    assert "ELK-BLEDOM" in opened["url"]
