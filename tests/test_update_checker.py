from __future__ import annotations

from app.update_checker import is_newer_version, parse_update_payload


def test_is_newer_version_compares_dotted_versions() -> None:
    assert is_newer_version("0.2.0", "0.1.9") is True
    assert is_newer_version("v1.10.0", "1.9.9") is True
    assert is_newer_version("1.0", "1.0.0") is False
    assert is_newer_version("1.0.0", "1.0.1") is False


def test_parse_update_payload_accepts_github_latest_release_shape() -> None:
    result = parse_update_payload(
        {
            "tag_name": "v0.2.0",
            "name": "LumaBLE 0.2.0",
            "html_url": "https://example.test/releases/v0.2.0",
            "body": "Release notes",
        },
        "0.1.0",
    )

    assert result.state == "available"
    assert result.info is not None
    assert result.info.latest_version == "0.2.0"
    assert result.info.url == "https://example.test/releases/v0.2.0"


def test_parse_update_payload_accepts_github_release_list_with_prereleases() -> None:
    result = parse_update_payload(
        [
            {
                "tag_name": "v0.1.1",
                "name": "LumaBLE 0.1.1 beta",
                "html_url": "https://example.test/releases/v0.1.1",
                "prerelease": True,
            },
            {
                "tag_name": "v0.1.0",
                "name": "LumaBLE 0.1.0 beta",
                "html_url": "https://example.test/releases/v0.1.0",
                "prerelease": True,
            },
        ],
        "0.1.0",
    )

    assert result.state == "available"
    assert result.info is not None
    assert result.info.latest_version == "0.1.1"
    assert result.info.url == "https://example.test/releases/v0.1.1"


def test_parse_update_payload_reports_current_version() -> None:
    result = parse_update_payload({"version": "0.1.0", "url": "https://example.test"}, "0.1.0")

    assert result.state == "current"
    assert result.info is not None
    assert result.info.current_version == "0.1.0"


def test_parse_update_payload_rejects_missing_version() -> None:
    result = parse_update_payload({"name": "No version"}, "0.1.0")

    assert result.state == "error"
