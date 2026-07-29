"""The advisory lock automations serialise on.

Both platform locks are per-handle, so a second handle stands for another process
just as well as another process does — and testing it that way needs no subprocess.
"""

from __future__ import annotations

import sys
from pathlib import Path
from time import monotonic

from app.automation.file_lock import file_lock, locking_available

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_a_second_holder_is_turned_away_rather_than_left_waiting(tmp_path) -> None:
    if not locking_available():  # pragma: no cover - every supported platform has one
        return
    path = tmp_path / "automation.lock"

    with file_lock(path, timeout=0.0) as first:
        assert first is True
        started = monotonic()
        with file_lock(path, timeout=0.2) as second:
            assert second is False, "two runs held the execution lock at once"
        # It waited for its turn before giving up, rather than failing instantly or
        # blocking for ever.
        assert 0.15 <= monotonic() - started < 5.0


def test_the_lock_is_free_again_afterwards(tmp_path) -> None:
    path = tmp_path / "automation.lock"

    with file_lock(path, timeout=0.0) as first:
        assert first is True
    with file_lock(path, timeout=0.0) as second:
        assert second is True, "the lock was not released"


def test_the_lock_file_and_its_directory_are_created(tmp_path) -> None:
    path = tmp_path / "nested" / "automation.lock"

    with file_lock(path, timeout=0.0) as locked:
        assert locked is True
    assert path.exists()


def test_an_unusable_path_is_reported_not_raised(tmp_path) -> None:
    """A lock that cannot be opened must not take the automation down with it: the
    caller decides whether to go on."""
    path = tmp_path / "automation.lock"
    path.mkdir()  # a directory where the lock file should be

    with file_lock(path, timeout=0.0) as locked:
        assert locked is False


def test_the_lock_is_released_even_when_the_body_raises(tmp_path) -> None:
    path = tmp_path / "automation.lock"

    try:
        with file_lock(path, timeout=0.0) as locked:
            assert locked is True
            raise RuntimeError("the run blew up")
    except RuntimeError:
        pass

    with file_lock(path, timeout=0.0) as again:
        assert again is True


_CHILD = """
import sys
from pathlib import Path
from time import monotonic, sleep

sys.path.insert(0, sys.argv[1])
from app.automation.file_lock import file_lock

lock_path, ready, stop = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
with file_lock(lock_path, timeout=5.0) as locked:
    ready.write_text("locked" if locked else "failed", encoding="utf-8")
    deadline = monotonic() + 10.0
    while not stop.exists() and monotonic() < deadline:
        sleep(0.05)
"""


def test_a_real_second_process_is_kept_out(tmp_path) -> None:
    """The rest of the suite stands in for another process with another handle, which
    is what the platform locks actually key on. This one is a genuine second OS
    process, because "two LumaBLE processes" is the situation the lock exists for.
    """
    if not locking_available():  # pragma: no cover - every supported platform has one
        return
    import subprocess
    from time import sleep

    lock_path = tmp_path / "automation.lock"
    ready, stop = tmp_path / "ready", tmp_path / "stop"
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(REPO_ROOT), str(lock_path), str(ready), str(stop)]
    )
    try:
        deadline = monotonic() + 30.0
        while not ready.exists() and monotonic() < deadline:
            assert child.poll() is None, "the child process died before taking the lock"
            sleep(0.05)
        assert ready.read_text(encoding="utf-8") == "locked", "the child never took the lock"

        with file_lock(lock_path, timeout=0.3) as ours:
            assert ours is False, "two processes held the execution lock at once"
    finally:
        stop.write_text("go", encoding="utf-8")
        child.wait(timeout=30)

    # And it is ours the moment the other process lets go.
    with file_lock(lock_path, timeout=1.0) as after:
        assert after is True
