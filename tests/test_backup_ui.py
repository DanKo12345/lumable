"""Restoring from the window: the order of the steps, and the way out.

The dangerous part is not writing the file. It is what the app does afterwards
while still holding the world that was replaced — so the tests here are about
sequence and about the fact that every way of dismissing the result closes the
app rather than returning to it.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from app import storage
from app.backup import build_backup
from app.backup_controller import BackupController
from app.widgets import BackupRestoreResultOverlay


class _Host:
    """Only what the controller touches."""

    def __init__(self, settings: dict) -> None:
        self._settings = settings
        self.errors: list[str] = []
        self.logs: list[str] = []
        self.asked: list[str] = []
        self.shown: list[dict] = []
        self.proceed = None

    def _tr(self, key: str, **kwargs) -> str:
        return f"{key}:{kwargs}" if kwargs else key

    def _show_error(self, message: str) -> None:
        self.errors.append(message)

    def _log(self, message: str) -> None:
        self.logs.append(message)

    def _confirm_restore(self, title: str, _body: str, proceed) -> None:
        self.asked.append(title)
        self.proceed = proceed

    def _show_backup_done(self, labels: dict) -> None:
        self.shown.append(labels)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(storage, "PROFILES_PATH", tmp_path / "profiles.json")
    monkeypatch.setattr(storage, "_legacy_migration_pairs", lambda: [])
    monkeypatch.setattr(storage, "_migration_done", False)
    monkeypatch.setattr(storage, "_writes_frozen", False)
    settings_path.write_text(json.dumps({"scenes": [{"name": "Old"}]}), encoding="utf-8")
    return settings_path


def _payload() -> dict:
    return build_backup(
        {
            "scenes": [{"scene_id": "s1", "name": "Read"}],
            "automations": {"enabled": True, "rules": [{"id": "r1"}]},
            "device_groups": [{"group_id": "g1", "name": "Desk", "members": ["AA:BB"]}],
        }
    )["data"]


def test_a_restore_replaces_the_file_and_shuts_the_door(store) -> None:
    host = _Host({"scenes": [{"name": "Old"}]})
    controller = BackupController(host)

    assert controller.apply_backup(_payload()) is True

    written = json.loads(store.read_text(encoding="utf-8"))
    assert written["scenes"][0]["name"] == "Read"
    assert storage.settings_writes_frozen()
    assert controller.restored()


def test_the_app_cannot_write_its_old_world_back_afterwards(store) -> None:
    """The failure this exists to prevent: the app closes, a controller saves
    the settings it has held since start-up, and by the next launch the restore
    is gone."""
    controller = BackupController(_Host({"scenes": [{"name": "Old"}]}))
    controller.apply_backup(_payload())

    storage.save_settings({"scenes": [{"name": "Old"}]})

    assert json.loads(store.read_text(encoding="utf-8"))["scenes"][0]["name"] == "Read"


def test_a_failed_write_changes_nothing_and_keeps_the_app_usable(store) -> None:
    host = _Host({"scenes": []})
    controller = BackupController(host)

    def explode(_path, _payload):
        raise OSError("disk full")

    original = storage._write_json
    storage._write_json = explode
    try:
        assert controller.apply_backup(_payload()) is False
    finally:
        storage._write_json = original

    assert host.errors, "the failure has to be said out loud"
    assert not controller.restored()
    assert not storage.settings_writes_frozen()
    assert json.loads(store.read_text(encoding="utf-8"))["scenes"][0]["name"] == "Old"


def test_the_result_says_which_groups_still_need_strips(store) -> None:
    host = _Host({})
    BackupController(host).apply_backup(_payload())

    labels = host.shown[0]
    assert labels["groups"], "a silent group is a group that lights nothing"
    assert labels["copy"], "the safety copy is worth nothing if nobody is told where it is"
    assert labels["restart"]
    assert labels["close"]


def test_no_group_left_hanging_means_no_warning(store) -> None:
    payload = _payload()
    payload["device_groups"] = []

    host = _Host({})
    BackupController(host).apply_backup(payload)

    assert host.shown[0]["groups"] == ""


def test_the_question_comes_before_the_file_is_touched(store) -> None:
    """After the replacement there is nothing left to cancel, so the offer to
    stop has to come first."""
    host = _Host({})
    controller = BackupController(host)
    document = json.dumps(build_backup({"scenes": [], "automations": {}}))
    path = store.parent / "backup.json"
    path.write_text(document, encoding="utf-8")

    from PySide6.QtWidgets import QFileDialog

    original = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(path), ""))
    try:
        controller.import_backup()
    finally:
        QFileDialog.getOpenFileName = original

    assert host.asked, "the user was never asked"
    assert not controller.restored(), "nothing may happen before the answer"
    assert json.loads(store.read_text(encoding="utf-8"))["scenes"][0]["name"] == "Old"

    host.proceed()
    assert controller.restored()


def test_a_refused_file_is_named_by_its_reason(store) -> None:
    host = _Host({})
    controller = BackupController(host)
    path = store.parent / "junk.json"
    path.write_text("not json", encoding="utf-8")

    from PySide6.QtWidgets import QFileDialog

    original = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(path), ""))
    try:
        controller.import_backup()
    finally:
        QFileDialog.getOpenFileName = original

    assert host.errors == ["backup.refused_unreadable"]
    assert not host.asked, "a file that cannot be used is not worth a question"


# ── the result overlay ────────────────────────────────────────────────
def _overlay():
    from PySide6.QtWidgets import QWidget

    QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(900, 600)
    overlay = BackupRestoreResultOverlay(
        {
            "title": "Settings restored",
            "summary": "12 scenes and 4 automations are back.",
            "groups": "2 groups need their strips assigned again.",
            "copy": "Kept as settings-before-restore.json",
            "restart": "To apply the settings, open LumaBLE again.",
            "close": "Close LumaBLE",
        },
        parent,
    )
    overlay.open()
    QApplication.instance().processEvents()
    return parent, overlay


def test_the_button_is_the_way_out() -> None:
    _parent, overlay = _overlay()
    asked: list[bool] = []
    overlay.close_requested.connect(lambda: asked.append(True))

    overlay.close_button.click()

    assert asked == [True]


def test_escape_does_not_return_to_a_world_that_is_gone() -> None:
    """Dismissing this would leave the app running on settings that no longer
    exist — which is exactly what the restore was avoiding."""
    _parent, overlay = _overlay()
    asked: list[bool] = []
    overlay.close_requested.connect(lambda: asked.append(True))

    overlay.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))

    assert asked == [True]


def test_a_click_on_the_backdrop_means_the_same_thing() -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    _parent, overlay = _overlay()
    asked: list[bool] = []
    overlay.close_requested.connect(lambda: asked.append(True))

    overlay.mousePressEvent(
        QMouseEvent(
            QMouseEvent.MouseButtonPress,
            QPointF(3.0, 3.0),
            QPointF(3.0, 3.0),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )

    assert asked == [True]


def test_everything_it_says_is_available_to_a_screen_reader() -> None:
    _parent, overlay = _overlay()

    described = overlay.accessibleDescription()
    for part in ("Settings restored", "groups need their strips", "open LumaBLE again"):
        assert part in described


def test_the_message_scrolls_but_the_button_never_leaves() -> None:
    """The first version of this test fed the labels a 400-character word, which
    cannot be wrapped and so was rendered on one line — it passed while real
    Russian sentences were being clipped. Measured with text that wraps, and at
    the smallest window the app allows."""
    from PySide6.QtWidgets import QWidget

    QApplication.instance() or QApplication([])
    sentence = (
        "Группам нужно назначить ленты заново, потому что адреса устройств "
        "никогда не попадают в резервную копию. "
    )
    for width, height in ((900, 700), (860, 420)):
        parent = QWidget()
        parent.resize(width, height)
        parent.show()
        QApplication.instance().processEvents()
        overlay = BackupRestoreResultOverlay(
            {
                "title": "Настройки восстановлены",
                "summary": sentence * 4,
                "groups": sentence * 4,
                "copy": "Прежние настройки сохранены как settings-before-restore.json",
                "restart": "Чтобы применить настройки, откройте LumaBLE снова.",
                "close": "Закрыть LumaBLE",
            },
            parent,
        )
        overlay.open()
        QApplication.instance().processEvents()
        QApplication.instance().processEvents()

        panel = overlay._panel
        button = overlay.close_button
        assert panel.height() <= panel.maximumHeight(), (width, height)
        assert panel.height() <= parent.height(), (width, height)
        assert button.y() + button.height() <= panel.height(), (
            f"the only way out was pushed off the panel at {width}x{height}"
        )
        parent.close()


def test_ordinary_text_needs_no_scrolling() -> None:
    """The scroll area is for the worst case; the everyday one should just fit."""
    from PySide6.QtWidgets import QWidget

    QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(900, 700)
    parent.show()
    QApplication.instance().processEvents()
    overlay = BackupRestoreResultOverlay(
        {
            "title": "Настройки восстановлены",
            "summary": "12 сцен и 4 автоматизации вернулись.",
            "groups": "2 группам нужно назначить ленты заново.",
            "copy": "Прежние настройки сохранены как settings-before-restore.json",
            "restart": "Чтобы применить настройки, откройте LumaBLE снова.",
            "close": "Закрыть LumaBLE",
        },
        parent,
    )
    overlay.open()
    QApplication.instance().processEvents()
    QApplication.instance().processEvents()

    bar = overlay._scroll.verticalScrollBar()
    assert bar.maximum() == 0, "the usual message should not need scrolling"
