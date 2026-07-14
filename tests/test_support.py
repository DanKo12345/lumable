from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from app.app_info import APP_VERSION
from app.support import (
    GITHUB_NEW_ISSUE_URL,
    build_unsupported_report_url,
    supported_controllers,
)


def test_catalog_lists_the_known_families() -> None:
    pytest.importorskip("bleak")
    catalog = supported_controllers()
    names = {entry["name"] for entry in catalog}
    # The four controller families LumaBLE ships drivers for.
    assert {"BLEDOM", "BanlanX", "Magic Home BLE", "Triones"} <= names
    for entry in catalog:
        assert entry["name"]
        assert entry["transport"]
        assert "id" in entry and "aliases" in entry and "notes" in entry


def test_catalog_aliases_come_from_driver_tokens() -> None:
    pytest.importorskip("bleak")
    bledom = next(e for e in supported_controllers() if e["id"] == "bledom")
    assert "BLEDOM" in bledom["aliases"]
    assert "ELK-BLEDOM" in bledom["aliases"]


def test_report_url_targets_github_issues() -> None:
    url = build_unsupported_report_url(device_name="ELK-BLEDOM")
    assert url.startswith(GITHUB_NEW_ISSUE_URL + "?")
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert "ELK-BLEDOM" in query["title"][0]
    body = query["body"][0]
    assert APP_VERSION in body
    assert "ELK-BLEDOM" in body


def test_report_url_includes_driver_hint_when_given() -> None:
    url = build_unsupported_report_url(device_name="Gadget", driver_hint="looks like Triones")
    body = parse_qs(urlsplit(url).query)["body"][0]
    assert "looks like Triones" in body


def test_report_url_falls_back_for_blank_name() -> None:
    url = build_unsupported_report_url(device_name="   ")
    query = parse_qs(urlsplit(url).query)
    assert "unknown device" in query["title"][0]


def test_report_url_respects_custom_base() -> None:
    url = build_unsupported_report_url(device_name="X", base_url="https://example.test/new")
    assert url.startswith("https://example.test/new?")
