from __future__ import annotations

from app import startup_controller


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeWinreg:
    HKEY_CURRENT_USER = object()
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def OpenKey(self, *_args):
        return _FakeKey()

    def QueryValueEx(self, _key, name: str):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, _key, name: str, _reserved: int, _kind: int, value: str) -> None:
        self.values[name] = value

    def DeleteValue(self, _key, name: str) -> None:
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def test_startup_enabled_roundtrip(monkeypatch) -> None:
    fake = _FakeWinreg()
    monkeypatch.setattr(startup_controller.os, "name", "nt")
    monkeypatch.setitem(__import__("sys").modules, "winreg", fake)
    monkeypatch.setattr(startup_controller, "_startup_command", lambda: '"LumaBLE.exe"')

    assert startup_controller.is_startup_enabled() is False

    startup_controller.set_startup_enabled(True)

    assert fake.values["LumaBLE"] == '"LumaBLE.exe"'
    assert startup_controller.is_startup_enabled() is True

    startup_controller.set_startup_enabled(False)

    assert startup_controller.is_startup_enabled() is False


def test_startup_unsupported_platform_raises(monkeypatch) -> None:
    monkeypatch.setattr(startup_controller.os, "name", "posix")

    try:
        startup_controller.set_startup_enabled(True)
    except OSError as exc:
        assert "not supported" in str(exc)
    else:
        raise AssertionError("Expected OSError")


def test_schedule_tasks_create_and_delete(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.delenv("LUMABLE_DISABLE_SCHTASKS", raising=False)
    monkeypatch.setattr(startup_controller.os, "name", "nt")
    monkeypatch.setattr(startup_controller, "_scheduled_action_command", lambda action: f'"LumaBLE.exe" --scheduled-action {action}')
    monkeypatch.setattr(startup_controller, "_run_schtasks", lambda args, allow_missing=False: calls.append(tuple(args)) or True)

    startup_controller.set_schedule_tasks_enabled(True, on_time="19:00", off_time="23:15")
    startup_controller.set_schedule_tasks_enabled(False, on_time="19:00", off_time="23:15")

    assert calls[0] == (
        "/Create",
        "/F",
        "/TN",
        "LumaBLE Schedule On",
        "/SC",
        "DAILY",
        "/ST",
        "19:00",
        "/TR",
        '"LumaBLE.exe" --scheduled-action on',
    )
    assert calls[1][7] == "23:15"
    assert calls[2] == ("/Delete", "/F", "/TN", "LumaBLE Schedule On")
    assert calls[3] == ("/Delete", "/F", "/TN", "LumaBLE Schedule Off")


def test_schedule_tasks_disable_is_noop_on_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(startup_controller.os, "name", "posix")

    startup_controller.set_schedule_tasks_enabled(False, on_time="19:00", off_time="23:00")
