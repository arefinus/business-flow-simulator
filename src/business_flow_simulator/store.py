"""Append-only, idempotent event store with per-correlation ordering.

Ordering rule (also documented in docs/method.md):
* an event whose ``id`` was seen before is ignored (``DUPLICATE_IGNORED``);
* an event whose ``version`` equals the next expected version for its
  ``correlation_id`` is applied and listeners are notified exactly once;
* an event whose ``version`` is ahead of the expected one is buffered and applied
  when the gap closes (``BUFFERED``);
* an event whose ``version`` is behind the expected one is rejected as stale
  (``REJECTED_STALE``) and never reaches a listener.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from business_flow_simulator.events import Event

Listener = Callable[[Event], None]


class AppendResult(str, Enum):
    APPLIED = "applied"
    DUPLICATE_IGNORED = "duplicate_ignored"
    BUFFERED = "buffered"
    REJECTED_STALE = "rejected_stale"


@dataclass(frozen=True)
class StoreCounters:
    applied: int
    duplicates_ignored: int
    buffered_pending: int
    rejected_stale: int


class EventStore:
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._ids: set[str] = set()
        self._versions: dict[str, int] = {}
        self._buffer: dict[str, dict[int, Event]] = {}
        self._listeners: list[Listener] = []
        self._duplicates = 0
        self._stale = 0

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def next_version(self, correlation_id: str) -> int:
        return self._versions.get(correlation_id, 0) + 1

    def counters(self) -> StoreCounters:
        pending = sum(len(b) for b in self._buffer.values())
        return StoreCounters(len(self._events), self._duplicates, pending, self._stale)

    def append(self, event: Event) -> AppendResult:
        if event.id in self._ids:
            self._duplicates += 1
            return AppendResult.DUPLICATE_IGNORED
        expected = self.next_version(event.correlation_id)
        if event.version < expected:
            self._stale += 1
            return AppendResult.REJECTED_STALE
        if event.version > expected:
            self._ids.add(event.id)
            self._buffer.setdefault(event.correlation_id, {})[event.version] = event
            return AppendResult.BUFFERED
        self._apply(event)
        self._drain(event.correlation_id)
        return AppendResult.APPLIED

    def _apply(self, event: Event) -> None:
        self._events.append(event)
        self._ids.add(event.id)
        self._versions[event.correlation_id] = event.version
        for listener in self._listeners:
            listener(event)

    def _drain(self, correlation_id: str) -> None:
        pending = self._buffer.get(correlation_id)
        while pending:
            event = pending.pop(self.next_version(correlation_id), None)
            if event is None:
                break
            self._apply(event)
        if pending is not None and not pending:
            del self._buffer[correlation_id]
