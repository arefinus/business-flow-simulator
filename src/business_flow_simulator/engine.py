"""Discrete-event engine: a priority queue on simulated minutes with a monotone
sequence number as tie-breaker, so equal-time events fire in scheduling order and the
run is deterministic. Randomness lives only in the workload generator; the engine
itself draws no random numbers."""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from business_flow_simulator.assumptions import Assumptions
from business_flow_simulator.events import ActorType, Event, EventStatus, EventType, OrderState
from business_flow_simulator.ledger import Ledger
from business_flow_simulator.policies import Policy
from business_flow_simulator.review_queue import ReviewQueue
from business_flow_simulator.scenario import Scenario
from business_flow_simulator.state_machine import assert_transition, state_for
from business_flow_simulator.store import AppendResult, EventStore, StoreCounters
from business_flow_simulator.workload import OrderSpec, Workload


class EngineError(RuntimeError):
    """Raised when the engine reaches an impossible internal state."""


@dataclass
class OrderRun:
    """Mutable per-order runtime state, internal to the simulator."""

    spec: OrderSpec
    state: OrderState | None = None
    reserved: dict[str, int] = field(default_factory=dict)
    shipped: dict[str, int] = field(default_factory=dict)
    received: dict[str, int] = field(default_factory=dict)
    shipments: int = 0
    invoices: dict[str, int] = field(default_factory=dict)
    primary_invoice: str | None = None
    payment_attempts: int = 0
    exceptions: int = 0
    reviews: int = 0
    auto_resolutions: int = 0
    escalations: int = 0
    cancelled: bool = False
    invoiced: bool = False
    paying: bool = False
    settled: bool = False
    t_completed: int | None = None

    def pending_qty(self, sku: str) -> int:
        ordered = sum(l.qty for l in self.spec.lines if l.sku == sku)
        return ordered - self.reserved.get(sku, 0)

    def fully_received(self) -> bool:
        return sum(self.received.values()) == self.spec.total_qty

    def is_terminal(self) -> bool:
        return self.cancelled or self.t_completed is not None


@dataclass(frozen=True)
class OrderRecord:
    order_id: str
    customer_id: str
    t_placed: int
    t_completed: int | None
    cycle_minutes: int | None
    completed: bool
    cancelled: bool
    exceptions: int
    reviews: int
    auto_resolutions: int
    escalations: int
    shipments: int
    payment_attempts: int
    amount_cents: int


@dataclass(frozen=True)
class SimulationResult:
    scenario_id: str
    policy: str
    seed: int
    horizon_minutes: int
    events: tuple[Event, ...]
    orders: tuple[OrderRecord, ...]
    backlog_series: tuple[tuple[int, int], ...]
    stockout_count: int
    replenishments: int
    processing_cost_cents: int
    store_counters: StoreCounters
    replayed_event_ids: int
    duplicate_invoices_detected: int
    review_tickets: int
    escalations: int
    auto_resolutions: int
    inventory_conserved: bool
    cash_conserved: bool
    ledger_balances: Mapping[str, int]


class Engine:
    def __init__(self, scenario: Scenario, workload: Workload, policy: Policy, assumptions: Assumptions) -> None:
        self.scenario = scenario
        self.workload = workload
        self.policy = policy
        self.a = assumptions
        self.store = EventStore()
        self.ledger = Ledger(workload.initial_stock, workload.opening_balances)
        self.store.subscribe(self.ledger.apply)
        rv = assumptions.review
        self.queue = ReviewQueue(
            policy.queue_mode, rv["reviewers_manual"], assumptions.minutes("manual_review"),
            rv["period_minutes"], rv["capacity_per_period"], rv["escalation_after_minutes"],
        )
        self.now = 0
        self._heap: list[tuple[int, int, str, tuple[Any, ...]]] = []
        self._seq = 0
        self._event_seq = 0
        self.orders: dict[str, OrderRun] = {o.order_id: OrderRun(o) for o in workload.orders}
        self.cost_cents = 0
        self.stockouts = 0
        self.replenishments = 0
        self.replayed_event_ids = 0
        self.duplicate_invoices_detected = 0

    # ---- scheduling ------------------------------------------------------------
    def schedule(self, t: int, handler: str, *args: Any) -> None:
        if t < self.now:
            raise EngineError(f"cannot schedule {handler} in the past ({t} < {self.now})")
        self._seq += 1
        heapq.heappush(self._heap, (int(t), self._seq, handler, args))

    def run_loop(self) -> None:
        horizon = self.scenario.horizon_minutes
        while self._heap:
            t, _, handler, args = heapq.heappop(self._heap)
            if t > horizon:
                break
            self.now = t
            fn: Callable[..., None] = getattr(self, handler)
            fn(*args)

    # ---- event emission --------------------------------------------------------
    def emit(self, correlation_id: str, actor: ActorType, to_actor: ActorType, event_type: EventType,
             status: EventStatus, payload: Mapping[str, Any], advance: bool = True,
             extra_cost_cents: int = 0) -> Event:
        run = self.orders.get(correlation_id)
        if run is not None and advance:
            new_state = assert_transition(run.state, state_for(event_type))
            run.state = new_state
            state = new_state
        elif run is not None:
            state = run.state if run.state is not None else state_for(event_type)
        else:
            state = OrderState.FULFILLMENT
        cost = self._cost_for(event_type, status) + extra_cost_cents
        self._event_seq += 1
        body = dict(payload)
        body["cost_cents"] = cost
        event = Event(
            id=f"SYN-EV-{self._event_seq:07d}",
            t=self.now,
            correlation_id=correlation_id,
            version=self.store.next_version(correlation_id),
            actor_type=actor.value,
            to_actor=to_actor.value,
            event_type=event_type.value,
            state=state.value,
            status=status.value,
            payload=body,
        )
        result = self.store.append(event)
        if result is not AppendResult.APPLIED:
            raise EngineError(f"engine emitted an event the store did not apply: {result}")
        self.cost_cents += cost
        return event

    def replay(self, event: Event) -> AppendResult:
        """Re-append an already stored event (fault injection). Must be a no-op."""
        result = self.store.append(event)
        if result is AppendResult.DUPLICATE_IGNORED:
            self.replayed_event_ids += 1
        return result

    def _cost_for(self, event_type: EventType, status: EventStatus) -> int:
        if event_type is EventType.REVIEW_RESOLVED:
            return self.a.cost("manual_review_per_item")
        if event_type is EventType.REVIEW_ESCALATED:
            return self.a.cost("escalation")
        if event_type is EventType.PAYMENT_ATTEMPTED and status is EventStatus.FAILED:
            return self.a.cost("payment_retry")
        return self.a.cost("automated_step")

    # ---- result ----------------------------------------------------------------
    def result(self) -> SimulationResult:
        records = []
        for run in self.orders.values():
            completed = run.t_completed is not None
            records.append(OrderRecord(
                order_id=run.spec.order_id, customer_id=run.spec.customer_id,
                t_placed=run.spec.t_arrival, t_completed=run.t_completed,
                cycle_minutes=(run.t_completed - run.spec.t_arrival) if completed else None,
                completed=completed, cancelled=run.cancelled, exceptions=run.exceptions,
                reviews=run.reviews, auto_resolutions=run.auto_resolutions,
                escalations=run.escalations, shipments=run.shipments,
                payment_attempts=run.payment_attempts, amount_cents=run.spec.total_cents,
            ))
        period = self.a.review["period_minutes"]
        samples = range(0, self.scenario.horizon_minutes + 1, period)
        return SimulationResult(
            scenario_id=self.scenario.scenario_id, policy=self.policy.name, seed=self.scenario.seed,
            horizon_minutes=self.scenario.horizon_minutes, events=self.store.events,
            orders=tuple(records), backlog_series=self.queue.backlog_series(samples),
            stockout_count=self.stockouts, replenishments=self.replenishments,
            processing_cost_cents=self.cost_cents, store_counters=self.store.counters(),
            replayed_event_ids=self.replayed_event_ids,
            duplicate_invoices_detected=self.duplicate_invoices_detected,
            review_tickets=len(self.queue.tickets), escalations=self.queue.escalations(),
            auto_resolutions=sum(r.auto_resolutions for r in self.orders.values()),
            inventory_conserved=self.ledger.inventory_conserved(),
            cash_conserved=self.ledger.cash_conserved(), ledger_balances=self.ledger.balances(),
        )
