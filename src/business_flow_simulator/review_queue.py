"""Human review queue with two service models.

``servers``: ``reviewers`` people work continuously; each item takes ``service_minutes``
and is picked up by the first free reviewer (FIFO). ``capacity``: at most
``capacity_per_period`` reviews may start in any period of ``period_minutes``; an item
that finds its period full waits for the next period with a free slot. Either way an
item that will wait longer than ``escalation_after_minutes`` is escalated once.
Resolution times are fixed at enqueue time, which keeps the simulation deterministic
and lets the backlog be sampled at any time from the ticket list alone."""
from __future__ import annotations

from dataclasses import dataclass

from business_flow_simulator.policies import QUEUE_CAPACITY, QUEUE_SERVERS


class QueueError(ValueError):
    """Raised for an invalid queue configuration."""


@dataclass(frozen=True)
class ReviewTicket:
    ticket_id: str
    order_id: str
    t_enqueued: int
    t_start: int
    t_resolved: int
    t_escalated: int | None
    slot: int

    @property
    def wait_minutes(self) -> int:
        return self.t_resolved - self.t_enqueued


class ReviewQueue:
    def __init__(self, mode: str, reviewers: int, service_minutes: int, period_minutes: int,
                 capacity_per_period: int, escalation_after_minutes: int) -> None:
        if mode not in (QUEUE_SERVERS, QUEUE_CAPACITY):
            raise QueueError(f"unknown queue mode {mode!r}")
        if reviewers < 1 or period_minutes < 1 or capacity_per_period < 1 or service_minutes < 0:
            raise QueueError("reviewers, period and capacity must be >= 1; service time >= 0")
        self.mode = mode
        self.reviewers = reviewers
        self.service = service_minutes
        self.period = period_minutes
        self.capacity = capacity_per_period
        self.escalation_after = escalation_after_minutes
        self._busy_until = [0] * reviewers
        self._used: dict[int, int] = {}
        self._tickets: list[ReviewTicket] = []

    @property
    def tickets(self) -> tuple[ReviewTicket, ...]:
        return tuple(self._tickets)

    def enqueue(self, t: int, order_id: str) -> ReviewTicket:
        if self.mode == QUEUE_SERVERS:
            slot = min(range(self.reviewers), key=lambda i: (self._busy_until[i], i))
            start = max(t, self._busy_until[slot])
            resolved = start + self.service
            self._busy_until[slot] = resolved
        else:
            period = t // self.period
            while self._used.get(period, 0) >= self.capacity:
                period += 1
            slot = period
            self._used[period] = self._used.get(period, 0) + 1
            start = max(t, period * self.period)
            resolved = start + self.service
        escalated = t + self.escalation_after if resolved - t > self.escalation_after else None
        ticket = ReviewTicket(f"SYN-RV-{len(self._tickets) + 1:05d}", order_id, t, start, resolved, escalated, slot)
        self._tickets.append(ticket)
        return ticket

    def backlog_at(self, t: int) -> int:
        return sum(1 for tk in self._tickets if tk.t_enqueued <= t < tk.t_resolved)

    def backlog_series(self, sample_times: range | list[int] | tuple[int, ...]) -> tuple[tuple[int, int], ...]:
        return tuple((int(s), self.backlog_at(int(s))) for s in sample_times)

    def escalations(self) -> int:
        return sum(1 for tk in self._tickets if tk.t_escalated is not None)

    def periods_used(self) -> dict[int, int]:
        return dict(self._used)
