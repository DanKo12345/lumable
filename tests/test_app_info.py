from __future__ import annotations

import tomllib
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.app_info import (
    APP_AUTHOR,
    APP_AUTHOR_SIGNATURE,
    APP_CHECKOUT_URL,
    APP_RELEASES_URL,
    APP_UPDATE_URL,
    APP_VERSION,
)
from app.crash_logging import _build_exception_report, _display_path
from app.widgets import AuthorSignatureMark


def test_author_metadata_is_consistent() -> None:
    assert APP_AUTHOR == "dollza"
    assert APP_AUTHOR_SIGNATURE == "by dollza"
    assert APP_UPDATE_URL == "https://api.github.com/repos/DanKo12345/lumable/releases"
    assert APP_RELEASES_URL == "https://github.com/DanKo12345/lumable/releases"
    assert APP_CHECKOUT_URL == "https://rgb-controller-dollza.lemonsqueezy.com/checkout/buy/53482924-7a40-488a-adff-e59bb7a58eac"


def test_window_icon_asset_exists() -> None:
    icon_path = Path(__file__).resolve().parents[1] / "app" / "assets" / "icon.ico"

    assert icon_path.exists()
    assert icon_path.stat().st_size > 0


def test_release_version_is_consistent_across_build_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    installer = (root / "installer" / "LumaBLE.iss").read_text(encoding="utf-8")
    version_info = (root / "build" / "version_info.txt").read_text(encoding="utf-8")

    assert project["project"]["version"] == APP_VERSION
    assert f'#define MyAppVersion "{APP_VERSION}"' in installer
    assert f"StringStruct('FileVersion', '{APP_VERSION}')" in version_info
    assert f"StringStruct('ProductVersion', '{APP_VERSION}')" in version_info


def test_author_signature_mark_uses_shared_signature() -> None:
    app = QApplication.instance() or QApplication([])
    mark = AuthorSignatureMark(lambda: {"muted": "rgba(255,255,255,0.5)", "text": "#ffffff"})

    assert APP_AUTHOR_SIGNATURE == "by dollza"
    assert APP_VERSION == "0.3.5"
    mark.set_edition("Free", "Current app edition")
    assert mark.edition_label.text() == "Free"
    assert not hasattr(mark, "version_label")
    assert mark.sizeHint().width() >= 64
    assert mark.sizeHint().height() >= 40
    app.processEvents()


def test_crash_report_contains_author_metadata() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError as error:
        report = _build_exception_report(type(error), error, error.__traceback__, context="test")

    assert "Application: LumaBLE" in report
    assert "Author: dollza" in report
    assert "Copyright" not in report


def test_crash_report_paths_are_home_relative(monkeypatch) -> None:
    class FakeHomePath:
        @staticmethod
        def home():
            return "C:\\Users\\ExampleUser"

    monkeypatch.setattr("app.crash_logging.Path", FakeHomePath)

    assert _display_path("C:\\Users\\ExampleUser\\Documents\\New project") == "~\\Documents\\New project"
