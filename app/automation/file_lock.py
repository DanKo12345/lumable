"""One writer at a time, across processes.

Automations are the first part of LumaBLE where two *processes* touch the same
files: a Windows task starts a headless LumaBLE while the app may already be
running, and several tasks can come due together after the machine wakes. Within
one process Qt keeps everything on one thread; across processes nothing does.

Advisory locks on a small lock file, because that is what both platforms offer
without a dependency: ``msvcrt.locking`` on Windows, ``flock`` elsewhere. Both are
per-handle, so a second handle — in this process or another — waits.

Failure to lock is reported, never raised. "Someone else is already doing it" is a
normal outcome for an automation task, and the caller is the only one that knows
whether that means "skip" or "give up on this write".
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep
from typing import IO, Any

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - not Windows
    msvcrt = None  # type: ignore[assignment]

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

POLL_SECONDS = 0.05
# One byte at offset 0. The region need not exist in the file: both platforms lock
# a range, not content, so an empty lock file is enough.
_LOCK_BYTES = 1


class ProcessLock:
    """An exclusive lock held for as long as the work takes.

    The context manager below covers the common case — take it, do something, let
    it go. This is for work that outlives the call that starts it: the app runs a
    BLE write asynchronously and must keep the lock until the *result* arrives, or a
    task's process would start the same rule in the gap.

    Not reentrant, and deliberately so: a second handle on the same file waits for
    the first even within one process, which is exactly what makes it work across
    processes. Whoever takes it must release it on every path out.
    """

    __slots__ = ("_handle", "_path")

    def __init__(self, path: Any) -> None:
        self._path = path
        self._handle: IO[bytes] | None = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self, timeout: float = 0.0) -> bool:
        """Take the lock, waiting up to ``timeout``. False if someone else has it."""
        if self._handle is not None:
            return True
        handle = _open(self._path)
        if handle is None:
            return False
        if not _acquire(handle, timeout):
            _close(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        """Give the lock up. Safe to call when it was never taken."""
        handle, self._handle = self._handle, None
        if handle is None:
            return
        _release(handle)
        _close(handle)


@contextmanager
def file_lock(path: Any, *, timeout: float) -> Iterator[bool]:
    """Hold an exclusive lock on ``path``, yielding whether it was taken.

    Yields ``False`` — rather than raising — when the lock is still held elsewhere
    after ``timeout`` seconds, or when the lock file cannot be opened at all. A
    caller that must not act without it checks the value; one for which a lost
    write is merely unfortunate can carry on.
    """
    lock = ProcessLock(path)
    acquired = lock.acquire(timeout)
    try:
        yield acquired
    finally:
        lock.release()


def _close(handle: IO[bytes]) -> None:
    try:
        handle.close()
    except OSError:  # pragma: no cover - closing a lock file rarely fails
        pass


def locking_available() -> bool:
    """False when this interpreter offers no advisory locking at all.

    Then :func:`file_lock` yields True without protecting anything: refusing to
    run automations would be a worse answer than running them unserialised, but
    the caller may want to say so.
    """
    return msvcrt is not None or fcntl is not None


def _open(path: Any) -> IO[bytes] | None:
    try:
        lock_path = Path(path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Append mode: opening must never truncate a lock another process holds.
        return open(lock_path, "a+b")
    except OSError:
        return None


def _acquire(handle: IO[bytes], timeout: float) -> bool:
    deadline = monotonic() + max(0.0, float(timeout))
    while True:
        if _try_lock(handle):
            return True
        if monotonic() >= deadline:
            return False
        sleep(POLL_SECONDS)


def _try_lock(handle: IO[bytes]) -> bool:
    if not locking_available():  # pragma: no cover - both modules missing
        return True
    try:
        handle.seek(0)  # msvcrt locks at the current position, and "a+b" is at the end
        if msvcrt is not None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, _LOCK_BYTES)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _release(handle: IO[bytes]) -> None:
    try:
        handle.seek(0)
        if msvcrt is not None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _LOCK_BYTES)
        elif fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:  # pragma: no cover - the handle is closed right after
        pass
