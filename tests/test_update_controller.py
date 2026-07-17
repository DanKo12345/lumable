from __future__ import annotations

from app.update_checker import UpdateResult
from app.update_controller import UpdateController


class FakeButton:
    def __init__(self) -> None:
        self.enabled = True
        self.text = ""

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setText(self, text: str) -> None:
        self.text = text


class FakeHost:
    def __init__(self) -> None:
        self.check_update_button = FakeButton()
        self.logs: list[str] = []
        self._update_result = None
        self._settings = {
            "updates_last_auto_check_at": 0,
            "updates_last_auto_check_version": "",
            "updates_notified_version": "",
            "updates_notified_at": 0,
        }
        self.update_overlays: list[object] = []

    def _tr(self, key: str, **kwargs: object) -> str:
        if kwargs:
            args = ",".join(f"{name}={value}" for name, value in kwargs.items())
            return f"{key}:{args}"
        return key

    def _log(self, message: str) -> None:
        self.logs.append(message)

    def _show_update_overlay(self, info: object) -> None:
        self.update_overlays.append(info)


class RunningChecker:
    is_running = True
    is_configured = True

    def check(self) -> bool:
        raise AssertionError("manual click should not start another check while one is already running")


class ConfiguredChecker:
    is_running = False
    is_configured = True

    def __init__(self) -> None:
        self.check_calls = 0

    def check(self) -> bool:
        self.check_calls += 1
        return True


def test_silent_update_error_does_not_log_noise() -> None:
    host = FakeHost()
    controller = UpdateController(host, "0.1.1", "", "")
    controller._silent_check = True

    controller.handle_result(UpdateResult("error", message="HTTP Error 403: rate limit exceeded"))

    assert host.logs == []
    assert host.check_update_button.enabled is True
    assert host.check_update_button.text == "updates.check"


def test_manual_rate_limit_uses_friendly_message() -> None:
    host = FakeHost()
    controller = UpdateController(host, "0.1.1", "", "https://example.test/releases")

    controller.handle_result(UpdateResult("rate_limited", message="HTTP Error 403: rate limit exceeded"))

    assert host.logs == ["updates.rate_limited"]
    assert host.check_update_button.enabled is True
    assert host.check_update_button.text == "updates.open_releases"


def test_rate_limit_cooldown_opens_releases_without_new_log(monkeypatch) -> None:
    opened_urls: list[str] = []
    monkeypatch.setattr(
        "app.update_controller.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url.toString()) or True,
    )
    host = FakeHost()
    controller = UpdateController(host, "0.1.1", "", "https://example.test/releases")
    controller.handle_result(UpdateResult("rate_limited", message="HTTP Error 403: rate limit exceeded"))

    controller.check()

    assert opened_urls == ["https://example.test/releases"]
    assert host.logs == ["updates.rate_limited"]
    assert host.check_update_button.text == "updates.open_releases"


def test_manual_update_check_animates_button_text() -> None:
    host = FakeHost()
    controller = UpdateController(host, "0.1.1", "", "")

    controller._start_check_animation()
    assert host.check_update_button.text == "updates.checking"

    controller._tick_check_animation()
    assert host.check_update_button.text == "updates.checking."

    controller._tick_check_animation()
    assert host.check_update_button.text == "updates.checking.."


def test_manual_click_uses_running_background_check_animation() -> None:
    host = FakeHost()
    controller = UpdateController(host, "0.1.1", "", "")
    controller._checker = RunningChecker()
    controller._silent_check = True

    controller.check()

    assert controller._silent_check is False
    assert host.check_update_button.enabled is False
    assert host.check_update_button.text == "updates.checking"
    assert host.logs == ["updates.checking"]


def test_silent_update_check_skips_recent_attempt(monkeypatch) -> None:
    monkeypatch.setattr("app.update_controller.time", lambda: 2_000.0)
    host = FakeHost()
    host._settings.update({"updates_last_auto_check_at": 1_900, "updates_last_auto_check_version": "0.1.1"})
    controller = UpdateController(host, "0.1.1", "", "")
    checker = ConfiguredChecker()
    controller._checker = checker

    controller.check_silent()

    assert checker.check_calls == 0
    assert controller._silent_check is False


def test_silent_update_check_records_attempt(monkeypatch) -> None:
    saved_settings: list[dict[str, object]] = []
    monkeypatch.setattr("app.update_controller.time", lambda: 90_000.0)
    monkeypatch.setattr("app.update_controller.save_settings", lambda settings: saved_settings.append(dict(settings)))
    host = FakeHost()
    controller = UpdateController(host, "0.1.1", "", "")
    checker = ConfiguredChecker()
    controller._checker = checker

    controller.check_silent()

    assert checker.check_calls == 1
    assert host._settings["updates_last_auto_check_at"] == 90_000
    assert host._settings["updates_last_auto_check_version"] == "0.1.1"
    assert saved_settings == [host._settings]


def test_silent_update_check_runs_after_app_version_changes(monkeypatch) -> None:
    monkeypatch.setattr("app.update_controller.time", lambda: 2_000.0)
    host = FakeHost()
    host._settings.update({"updates_last_auto_check_at": 1_999, "updates_last_auto_check_version": "0.1.0"})
    controller = UpdateController(host, "0.1.1", "", "")
    checker = ConfiguredChecker()
    controller._checker = checker

    controller.check_silent()

    assert checker.check_calls == 1


def test_silent_update_check_ignores_future_timestamp(monkeypatch) -> None:
    monkeypatch.setattr("app.update_controller.time", lambda: 2_000.0)
    host = FakeHost()
    host._settings.update({"updates_last_auto_check_at": 9_999, "updates_last_auto_check_version": "0.1.1"})
    controller = UpdateController(host, "0.1.1", "", "")
    checker = ConfiguredChecker()
    controller._checker = checker

    controller.check_silent()

    assert checker.check_calls == 1


def test_update_reminder_reappears_after_a_day(monkeypatch) -> None:
    saved_settings: list[dict[str, object]] = []
    monkeypatch.setattr("app.update_controller.save_settings", lambda settings: saved_settings.append(dict(settings)))
    host = FakeHost()
    controller = UpdateController(host, "0.1.1", "", "")
    info = type("Info", (), {"latest_version": "0.2.0"})()

    monkeypatch.setattr("app.update_controller.time", lambda: 100_000.0)
    controller._notify_update(info, was_silent=True)
    controller._notify_update(info, was_silent=True)

    monkeypatch.setattr("app.update_controller.time", lambda: 100_000.0 + 24 * 60 * 60)
    controller._notify_update(info, was_silent=True)

    assert len(host.update_overlays) == 2
    assert len(saved_settings) == 2
