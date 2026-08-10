"""Saving a backup, and putting one back.

The file work is in :mod:`app.backup` and :mod:`app.storage`; this is the part
that talks to a person. Two things shape it.

A restore replaces the settings file while the app is still holding the old
world in memory. There is no attempt to reload it: controllers keep references
to nested dictionaries that are no longer what is on disk, and chasing every one
of them is a much larger promise than "your backup is back". So the settings
file is replaced, writing is frozen where writing happens, and the app is shut
down — the next launch reads the restored file and everything is simply true.

And the point of no return is announced before it is reached, not after. Once
the file has been replaced there is nothing to cancel, so the offer to stop
comes first and the only button afterwards is the one that closes the app.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog

from app.app_info import APP_VERSION
from app.backup import build_backup, inspect_backup, restore_into
from app.storage import restore_settings_file

_SUFFIX = ".lumable.json"


class BackupController:
    """Export and import, and the shutdown a successful import ends with."""

    def __init__(self, host: Any) -> None:
        self._host = host
        self._restored = False

    # ── export ────────────────────────────────────────────────────────
    def export_backup(self) -> None:
        host = self._host
        default_name = f"lumable-backup-{APP_VERSION}{_SUFFIX}"
        path, _filter = QFileDialog.getSaveFileName(
            host,
            host._tr("backup.export_title"),
            str(Path.home() / "Desktop" / default_name),
            host._tr("backup.file_filter"),
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += _SUFFIX
        document = build_backup(self._settings(), app_version=APP_VERSION)
        try:
            Path(path).write_text(
                json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            host._show_error(host._tr("backup.export_error", error=str(exc)))
            return
        host._log(host._tr("backup.exported", path=Path(path).name))

    # ── import ────────────────────────────────────────────────────────
    def import_backup(self) -> None:
        host = self._host
        path, _filter = QFileDialog.getOpenFileName(
            host,
            host._tr("backup.import_title"),
            str(Path.home() / "Desktop"),
            host._tr("backup.file_filter"),
        )
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            host._show_error(host._tr("backup.import_error", error=str(exc)))
            return

        # The whole file is judged before anything is touched, so a refusal
        # costs the user nothing but a message.
        check = inspect_backup(raw)
        if not check.ok:
            host._show_error(host._tr(f"backup.refused_{check.error}"))
            return

        # Asked before the file is replaced, because afterwards there is
        # nothing left to cancel. The overlay answers by signal, like every
        # other confirmation in the app.
        self._ask(check.counts, lambda: self.apply_backup(check.payload))

    def apply_backup(self, payload: dict[str, Any]) -> bool:
        """Replace the settings with a checked backup and close the app.

        Public and separate from the dialogs so the sequence itself can be
        exercised: this is the part where getting the order wrong loses data.
        """
        host = self._host
        restored, report = restore_into(self._settings(), payload)
        try:
            kept = restore_settings_file(restored)
        except (OSError, TimeoutError) as exc:
            # Nothing was replaced and writing is not frozen: the app carries on
            # with exactly what it had.
            host._show_error(host._tr("backup.import_error", error=str(exc)))
            return False

        self._restored = True
        host._log(
            host._tr(
                "backup.restored_log",
                scenes=report.counts.get("scenes", 0),
                rules=report.counts.get("automations", 0),
            )
        )
        self._announce(report, kept)
        return True

    def restored(self) -> bool:
        """Whether a restore has happened, so the window can refuse to save."""
        return self._restored

    # ── the parts a test replaces ─────────────────────────────────────
    def _settings(self) -> dict[str, Any]:
        settings = self._host._settings
        return settings if isinstance(settings, dict) else {}

    def _ask(self, counts: dict[str, int], proceed) -> None:
        host = self._host
        host._confirm_restore(
            host._tr("backup.confirm_title"),
            host._tr(
                "backup.confirm_body",
                scenes=counts.get("scenes", 0),
                rules=counts.get("automations", 0),
            ),
            proceed,
        )

    def _announce(self, report, kept: Path | None) -> None:
        """What was restored, what still needs doing, and the one way out."""
        host = self._host
        host._show_backup_done(
            {
                "title": host._tr("backup.done_title"),
                "summary": host._tr(
                    "backup.done_body",
                    scenes=report.counts.get("scenes", 0),
                    rules=report.counts.get("automations", 0),
                ),
                # Its own line: the groups are back by name and light nothing
                # until strips are assigned to them again, and that is the one
                # thing here the user still has to do.
                "groups": (
                    host._tr("backup.done_groups", count=report.groups_need_strips)
                    if report.groups_need_strips
                    else ""
                ),
                "copy": host._tr("backup.done_copy", path=kept.name) if kept is not None else "",
                "restart": host._tr("backup.done_restart"),
                "close": host._tr("backup.done_close"),
            }
        )
