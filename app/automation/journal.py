"""What the automation engine did, and what it declined to do.

Kept in its own file rather than in ``settings.json``: entries are written far
more often than settings, and a corrupt or half-written journal must never cost
the user their configuration.

Stored as stable codes, never as localised text. The journal outlives a language
change, and a line written in Russian would still read in Russian after the user
switches to English.

Repeats of the *same* skip collapse into one row with a count. Successes and
errors never collapse: each one is a distinct thing that happened to the light.

**Two processes write here.** A Windows task runs a headless LumaBLE while the app
may be open, so a flush is not "write my list": it takes a lock, re-reads what is
on disk, merges, and writes the union. Anything else and the last writer would
silently delete the other's history. The temporary file is per-process for the
same reason — two processes sharing one ``.tmp`` name corrupt each other's write.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from app.automation.file_lock import file_lock

KIND_SUCCESS = "success"
KIND_SKIPPED = "skipped"
KIND_ERROR = "error"
# Its own kind rather than an error: the user taking over is not a fault, and a
# journal that paints it red would train them to ignore real failures.
KIND_CANCELLED = "cancelled"

_KINDS = (KIND_SUCCESS, KIND_SKIPPED, KIND_ERROR, KIND_CANCELLED)

MAX_ENTRIES = 300
FLUSH_INTERVAL_SECONDS = 5.0
# Short on purpose: a flush that cannot get the lock keeps its entries and tries
# again, so waiting longer would only stall whoever is writing.
LOCK_TIMEOUT_SECONDS = 3.0
# Two strips going offline a week apart are two events, not one row that has
# been "happening" for seven days. Past this gap the same skip starts afresh.
COLLAPSE_WINDOW_SECONDS = 5 * 60.0

# Only these context fields identify *which* situation a skip is about. The rest
# (retry_at, paused_until) move on every tick and would defeat collapsing.
_KEY_CONTEXT_FIELDS = ("winner_rule_id", "scene_id", "target")


@dataclass(frozen=True)
class JournalEntry:
    id: int
    kind: str
    rule_id: str
    reason: str = ""
    message_code: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    count: int = 1
    occurred_at: datetime | None = None
    decided_at: datetime | None = None
    # What makes this entry itself, for merging two processes' views. ``id`` cannot
    # serve: each process numbers from what it last read, so the same number stands
    # for different events. Nor can the fields — a rule that fails twice in the same
    # second produces two entries that differ in nothing a reader can see, and
    # treating those as one would quietly drop half the story.
    uid: str = ""
    # Count last read from or written to disk by this journal instance. Not
    # serialised: it is the baseline that lets flush merge this process's delta
    # with increments another process committed in the meantime.
    persisted_count: int = field(default=0, compare=False, repr=False)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat(timespec="seconds")


def _parse_iso(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _derived_uid(item: dict[str, Any]) -> str:
    """A uid for an entry written before entries had one.

    Derived from the fields rather than random, so reading the same file twice does
    not turn one entry into two. Two entries that are genuinely indistinguishable
    will collide — the price of a file that predates the field, and only ever paid
    for a journal written by a development build.
    """
    seed = "|".join(
        str(item.get(name, "")) for name in ("kind", "rule_id", "reason", "message_code", "first_seen")
    )
    return "legacy-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def _more_recent(candidate: JournalEntry, current: JournalEntry) -> bool:
    """Which copy carries the latest moving context and timestamp."""
    if candidate.last_seen != current.last_seen:
        if candidate.last_seen is None:
            return False
        if current.last_seen is None:
            return True
        return candidate.last_seen > current.last_seen
    return candidate.count > current.count


def _merge_entries(
    disk: list[JournalEntry], mine: list[JournalEntry], max_entries: int
) -> list[JournalEntry]:
    """The union of two views of the journal, in time order and renumbered.

    Entries are matched by uid, so nothing is deduplicated that a reader could tell
    apart. For a collapsed skip, this process's increment since its last disk view
    is added to the latest on-disk count. Ids are handed out again at the end: they
    only order the list for the reader, and two processes' numbering cannot be
    reconciled otherwise.
    """
    by_uid = {entry.uid: entry for entry in disk}
    for entry in mine:
        current = by_uid.get(entry.uid)
        if current is None:
            by_uid[entry.uid] = entry
            continue

        # Both processes can load count=1 and independently collapse one more
        # occurrence into count=2. Taking max would persist 2, although three
        # events happened. Add only this instance's change since its last disk
        # baseline to the current on-disk count.
        local_delta = max(0, entry.count - entry.persisted_count)
        recent = entry if _more_recent(entry, current) else current
        first_seen_values = [value for value in (entry.first_seen, current.first_seen) if value]
        last_seen_values = [value for value in (entry.last_seen, current.last_seen) if value]
        by_uid[entry.uid] = replace(
            recent,
            count=current.count + local_delta,
            first_seen=min(first_seen_values) if first_seen_values else None,
            last_seen=max(last_seen_values) if last_seen_values else None,
        )
    ordered = sorted(by_uid.values(), key=_chronological)
    ordered = ordered[-max(1, int(max_entries)) :]
    return [
        replace(entry, id=index, persisted_count=entry.count)
        for index, entry in enumerate(ordered, start=1)
    ]


def _chronological(entry: JournalEntry) -> tuple:
    # A missing timestamp sorts first: an entry from a damaged file keeps its place
    # at the back of the history rather than jumping to the front of the list. The
    # uid only breaks a complete tie, so the order cannot depend on dict iteration.
    return (entry.first_seen or datetime.min, entry.id, entry.uid)


def _collapse_key(rule_id: str, reason: str, context: dict[str, Any]) -> tuple:
    """Structural, not ``str(dict)``: key order must not decide identity."""
    return (
        rule_id,
        reason,
        *((name, context.get(name)) for name in _KEY_CONTEXT_FIELDS if context.get(name) is not None),
    )


class AutomationJournal:
    """In-memory log with a debounced, atomic write behind it.

    It owns no timer on purpose. ``record_*`` only touches memory; the caller
    already ticks and decides when to ``flush``. That keeps the journal free of
    Qt and makes every test deterministic.
    """

    def __init__(
        self,
        path: Path,
        *,
        max_entries: int = MAX_ENTRIES,
        flush_interval: float = FLUSH_INTERVAL_SECONDS,
        collapse_window: float = COLLAPSE_WINDOW_SECONDS,
        lock_timeout: float = LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self._path = Path(path)
        self._max_entries = max(1, int(max_entries))
        self._flush_interval = float(flush_interval)
        self._collapse_window = float(collapse_window)
        self._lock_timeout = float(lock_timeout)
        self._entries: list[JournalEntry] = []
        self._next_id = 1
        self._dirty = False
        self._last_flush_monotonic: float | None = None

    # ── reading ───────────────────────────────────────────────────────
    def entries(self) -> list[JournalEntry]:
        return list(self._entries)

    def load(self) -> None:
        """Read what is on disk. A damaged file costs the history, not the run.

        Automations must keep working after a bad shutdown, so anything
        unreadable is discarded rather than raised.
        """
        entries = self._read_from_disk()
        if entries is None:
            return  # unreadable: keep what we have rather than wiping the history
        self._entries = entries[-self._max_entries :]
        self._next_id = max((entry.id for entry in self._entries), default=0) + 1

    def _read_from_disk(self) -> list[JournalEntry] | None:
        """What is on disk now, or None when it cannot be read at all.

        The distinction matters: an empty journal is a fact to adopt, whereas an
        unreadable one must not be mistaken for "there is no history".
        """
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
            return None
        entries: list[JournalEntry] = []
        for item in raw["entries"]:
            entry = self._parse_entry(item)
            if entry is not None:
                entries.append(entry)
        return entries

    def _parse_entry(self, item: Any) -> JournalEntry | None:
        if not isinstance(item, dict):
            return None
        kind = str(item.get("kind", ""))
        if kind not in _KINDS:
            return None
        context = item.get("context")
        # Every coercion is inside the guard: one entry with a nonsense number
        # must cost that entry, not the whole file. The contract above promises
        # exactly that, so nothing here may raise.
        try:
            entry_id = int(item.get("id"))
            count = max(1, int(item.get("count", 1) or 1))
        except (TypeError, ValueError):
            return None
        return JournalEntry(
            id=entry_id,
            uid=str(item.get("uid", "")).strip() or _derived_uid(item),
            kind=kind,
            rule_id=str(item.get("rule_id", "")),
            reason=str(item.get("reason", "")),
            message_code=str(item.get("message_code", "")),
            context=context if isinstance(context, dict) else {},
            first_seen=_parse_iso(item.get("first_seen")),
            last_seen=_parse_iso(item.get("last_seen")),
            count=count,
            occurred_at=_parse_iso(item.get("occurred_at")),
            decided_at=_parse_iso(item.get("decided_at")),
            persisted_count=count,
        )

    # ── writing ───────────────────────────────────────────────────────
    def record_success(
        self,
        rule_id: str,
        *,
        message_code: str,
        now: datetime,
        occurred_at: datetime | None = None,
        decided_at: datetime | None = None,
        context: dict[str, Any] | None = None,
    ) -> JournalEntry:
        return self._append(
            KIND_SUCCESS,
            rule_id,
            message_code=message_code,
            now=now,
            occurred_at=occurred_at,
            decided_at=decided_at,
            context=context,
        )

    def record_error(
        self,
        rule_id: str,
        *,
        message_code: str,
        now: datetime,
        occurred_at: datetime | None = None,
        decided_at: datetime | None = None,
        context: dict[str, Any] | None = None,
    ) -> JournalEntry:
        return self._append(
            KIND_ERROR,
            rule_id,
            message_code=message_code,
            now=now,
            occurred_at=occurred_at,
            decided_at=decided_at,
            context=context,
        )

    def record_cancelled(
        self,
        rule_id: str,
        *,
        message_code: str,
        now: datetime,
        occurred_at: datetime | None = None,
        decided_at: datetime | None = None,
        context: dict[str, Any] | None = None,
    ) -> JournalEntry:
        return self._append(
            KIND_CANCELLED,
            rule_id,
            message_code=message_code,
            now=now,
            occurred_at=occurred_at,
            decided_at=decided_at,
            context=context,
        )

    def record_skip(
        self,
        rule_id: str,
        reason: str,
        *,
        now: datetime,
        context: dict[str, Any] | None = None,
    ) -> JournalEntry:
        """Add a skip, or fold it into the matching recent one."""
        context = dict(context or {})
        key = _collapse_key(rule_id, reason, context)
        for index in range(len(self._entries) - 1, -1, -1):
            entry = self._entries[index]
            if entry.rule_id != rule_id:
                continue  # another rule's line says nothing about this episode
            # The first entry belonging to this rule decides: anything that is
            # not the same skip — a success, an error, a different reason —
            # ended the episode, and what follows is a new one. Reaching past it
            # would merge two separate disconnections around a working apply.
            if entry.kind != KIND_SKIPPED:
                break
            if _collapse_key(entry.rule_id, entry.reason, entry.context) != key:
                break
            if entry.last_seen is not None:
                gap = (now - entry.last_seen).total_seconds()
                if gap > self._collapse_window:
                    break  # too long ago to be the same episode
            merged = replace(
                entry,
                count=entry.count + 1,
                last_seen=now,
                # The moving parts are kept as of the latest occurrence.
                context={**entry.context, **context},
            )
            self._entries[index] = merged
            self._dirty = True
            return merged
        return self._append(KIND_SKIPPED, rule_id, reason=reason, now=now, context=context)

    def _append(
        self,
        kind: str,
        rule_id: str,
        *,
        now: datetime,
        reason: str = "",
        message_code: str = "",
        occurred_at: datetime | None = None,
        decided_at: datetime | None = None,
        context: dict[str, Any] | None = None,
    ) -> JournalEntry:
        entry = JournalEntry(
            id=self._next_id,
            uid=uuid.uuid4().hex[:12],
            kind=kind,
            rule_id=rule_id,
            reason=reason,
            message_code=message_code,
            context=dict(context or {}),
            first_seen=now,
            last_seen=now,
            count=1,
            occurred_at=occurred_at,
            decided_at=decided_at,
            persisted_count=0,
        )
        self._next_id += 1
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            del self._entries[: len(self._entries) - self._max_entries]
        self._dirty = True
        return entry

    # ── persistence ───────────────────────────────────────────────────
    def flush(self, monotonic_now: float, *, force: bool = False) -> bool:
        """Merge with what is on disk and write. True when it wrote.

        Debounced by a monotonic clock so a system time change cannot stall or
        stampede writes; the timestamps *in* the entries stay wall-clock, because
        those are what the user reads.

        Under a lock, and a re-read before writing: a headless task may have
        appended its own run while this process held its list in memory, and
        writing that list as-is would delete it. Failing to take the lock is not
        an error — the entries stay dirty and go out with the next flush.
        """
        if not self._dirty:
            return False
        if not force and self._last_flush_monotonic is not None:
            if monotonic_now - self._last_flush_monotonic < self._flush_interval:
                return False
        with file_lock(self._lock_path(), timeout=self._lock_timeout) as locked:
            if not locked:
                return False
            merged = _merge_entries(self._read_from_disk() or [], self._entries, self._max_entries)
            if not self._write(merged):
                return False
            # Adopted, not just written: this process now sees the other's entries
            # too, so the next flush cannot undo them either.
            self._entries = merged
            self._next_id = max((entry.id for entry in merged), default=0) + 1
        self._dirty = False
        self._last_flush_monotonic = monotonic_now
        return True

    def _lock_path(self) -> Path:
        return self._path.with_suffix(self._path.suffix + ".lock")

    def _write(self, entries: list[JournalEntry]) -> bool:
        payload = {"entries": [self._as_dict(entry) for entry in entries]}
        # The temporary name carries this process's id: two processes sharing one
        # would overwrite each other's half-written file and rename the wreck into
        # place. os.replace is what makes the swap itself atomic.
        temporary = self._path.with_suffix(f"{self._path.suffix}.{os.getpid()}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, self._path)
        except OSError:
            # Losing the journal is not worth interrupting automations for.
            try:
                temporary.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - nothing more we can do
                pass
            return False
        return True

    @staticmethod
    def _as_dict(entry: JournalEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "uid": entry.uid,
            "kind": entry.kind,
            "rule_id": entry.rule_id,
            "reason": entry.reason,
            "message_code": entry.message_code,
            "context": entry.context,
            "first_seen": _iso(entry.first_seen),
            "last_seen": _iso(entry.last_seen),
            "count": entry.count,
            "occurred_at": _iso(entry.occurred_at),
            "decided_at": _iso(entry.decided_at),
        }
