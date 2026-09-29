from __future__ import annotations

import pytest

from business_flow_simulator.events import Event
from business_flow_simulator.ledger import RETAILER_ACCOUNT, Ledger, LedgerError
from business_flow_simulator.store import AppendResult, EventStore

SKU = "SYN-SKU-001"
CUST = "SYN-CUST-01"


def ev(eid: str, version: int, event_type: str, payload: dict, cid: str = "SYN-PO-000001") -> Event:
    return Event(id=eid, t=1, correlation_id=cid, version=version, actor_type="warehouse", to_actor="customer",
                 event_type=event_type, state="fulfillment", status="ok", payload=payload)


def fresh() -> tuple[EventStore, Ledger]:
    store, ledger = EventStore(), Ledger({SKU: 100}, {CUST: 50_000})
    store.subscribe(ledger.apply)
    return store, ledger


def test_reservation_moves_stock_and_conserves():
    store, ledger = fresh()
    store.append(ev("e1", 1, "inventory_reserved", {"lines": [{"sku": SKU, "reserved": 30}]}))
    s = ledger.stock(SKU)
    assert (s.on_hand, s.reserved) == (70, 30) and ledger.inventory_conserved()


def test_reservation_beyond_available_raises():
    store, ledger = fresh()
    with pytest.raises(LedgerError):
        ledger.apply(ev("e1", 1, "inventory_reserved", {"lines": [{"sku": SKU, "reserved": 101}]}))


def test_dispatch_arrival_and_replenishment_chain_conserves():
    store, ledger = fresh()
    store.append(ev("e1", 1, "inventory_reserved", {"lines": [{"sku": SKU, "reserved": 30}]}))
    store.append(ev("e2", 2, "shipment_dispatched", {"lines": [{"sku": SKU, "qty": 30}]}))
    store.append(ev("e3", 3, "shipment_arrived", {"lines": [{"sku": SKU, "qty": 30}]}))
    store.append(ev("r1", 1, "replenishment_arrived", {"sku": SKU, "qty": 50}, cid="SYN-REPL-0001"))
    s = ledger.stock(SKU)
    assert (s.on_hand, s.reserved, s.in_transit, s.delivered, s.received) == (120, 0, 0, 30, 50)
    assert ledger.inventory_conserved()


def test_settlement_transfers_cash_and_total_is_conserved():
    store, ledger = fresh()
    store.append(ev("e1", 1, "settled", {"payer_account": CUST, "payee_account": RETAILER_ACCOUNT, "amount_cents": 12_345}))
    assert ledger.balance(CUST) == 37_655 and ledger.balance(RETAILER_ACCOUNT) == 12_345
    assert ledger.cash_conserved() and ledger.cash_total() == 50_000


def test_settlement_beyond_balance_raises_and_negative_amount_raises():
    _, ledger = fresh()
    with pytest.raises(LedgerError):
        ledger.apply(ev("e1", 1, "settled", {"payer_account": CUST, "payee_account": RETAILER_ACCOUNT, "amount_cents": 50_001}))
    with pytest.raises(LedgerError):
        ledger.apply(ev("e2", 1, "settled", {"payer_account": CUST, "payee_account": RETAILER_ACCOUNT, "amount_cents": -1}))


def test_replaying_settlement_event_id_does_not_double_charge():
    store, ledger = fresh()
    settle = ev("e1", 1, "settled", {"payer_account": CUST, "payee_account": RETAILER_ACCOUNT, "amount_cents": 10_000})
    assert store.append(settle) is AppendResult.APPLIED
    assert store.append(settle) is AppendResult.DUPLICATE_IGNORED
    assert store.append(settle) is AppendResult.DUPLICATE_IGNORED
    assert ledger.balance(CUST) == 40_000 and ledger.balance(RETAILER_ACCOUNT) == 10_000
    assert ledger.applied_events == 1


def test_replaying_reservation_event_id_does_not_duplicate_stock_movement():
    store, ledger = fresh()
    reserve = ev("e1", 1, "inventory_reserved", {"lines": [{"sku": SKU, "reserved": 60}]})
    store.append(reserve)
    store.append(reserve)  # a second application would need 120 units and would raise
    assert ledger.stock(SKU).reserved == 60 and ledger.inventory_conserved()


def test_compensation_releases_reservation_and_refund_restores_cash():
    store, ledger = fresh()
    store.append(ev("e1", 1, "inventory_reserved", {"lines": [{"sku": SKU, "reserved": 25}]}))
    store.append(ev("e2", 2, "compensation_applied", {"kind": "release_reservation", "lines": [{"sku": SKU, "qty": 25}]}))
    assert ledger.stock(SKU).on_hand == 100 and ledger.stock(SKU).reserved == 0
    store.append(ev("e3", 3, "settled", {"payer_account": CUST, "payee_account": RETAILER_ACCOUNT, "amount_cents": 700}))
    store.append(ev("e4", 4, "compensation_applied", {"kind": "refund", "payer_account": RETAILER_ACCOUNT, "payee_account": CUST, "amount_cents": 700}))
    assert ledger.balance(CUST) == 50_000 and ledger.cash_conserved()
    with pytest.raises(LedgerError):
        ledger.apply(ev("e5", 5, "compensation_applied", {"kind": "unknown"}))
