from __future__ import annotations

from app.app_info import APP_UPDATE_PRERELEASES
from app.update_checker import (
    canonical_version,
    is_newer_version,
    is_valid_version,
    parse_update_payload,
    parse_version,
)


def test_is_newer_version_compares_dotted_versions() -> None:
    assert is_newer_version("0.2.0", "0.1.9") is True
    assert is_newer_version("v1.10.0", "1.9.9") is True
    assert is_newer_version("1.0", "1.0.0") is False
    assert is_newer_version("1.0.0", "1.0.1") is False


def test_version_equality_ignores_trailing_zeros() -> None:
    # 1.0.0, 1.0 and 1 are the same release — comparison must not depend on how
    # many segments each side was written with.
    assert parse_version("1.0.0") == parse_version("1.0") == parse_version("1")
    assert is_newer_version("1.0.0", "1.0") is False
    assert is_newer_version("1.0", "1.0.0") is False


def test_all_zero_version_keeps_a_single_component() -> None:
    # Stripping trailing zeros must never empty the release tuple.
    key = parse_version("0.0.0")
    assert key.release == (0,)
    assert parse_version("0.0.0") == parse_version("0") == parse_version("0.0")
    assert is_newer_version("0.0.1", "0.0.0") is True


def test_canonical_version_keeps_unknown_prerelease_labels_distinct() -> None:
    # Skip ids must not collide: skipping "preview1" must not silence "nightly1".
    assert canonical_version("0.3.5-preview1") == "0.3.5-preview1"
    assert canonical_version("0.3.5-nightly1") == "0.3.5-nightly1"
    assert canonical_version("0.3.5-preview1") != canonical_version("0.3.5-nightly1")
    assert canonical_version("v0.3.5-beta+build7") == "0.3.5-beta0"


def test_build_metadata_does_not_affect_precedence() -> None:
    # +build is metadata, not a version component: its digits must not leak into
    # the release core and must never make a build look newer.
    assert parse_version("0.3.5+build2") == parse_version("0.3.5")
    assert parse_version("0.3.5+build2") == parse_version("0.3.5+build9")
    assert parse_version("0.3.5-beta2+build7") == parse_version("0.3.5-beta2")
    assert is_newer_version("0.3.5+build2", "0.3.5") is False
    assert is_valid_version("v0.3.5-beta2+build7") is True


def test_stable_release_outranks_its_own_prereleases() -> None:
    # The historical bug: a numeric prerelease suffix looked "newer" than the
    # final release. 0.3.5 must beat every 0.3.5-* build.
    assert is_newer_version("0.3.5", "0.3.5-beta") is True
    assert is_newer_version("0.3.5", "0.3.5-beta2") is True
    assert is_newer_version("0.3.5-beta2", "0.3.5") is False


def test_prerelease_stage_and_number_ordering() -> None:
    assert is_newer_version("0.3.5-rc1", "0.3.5-beta2") is True
    assert is_newer_version("0.3.5-beta2", "0.3.5-beta") is True
    assert parse_version("0.3.5-beta") == parse_version("0.3.5-beta0")


def test_unknown_prerelease_never_outranks_stable() -> None:
    assert is_newer_version("0.3.5-quux", "0.3.5") is False
    assert is_newer_version("0.3.6", "0.3.5-quux") is True


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


# --- 1.2 admission policy: draft / prerelease / malformed --------------------


def test_this_build_ships_as_beta_so_prereleases_are_allowed() -> None:
    # Documents the current build state; flipping it must be a conscious change.
    assert APP_UPDATE_PRERELEASES is True


def test_is_valid_version_rejects_non_version_tags() -> None:
    assert is_valid_version("v0.3.5-beta") is True
    assert is_valid_version("0.3.5") is True
    assert is_valid_version("banana") is False
    assert is_valid_version("") is False


def test_validator_only_accepts_prerelease_grammar_the_parser_can_split() -> None:
    # Supported forms — label, label+number, label.number:
    assert is_valid_version("0.3.5-beta") is True
    assert is_valid_version("0.3.5-beta2") is True
    assert is_valid_version("0.3.5-beta.2") is True
    # A dotted alphabetic tail collapses in canonical_version (preview.one and
    # preview.two would both become "preview0"), so the validator must reject it
    # rather than let two different releases share one skip id.
    assert is_valid_version("0.3.5-preview.one") is False
    assert is_valid_version("0.3.5-preview.two") is False


def test_overlong_tag_is_invalid_before_it_reaches_int() -> None:
    # A pathological numeric tag must be rejected up front, not parsed into a
    # gigantic integer.
    assert is_valid_version("1" * 100) is False
    result = parse_update_payload({"tag_name": "1" * 100}, "0.3.4")
    assert result.state == "error"


def test_prereleases_offered_when_the_build_allows_them() -> None:
    # The beta chain: a 0.3.4 user must be offered 0.3.5-beta.
    result = parse_update_payload(
        [
            {"tag_name": "v0.3.5-beta", "prerelease": True, "html_url": "https://x/beta"},
            {"tag_name": "v0.3.4", "html_url": "https://x/stable"},
        ],
        "0.3.4",
        allow_prereleases=True,
    )
    assert result.state == "available"
    assert result.info is not None
    assert result.info.latest_version == "0.3.5-beta"


def test_prereleases_ignored_when_the_build_forbids_them() -> None:
    # A stable-only build skips the beta and offers the newest stable instead.
    result = parse_update_payload(
        [
            {"tag_name": "v0.3.6-beta", "prerelease": True, "html_url": "https://x/beta"},
            {"tag_name": "v0.3.5", "html_url": "https://x/stable"},
        ],
        "0.3.4",
        allow_prereleases=False,
    )
    assert result.state == "available"
    assert result.info is not None
    assert result.info.latest_version == "0.3.5"


def test_draft_releases_are_never_offered() -> None:
    result = parse_update_payload(
        [
            {"tag_name": "v0.9.0", "draft": True, "html_url": "https://x/draft"},
            {"tag_name": "v0.3.5", "html_url": "https://x/stable"},
        ],
        "0.3.4",
        allow_prereleases=True,
    )
    assert result.state == "available"
    assert result.info is not None
    assert result.info.latest_version == "0.3.5"


def test_all_malformed_releases_are_an_error() -> None:
    result = parse_update_payload(
        [{"tag_name": "banana"}, {"tag_name": "not-a-version"}],
        "0.3.4",
    )
    assert result.state == "error"


def test_valid_releases_all_filtered_by_policy_are_current_not_error() -> None:
    # A real release exists but policy rules it out — that's "up to date", and
    # the result must carry UpdateInfo so the controller doesn't call it invalid.
    result = parse_update_payload(
        [{"tag_name": "v0.3.5-beta", "prerelease": True, "html_url": "https://x/beta"}],
        "0.3.4",
        allow_prereleases=False,
    )
    assert result.state == "current"
    assert result.info is not None
    assert result.info.current_version == "0.3.4"


def test_single_malformed_release_is_an_error() -> None:
    result = parse_update_payload({"tag_name": "banana"}, "0.3.4")
    assert result.state == "error"


def test_single_draft_release_is_current_with_info() -> None:
    result = parse_update_payload(
        {"tag_name": "v0.9.0", "draft": True, "html_url": "https://x/draft"},
        "0.3.4",
        allow_prereleases=True,
    )
    assert result.state == "current"
    assert result.info is not None
    assert result.info.current_version == "0.3.4"
