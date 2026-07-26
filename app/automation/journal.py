"""What the automation engine did, and what it declined to do.

Kept in its own file rather than in ``settings.json``: entries are written far
more often than settings, and a corrupt or half-written journal must never cost
the user their configuration.

Stored as stable codes, never as localised text. The journal outlives a language
change, and a line written in Russian would still read in Russian after the user
switches to English.

Repeats of the *same* skip collapse into one row with a count. Successes and
errors never collapse: each one is a distinct thing that happened to the light.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

KIND_SUCCESS = "success"
KIND_SKIPPED = "skipped"
KIND_ERROR = "error"
# Its own kind rather than an error: the user taking over is not a fault, and a
# journal that paints it red would train them to ignore real failures.
KIND_CANCELLED = "cancelled"

_KINDS = (KIND_SUCCESS, KIND_SKIPPED, KIND_ERROR, KIND_CANCELLED)

MAX_ENTRIES = 300
FLUSH_INTERVAL_SECONDS = 5.0
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


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat(timespec="seconds")


def _parse_iso(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


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
    ) -> None:
        self._path = Path(path)
        self._max_entries = max(1, int(max_entries))
        self._flush_interval = float(flush_interval)
        self._collapse_window = float(collapse_window)
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
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
            return
        entries: list[JournalEntry] = []
        for item in raw["entries"]:
            entry = self._parse_entry(item)
            if entry is not None:
                entries.append(entry)
        self._entries = entries[-self._max_entries :]
        self._next_id = max((entry.id for entry in self._entries), default=0) + 1

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
        )
        self._next_id += 1
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            del self._entries[: len(self._entries) - self._max_entries]
        self._dirty = True
        return entry

    # ── persistence ───────────────────────────────────────────────────
    def flush(self, monotonic_now: float, *, force: bool = False) -> bool:
        """Write to disk at most every ``flush_interval``. True when it wrote.

        Debounced by a monotonic clock so a system time change cannot stall or
        stampede writes; the timestamps *in* the entries stay wall-clock,
        because those are what the user reads.
        """
        if not self._dirty:
            return False
        if not force and self._last_flush_monotonic is not None:
            if monotonic_now - self._last_flush_monotonic < self._flush_interval:
                return False
        payload = {"entries": [self._as_dict(entry) for entry in self._entries]}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(self._path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, self._path)
        except OSError:
            # Losing the journal is not worth interrupting automations for.
            return False
        self._dirty = False
        self._last_flush_monotonic = monotonic_now
        return True

    @staticmethod
    def _as_dict(entry: JournalEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
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
