from __future__ import annotations

import pytest

from business_flow_simulator.events import EventType, OrderState
from business_flow_simulator.money import MoneyError, apply_bps, cents, format_usd, line_total
from business_flow_simulator.state_machine import (EVENT_STATE, HAPPY_PATH, TERMINAL_STATES, InvalidTransition,
                                                   assert_transition, state_for)


def test_happy_path_is_legal_end_to_end():
    current = None
    for state in HAPPY_PATH:
        current = assert_transition(current, state)
    assert current is OrderState.REPORTING and current in TERMINAL_STATES


def test_illegal_transitions_raise():
    with pytest.raises(InvalidTransition):
        assert_transition(OrderState.SETTLEMENT, OrderState.FULFILLMENT)
    with pytest.raises(InvalidTransition):
        assert_transition(OrderState.REPORTING, OrderState.SETTLEMENT)
    with pytest.raises(InvalidTransition):
        assert_transition(None, OrderState.INVOICE)


def test_cancellation_allowed_only_before_invoice():
    assert assert_transition(OrderState.PURCHASE_ORDER, OrderState.CANCELLED) is OrderState.CANCELLED
    assert assert_transition(OrderState.FULFILLMENT, OrderState.CANCELLED) is OrderState.CANCELLED
    for late in (OrderState.INVOICE, OrderState.PAYMENT_REVIEW, OrderState.SETTLEMENT):
        with pytest.raises(InvalidTransition):
            assert_transition(late, OrderState.CANCELLED)


def test_every_order_event_type_maps_to_a_state():
    replenishment = {EventType.REPLENISHMENT_ORDERED, EventType.SUPPLY_DISPATCHED,
                     EventType.REPLENISHMENT_SHIPPED, EventType.REPLENISHMENT_ARRIVED}
    for et in EventType:
        if et in replenishment:
            with pytest.raises(InvalidTransition):
                state_for(et)
        else:
            assert isinstance(state_for(et), OrderState)
    assert set(EVENT_STATE) | replenishment == set(EventType)


def test_money_rejects_floats_and_bools_and_negative_quantities():
    assert cents(1200) == 1200
    for bad in (12.0, True, "12"):
        with pytest.raises(MoneyError):
            cents(bad)
    with pytest.raises(MoneyError):
        line_total(-1, 100)


def test_money_arithmetic_stays_integer():
    assert line_total(3, 1999) == 5997
    assert apply_bps(10_000, 150) == 10_150
    assert apply_bps(10_000, -150) == 9_850
    assert apply_bps(333, 100) == 336  # floor division, still an int
    assert format_usd(123_456) == "USD 1234.56" and format_usd(-5) == "-USD 0.05"
