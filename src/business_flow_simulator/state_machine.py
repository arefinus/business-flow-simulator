"""Order-level state machine. The simulator asks ``assert_transition`` before it emits
an event that moves an order; an invalid move is a programming error and raises."""
from __future__ import annotations

from business_flow_simulator.events import EventType, OrderState

TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.PURCHASE_ORDER: frozenset({OrderState.FULFILLMENT, OrderState.CANCELLED}),
    OrderState.FULFILLMENT: frozenset(
        {OrderState.FULFILLMENT, OrderState.INVOICE, OrderState.CANCELLED}
    ),
    OrderState.INVOICE: frozenset({OrderState.INVOICE, OrderState.PAYMENT_REVIEW}),
    OrderState.PAYMENT_REVIEW: frozenset(
        {OrderState.PAYMENT_REVIEW, OrderState.INVOICE, OrderState.SETTLEMENT}
    ),
    OrderState.SETTLEMENT: frozenset({OrderState.REPORTING}),
    OrderState.REPORTING: frozenset(),
    OrderState.CANCELLED: frozenset({OrderState.CANCELLED}),
}

TERMINAL_STATES: frozenset[OrderState] = frozenset({OrderState.REPORTING, OrderState.CANCELLED})

# Which order state an event type places the order in.
EVENT_STATE: dict[EventType, OrderState] = {
    EventType.PURCHASE_ORDER_PLACED: OrderState.PURCHASE_ORDER,
    EventType.INVENTORY_RESERVED: OrderState.FULFILLMENT,
    EventType.SHIPMENT_DISPATCHED: OrderState.FULFILLMENT,
    EventType.SHIPMENT_DELAYED: OrderState.FULFILLMENT,
    EventType.SHIPMENT_ARRIVED: OrderState.FULFILLMENT,
    EventType.INVOICE_ISSUED: OrderState.INVOICE,
    EventType.THREE_WAY_MATCH: OrderState.INVOICE,
    EventType.AUTO_RESOLVED: OrderState.PAYMENT_REVIEW,
    EventType.REVIEW_ENQUEUED: OrderState.PAYMENT_REVIEW,
    EventType.REVIEW_ESCALATED: OrderState.PAYMENT_REVIEW,
    EventType.REVIEW_RESOLVED: OrderState.PAYMENT_REVIEW,
    EventType.INVOICE_REJECTED: OrderState.PAYMENT_REVIEW,
    EventType.PAYMENT_ATTEMPTED: OrderState.PAYMENT_REVIEW,
    EventType.PAYMENT_RETRY_SCHEDULED: OrderState.PAYMENT_REVIEW,
    EventType.SETTLED: OrderState.SETTLEMENT,
    EventType.REPORTED: OrderState.REPORTING,
    EventType.ORDER_CANCELLED: OrderState.CANCELLED,
    EventType.COMPENSATION_APPLIED: OrderState.CANCELLED,
}

HAPPY_PATH: tuple[OrderState, ...] = (
    OrderState.PURCHASE_ORDER,
    OrderState.FULFILLMENT,
    OrderState.INVOICE,
    OrderState.PAYMENT_REVIEW,
    OrderState.SETTLEMENT,
    OrderState.REPORTING,
)


class InvalidTransition(RuntimeError):
    """Raised when an order would move along an edge the state machine does not have."""


def assert_transition(current: OrderState | None, new: OrderState) -> OrderState:
    """Return ``new`` if the move is legal. ``current is None`` means a fresh order,
    which may only start in ``PURCHASE_ORDER``."""
    if current is None:
        if new is OrderState.PURCHASE_ORDER:
            return new
        raise InvalidTransition(f"an order must start in purchase_order, not {new.value}")
    if new in TRANSITIONS[current]:
        return new
    raise InvalidTransition(f"illegal transition {current.value} -> {new.value}")


def state_for(event_type: EventType) -> OrderState:
    try:
        return EVENT_STATE[event_type]
    except KeyError as exc:
        raise InvalidTransition(f"{event_type.value} is not an order event") from exc
