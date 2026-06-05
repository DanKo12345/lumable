from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, Signal


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


def _version_parts(version: str) -> tuple[int, ...]:
    text = version.strip().lower()
    if text.startswith("v"):
        text = text[1:]
    parts = [int(part) for part in re.findall(r"\d+", text)]
    return tuple(parts or [0])


def is_newer_version(latest: str, current: str) -> bool:
    latest_parts = list(_version_parts(latest))
    current_parts = list(_version_parts(current))
    width = max(len(latest_parts), len(current_parts))
    latest_parts.extend([0] * (width - len(latest_parts)))
    current_parts.extend([0] * (width - len(current_parts)))
    return tuple(latest_parts) > tuple(current_parts)


def parse_update_payload(payload: dict[str, Any] | list[Any], current_version: str, fallback_url: str = "") -> UpdateResult:
    if isinstance(payload, list):
        return _parse_release_list(payload, current_version, fallback_url)

    latest_version = str(payload.get("tag_name") or payload.get("version") or "").strip()
    if latest_version.startswith("v"):
        latest_version = latest_version[1:]
    if not latest_version:
        return UpdateResult("error", message="missing_version")

    url = str(
        payload.get("html_url")
        or payload.get("download_url")
        or payload.get("url")
        or fallback_url
        or ""
    ).strip()
    info = UpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        title=str(payload.get("name") or f"Version {latest_version}").strip(),
        url=url,
        notes=str(payload.get("body") or payload.get("notes") or "").strip(),
    )
    if is_newer_version(latest_version, current_version):
        return UpdateResult("available", info=info)
    return UpdateResult("current", info=info)


def _parse_release_list(payload: list[Any], current_version: str, fallback_url: str = "") -> UpdateResult:
    releases = [item for item in payload if isinstance(item, dict) and str(item.get("tag_name") or item.get("version") or "").strip()]
    if not releases:
        return UpdateResult("error", message="missing_version")
    latest_payload = max(
        releases,
        key=lambda item: _version_parts(str(item.get("tag_name") or item.get("version") or "")),
    )
    return parse_update_payload(latest_payload, current_version, fallback_url)


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
            with urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
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

    def _emit_finished(self, result: UpdateResult) -> None:
        try:
            self.finished.emit(result)
        except RuntimeError:
            # The application window can be closed while the background check is still finishing.
            pass
