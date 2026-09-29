"""Inventory and cash ledger. The ledger is a pure projection of applied events: it
subscribes to the ``EventStore`` and never sees a duplicate or stale event, which is
what makes replaying an event id safe. Two invariants are exposed so tests can check
them after any sequence of events:

* inventory: initial + received == on_hand + reserved + in_transit + delivered (per SKU)
* cash: the sum of all account balances never changes (payments move cents, they do
  not create or destroy them)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from business_flow_simulator.events import Event, EventType
from business_flow_simulator.money import cents

RETAILER_ACCOUNT = "RETAILER"


class LedgerError(RuntimeError):
    """Raised when an event would drive stock or cash negative."""


@dataclass
class SkuStock:
    initial: int
    on_hand: int
    reserved: int = 0
    in_transit: int = 0
    delivered: int = 0
    received: int = 0

    def conserved(self) -> bool:
        return self.initial + self.received == (
            self.on_hand + self.reserved + self.in_transit + self.delivered
        )


class Ledger:
    def __init__(self, initial_stock: Mapping[str, int], opening_balances: Mapping[str, int]) -> None:
        self._stock: dict[str, SkuStock] = {
            sku: SkuStock(initial=int(q), on_hand=int(q)) for sku, q in initial_stock.items()
        }
        self._cash: dict[str, int] = {acct: cents(bal) for acct, bal in opening_balances.items()}
        self._cash.setdefault(RETAILER_ACCOUNT, 0)
        self._opening_total = sum(self._cash.values())
        self.applied_events = 0

    # ---- read side -------------------------------------------------------------
    def available(self, sku: str) -> int:
        return self._stock[sku].on_hand

    def stock(self, sku: str) -> SkuStock:
        return self._stock[sku]

    def skus(self) -> tuple[str, ...]:
        return tuple(self._stock)

    def balance(self, account: str) -> int:
        return self._cash[account]

    def balances(self) -> dict[str, int]:
        return dict(self._cash)

    def cash_total(self) -> int:
        return sum(self._cash.values())

    def cash_conserved(self) -> bool:
        return self.cash_total() == self._opening_total

    def inventory_conserved(self) -> bool:
        return all(s.conserved() for s in self._stock.values())

    # ---- write side (only via events) ------------------------------------------
    def apply(self, event: Event) -> None:
        handler = _HANDLERS.get(event.event_type)
        if handler is not None:
            handler(self, event)
            self.applied_events += 1

    def _move(self, sku: str, src: str, dst: str, qty: int) -> None:
        if qty < 0:
            raise LedgerError(f"negative movement {qty} for {sku}")
        stock = self._stock[sku]
        if getattr(stock, src) < qty:
            raise LedgerError(f"{sku}: cannot move {qty} from {src} (has {getattr(stock, src)})")
        setattr(stock, src, getattr(stock, src) - qty)
        setattr(stock, dst, getattr(stock, dst) + qty)

    def _reserve(self, event: Event) -> None:
        for line in event.payload["lines"]:
            self._move(line["sku"], "on_hand", "reserved", int(line["reserved"]))

    def _dispatch(self, event: Event) -> None:
        for line in event.payload["lines"]:
            self._move(line["sku"], "reserved", "in_transit", int(line["qty"]))

    def _arrive(self, event: Event) -> None:
        for line in event.payload["lines"]:
            self._move(line["sku"], "in_transit", "delivered", int(line["qty"]))

    def _replenish(self, event: Event) -> None:
        stock = self._stock[event.payload["sku"]]
        qty = int(event.payload["qty"])
        if qty < 0:
            raise LedgerError("replenishment quantity must be non-negative")
        stock.on_hand += qty
        stock.received += qty

    def _transfer(self, payer: str, payee: str, amount: int) -> None:
        amount = cents(amount)
        if amount < 0:
            raise LedgerError("transfers must be non-negative")
        if self._cash.get(payer, 0) < amount:
            raise LedgerError(f"{payer} cannot pay {amount} (balance {self._cash.get(payer, 0)})")
        self._cash[payer] -= amount
        self._cash[payee] = self._cash.get(payee, 0) + amount

    def _settle(self, event: Event) -> None:
        p = event.payload
        self._transfer(p["payer_account"], p["payee_account"], p["amount_cents"])

    def _compensate(self, event: Event) -> None:
        p = event.payload
        kind = p["kind"]
        if kind == "release_reservation":
            for line in p["lines"]:
                self._move(line["sku"], "reserved", "on_hand", int(line["qty"]))
        elif kind == "return_to_stock":
            for line in p["lines"]:
                self._move(line["sku"], "delivered", "on_hand", int(line["qty"]))
        elif kind == "refund":
            self._transfer(p["payer_account"], p["payee_account"], p["amount_cents"])
        else:
            raise LedgerError(f"unknown compensation kind {kind!r}")


_HANDLERS = {
    EventType.INVENTORY_RESERVED.value: Ledger._reserve,
    EventType.SHIPMENT_DISPATCHED.value: Ledger._dispatch,
    EventType.SHIPMENT_ARRIVED.value: Ledger._arrive,
    EventType.REPLENISHMENT_ARRIVED.value: Ledger._replenish,
    EventType.SETTLED.value: Ledger._settle,
    EventType.COMPENSATION_APPLIED.value: Ledger._compensate,
}
