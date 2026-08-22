from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, Signal

from app.app_info import APP_UPDATE_PRERELEASES

_TRANSIENT_HTTP_CODES = frozenset({502, 503, 504})
_RETRY_DELAYS_S = (0.25, 0.75)


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    title: str
    url: str
    notes: str = ""


@dataclass(frozen=True)
class UpdateResult:
    state: str
    info: UpdateInfo | None = None
    message: str = ""


# Prerelease stages in ascending precedence. Anything unrecognised sorts below
# the known stages (rank -1) but — because ``stable`` is compared first — never
# above a final release of the same core version.
_PRE_STAGE_RANK = {"alpha": 0, "beta": 1, "rc": 2}


@dataclass(frozen=True, order=True)
class VersionKey:
    """A comparable version identity. Field order IS the precedence order:
    numeric core first, then final-over-prerelease, then prerelease stage, then
    the trailing prerelease number. ``0.3.5`` beats ``0.3.5-beta2`` because
    ``stable`` (1 vs 0) is weighed before the prerelease fields."""

    release: tuple[int, ...]
    stable: int
    pre_stage: int
    pre_num: int


def _parse_parts(tag: str) -> tuple[tuple[int, ...], bool, str, int]:
    """Split a tag into (release, is_prerelease, prerelease_label, number).
    The label is kept verbatim so callers that need identity (not just ordering)
    can tell ``preview1`` from ``nightly1``."""
    text = str(tag).strip().lower()
    if text.startswith("v"):
        text = text[1:]
    # Build metadata (+build) never participates in precedence or identity, so
    # drop it before anything else — otherwise its digits would leak into core.
    text, _, _build = text.partition("+")
    core, _, pre = text.partition("-")
    nums = [int(part) for part in re.findall(r"\d+", core)] or [0]
    # Canonicalise so 1.0.0 == 1.0 == 1: drop insignificant trailing zeros,
    # keeping at least one component. Comparison no longer depends on how many
    # segments the *other* version happens to have.
    while len(nums) > 1 and nums[-1] == 0:
        nums.pop()
    release = tuple(nums)
    if not pre:
        return release, False, "", 0
    match = re.match(r"([a-z]+)?\.?(\d+)?", pre)
    label = (match.group(1) or "") if match else ""
    number = int(match.group(2)) if (match and match.group(2)) else 0
    return release, True, label, number


def parse_version(tag: str) -> VersionKey:
    release, is_pre, label, number = _parse_parts(tag)
    if not is_pre:
        return VersionKey(release, 1, 0, 0)
    return VersionKey(release, 0, _PRE_STAGE_RANK.get(label, -1), number)


def is_newer_version(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def canonical_version(tag: str) -> str:
    """A stable identity string for a version, used to remember a skipped
    release. Build metadata is dropped and trailing zeros normalised, while the
    prerelease label and number are kept verbatim — so ``beta``, ``beta2``,
    ``rc1``, ``preview1``, ``nightly1`` and the final release never collapse
    into the same skip id."""
    release, is_pre, label, number = _parse_parts(tag)
    core = ".".join(str(part) for part in release)
    if not is_pre:
        return core
    return f"{core}-{label or 'pre'}{number}"


# A supported version tag: optional leading "v", dotted numbers, an optional
# -prerelease and an optional +build suffix (both may appear together). It must
# match in full — "banana" has no numeric core and is not a version.
#
# The prerelease grammar is deliberately limited to what ``_parse_parts`` can
# actually distinguish: a label optionally followed by a number (``beta``,
# ``beta2``, ``beta.2``). A dotted alphabetic tail like ``preview.one`` is
# rejected here rather than silently collapsing to the same canonical id later.
_MAX_TAG_LENGTH = 64
_VERSION_RE = re.compile(r"v?\d+(?:\.\d+)*(?:-[a-z]+(?:\.?\d+)?)?(?:\+[0-9a-z.]+)?", re.IGNORECASE)


def is_valid_version(tag: str) -> bool:
    text = str(tag).strip()
    # Bound the length before any parsing so an absurd numeric tag can never
    # reach int() on a huge string.
    if not text or len(text) > _MAX_TAG_LENGTH:
        return False
    return bool(_VERSION_RE.fullmatch(text))


def _tag_of(payload: dict[str, Any]) -> str:
    return str(payload.get("tag_name") or payload.get("version") or "").strip()


def _display_version(tag: str) -> str:
    return tag[1:] if tag[:1].lower() == "v" else tag


def _is_admissible(payload: dict[str, Any], allow_prereleases: bool) -> bool:
    # A draft is never offered; a prerelease only when the build opts in.
    if payload.get("draft") is True:
        return False
    return allow_prereleases or payload.get("prerelease") is not True


def _build_info(payload: dict[str, Any], current_version: str, tag: str, fallback_url: str) -> UpdateInfo:
    latest_version = _display_version(tag)
    url = str(
        payload.get("html_url")
        or payload.get("download_url")
        or payload.get("url")
        or fallback_url
        or ""
    ).strip()
    return UpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        title=str(payload.get("name") or f"Version {latest_version}").strip(),
        url=url,
        notes=str(payload.get("body") or payload.get("notes") or "").strip(),
    )


def _current_result(current_version: str, fallback_url: str = "") -> UpdateResult:
    # ``current`` must still carry an UpdateInfo: the controller reads a missing
    # info as a corrupted response, so "you're up to date" (an empty-but-valid
    # release list) must not look like an error.
    return UpdateResult(
        "current",
        info=UpdateInfo(
            current_version=current_version,
            latest_version=current_version,
            title="",
            url=fallback_url.strip(),
        ),
    )


def _decide(payload: dict[str, Any], current_version: str, tag: str, fallback_url: str) -> UpdateResult:
    info = _build_info(payload, current_version, tag, fallback_url)
    if is_newer_version(tag, current_version):
        return UpdateResult("available", info=info)
    return UpdateResult("current", info=info)


def parse_update_payload(
    payload: dict[str, Any] | list[Any],
    current_version: str,
    fallback_url: str = "",
    *,
    allow_prereleases: bool | None = None,
) -> UpdateResult:
    if allow_prereleases is None:
        allow_prereleases = APP_UPDATE_PRERELEASES
    if isinstance(payload, list):
        return _parse_release_list(payload, current_version, fallback_url, allow_prereleases=allow_prereleases)

    tag = _tag_of(payload)
    if not is_valid_version(tag):
        return UpdateResult("error", message="missing_version")
    if not _is_admissible(payload, allow_prereleases):
        return _current_result(current_version, fallback_url)
    return _decide(payload, current_version, tag, fallback_url)


def _parse_release_list(
    payload: list[Any],
    current_version: str,
    fallback_url: str = "",
    *,
    allow_prereleases: bool | None = None,
) -> UpdateResult:
    if allow_prereleases is None:
        allow_prereleases = APP_UPDATE_PRERELEASES
    # Only genuinely valid versions decide error-vs-current. If *none* parse, the
    # response is malformed (error). If some parse but the admission policy
    # (draft always out, prerelease by build flag) filters them all, we are
    # simply up to date (current) — not an error.
    valid: list[tuple[dict[str, Any], str]] = []
    for item in payload:
        if isinstance(item, dict):
            tag = _tag_of(item)
            if is_valid_version(tag):
                valid.append((item, tag))
    if not valid:
        return UpdateResult("error", message="missing_version")
    admissible = [(item, tag) for item, tag in valid if _is_admissible(item, allow_prereleases)]
    if not admissible:
        return _current_result(current_version, fallback_url)
    latest_item, latest_tag = max(admissible, key=lambda pair: parse_version(pair[1]))
    return _decide(latest_item, current_version, latest_tag, fallback_url)


class UpdateChecker(QObject):
    finished = Signal(object)

    def __init__(self, current_version: str, update_url: str = "", fallback_url: str = "") -> None:
        super().__init__()
        self._current_version = current_version
        self._update_url = update_url.strip()
        self._fallback_url = fallback_url.strip()
        self._running = False

    @property
    def is_configured(self) -> bool:
        return bool(self._update_url)

    @property
    def is_running(self) -> bool:
        return self._running

    def check(self) -> bool:
        if self._running:
            return False
        if not self._update_url:
            self.finished.emit(UpdateResult("disabled", message="not_configured"))
            return True
        self._running = True
        thread = threading.Thread(target=self._run_check, daemon=True)
        thread.start()
        return True

    def _run_check(self) -> None:
        try:
            request = Request(
                self._update_url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": f"LumaBLE/{self._current_version}",
                },
            )
            payload = self._fetch_payload(request)
            if not isinstance(payload, (dict, list)):
                result = UpdateResult("error", message="invalid_response")
            else:
                result = parse_update_payload(payload, self._current_version, self._fallback_url)
        except HTTPError as exc:
            result = UpdateResult("rate_limited" if exc.code == 403 else "error", message=str(exc))
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            result = UpdateResult("error", message=str(exc))
        finally:
            self._running = False
        self._emit_finished(result)

    @staticmethod
    def _fetch_payload(request: Request) -> Any:
        for attempt in range(len(_RETRY_DELAYS_S) + 1):
            try:
                with urlopen(request, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code not in _TRANSIENT_HTTP_CODES or attempt >= len(_RETRY_DELAYS_S):
                    raise
                time.sleep(_RETRY_DELAYS_S[attempt])
        raise RuntimeError("unreachable")

    def _emit_finished(self, result: UpdateResult) -> None:
        try:
            self.finished.emit(result)
        except RuntimeError:
            # The application window can be closed while the background check is still finishing.
            pass
