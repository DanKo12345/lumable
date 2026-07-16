from __future__ import annotations

from app.local_api import config as api_config
from app.local_api.config import (
    DEFAULT_PORT,
    LAN_WARNING_MAX_SHOWN,
    detect_lan_ip,
    generate_token,
    is_loopback,
    resolve_bind_host,
    validate_api_settings,
)


class _FakeSock:
    def __init__(self, name, *, fail=False):
        self._name = name
        self._fail = fail

    def connect(self, _addr):
        if self._fail:
            raise OSError("offline")

    def getsockname(self):
        return self._name

    def close(self):
        pass


def test_defaults_are_safe() -> None:
    cfg = validate_api_settings(None)
    assert cfg["enabled"] is False
    assert cfg["allow_lan"] is False
    assert cfg["lan_confirmed"] is False
    assert cfg["lan_warning_count"] == 0
    assert cfg["port"] == DEFAULT_PORT
    assert cfg["token"] == ""
    assert cfg["lan_host"] == ""


def test_port_is_clamped_to_valid_range() -> None:
    assert validate_api_settings({"port": 70000})["port"] == DEFAULT_PORT
    assert validate_api_settings({"port": "nope"})["port"] == DEFAULT_PORT
    assert validate_api_settings({"port": 8080})["port"] == 8080


def test_bind_host_defaults_to_loopback() -> None:
    assert resolve_bind_host(validate_api_settings({})) == "127.0.0.1"


def test_lan_requires_flag_and_specific_host() -> None:
    # Flag on but no host -> still loopback.
    assert resolve_bind_host(validate_api_settings({"allow_lan": True})) == "127.0.0.1"
    # Flag on with a concrete IP -> that IP.
    cfg = validate_api_settings(
        {"allow_lan": True, "lan_confirmed": True, "lan_host": "192.168.1.50"}
    )
    assert resolve_bind_host(cfg) == "192.168.1.50"
    # Host set but flag off -> loopback.
    assert resolve_bind_host(validate_api_settings({"lan_host": "192.168.1.50"})) == "127.0.0.1"


def test_lan_never_binds_all_interfaces_implicitly() -> None:
    cfg = validate_api_settings({"allow_lan": True, "lan_confirmed": True, "lan_host": "0.0.0.0"})
    assert resolve_bind_host(cfg) == "127.0.0.1"


def test_legacy_lan_setting_requires_explicit_confirmation() -> None:
    cfg = validate_api_settings({"allow_lan": True, "lan_host": "192.168.1.50"})

    assert cfg["allow_lan"] is False
    assert resolve_bind_host(cfg) == "127.0.0.1"


def test_lan_warning_count_is_clamped() -> None:
    assert validate_api_settings({"lan_warning_count": -1})["lan_warning_count"] == 0
    assert validate_api_settings({"lan_warning_count": 999})["lan_warning_count"] == LAN_WARNING_MAX_SHOWN


def test_generate_token_is_nonempty_and_unique() -> None:
    a, b = generate_token(), generate_token()
    assert a and b and a != b
    assert len(a) >= 16


def test_is_loopback() -> None:
    assert is_loopback("127.0.0.1")
    assert is_loopback("localhost")
    assert not is_loopback("192.168.1.5")


def test_detect_lan_ip_returns_outbound_address(monkeypatch) -> None:
    monkeypatch.setattr(api_config.socket, "socket", lambda *a, **k: _FakeSock(("192.168.1.77", 5)))
    assert detect_lan_ip() == "192.168.1.77"


def test_detect_lan_ip_offline_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(api_config.socket, "socket", lambda *a, **k: _FakeSock(("0.0.0.0", 0), fail=True))
    assert detect_lan_ip() == ""


def test_detect_lan_ip_ignores_loopback(monkeypatch) -> None:
    monkeypatch.setattr(api_config.socket, "socket", lambda *a, **k: _FakeSock(("127.0.0.1", 0)))
    assert detect_lan_ip() == ""
