"""Fulfillment-side workflow handlers on top of the engine (review, retry and payment
handlers live in review_flow.py): purchase order -> fulfillment (reservation,
partial shipment, replenishment, arrival) -> invoice (three-way match) ->
payment_review (rules or human queue, retries, escalation) -> settlement -> reporting,
plus the cancellation and compensation path. See docs/method.md."""
from __future__ import annotations

from business_flow_simulator.assumptions import Assumptions, load_assumptions
from business_flow_simulator.engine import SimulationResult
from business_flow_simulator.events import ActorType as A
from business_flow_simulator.events import EventStatus as S
from business_flow_simulator.events import EventType as E
from business_flow_simulator.events import OrderState
from business_flow_simulator.money import apply_bps
from business_flow_simulator.policies import (KIND_DUPLICATE_INVOICE, KIND_PRICE_VARIANCE, KIND_QUANTITY_MISMATCH,
                                              KIND_SHIPMENT_DELAYED, ExceptionCase, Policy, Thresholds, get_policy)
from business_flow_simulator.review_flow import ReviewFlowMixin
from business_flow_simulator.scenario import Scenario
from business_flow_simulator.workload import NO_CANCEL, Workload, generate_workload


class Simulator(ReviewFlowMixin):
    def __init__(self, scenario: Scenario, workload: Workload, policy: Policy, assumptions: Assumptions) -> None:
        super().__init__(scenario, workload, policy, assumptions)
        self._backorders: list[str] = []
        self._open_replenishments: set[str] = set()
        self._stockout_lines: set[tuple[str, str]] = set()
        self._repl_seq = 0
        self._invoice_seq = 0
        self.thresholds = Thresholds(
            max_attempts=int(scenario.retry_policy["max_attempts"]),
            price_variance_tolerance_bps=int(assumptions.review["price_variance_tolerance_bps"]),
            shipment_delay_tolerance_minutes=int(assumptions.review["shipment_delay_tolerance_minutes"]),
        )

    def run(self) -> SimulationResult:
        for spec in self.workload.orders:
            self.schedule(spec.t_arrival, "on_place_order", spec.order_id)
        self.run_loop()
        return self.result()

    # ---- purchase order ----------------------------------------------------------
    def on_place_order(self, oid: str) -> None:
        run = self.orders[oid]
        self.emit(oid, A.CUSTOMER, A.RETAILER, E.PURCHASE_ORDER_PLACED, S.OK, {
            "customer_id": run.spec.customer_id,
            "lines": [{"sku": l.sku, "qty": l.qty, "unit_price_cents": l.unit_price_cents} for l in run.spec.lines],
            "amount_cents": run.spec.total_cents,
        })
        self.schedule(self.now + self.a.minutes("po_acknowledge"), "on_reserve", oid)
        if run.spec.faults.cancel_after_minutes != NO_CANCEL:
            self.schedule(self.now + run.spec.faults.cancel_after_minutes, "on_cancel", oid)

    # ---- fulfillment ---------------------------------------------------------------
    def on_reserve(self, oid: str) -> None:
        run = self.orders[oid]
        if run.is_terminal():
            return
        lines, shortfall_lines, new_stockouts, to_ship = [], 0, 0, []
        for line in run.spec.lines:
            pending = run.pending_qty(line.sku)
            if pending <= 0:
                continue
            take = min(self.ledger.available(line.sku), pending)
            lines.append({"sku": line.sku, "requested": pending, "reserved": take, "backordered": pending - take})
            if take > 0:
                to_ship.append({"sku": line.sku, "qty": take})
                run.reserved[line.sku] = run.reserved.get(line.sku, 0) + take
            if pending - take > 0:
                shortfall_lines += 1
                if (oid, line.sku) not in self._stockout_lines:
                    self._stockout_lines.add((oid, line.sku))
                    new_stockouts += 1
        if not lines:
            return
        # A stockout is counted once per order line, on the first attempt that falls short.
        self.stockouts += new_stockouts
        status = S.PARTIAL if shortfall_lines else S.OK
        self.emit(oid, A.RETAILER, A.WAREHOUSE, E.INVENTORY_RESERVED, status,
                  {"lines": lines, "partial": bool(shortfall_lines)},
                  extra_cost_cents=new_stockouts * self.a.cost("backorder_line_handling"))
        if shortfall_lines and oid not in self._backorders:
            self._backorders.append(oid)
        for line in run.spec.lines:
            if self.ledger.available(line.sku) <= self.workload.reorder_point:
                self.on_replenish(line.sku)
        if to_ship:
            self.schedule(self.now + self.a.minutes("pick_pack"), "on_ship", oid, tuple((d["sku"], d["qty"]) for d in to_ship))

    def on_replenish(self, sku: str) -> None:
        if sku in self._open_replenishments:
            return
        self._open_replenishments.add(sku)
        self._repl_seq += 1
        cid = f"SYN-REPL-{self._repl_seq:04d}"
        qty = self.workload.reorder_qty
        lead = self.a.minutes("replenishment_lead")
        self.emit(cid, A.WAREHOUSE, A.MANUFACTURER, E.REPLENISHMENT_ORDERED, S.OK, {"sku": sku, "qty": qty})
        self.schedule(self.now + (lead * 3) // 10, "on_supply_dispatched", cid, sku, qty)
        self.schedule(self.now + (lead * 6) // 10, "on_replenishment_shipped", cid, sku, qty)
        self.schedule(self.now + lead, "on_replenishment_arrived", cid, sku, qty)

    def on_supply_dispatched(self, cid: str, sku: str, qty: int) -> None:
        self.emit(cid, A.SUPPLIER, A.MANUFACTURER, E.SUPPLY_DISPATCHED, S.OK, {"sku": sku, "qty": qty})

    def on_replenishment_shipped(self, cid: str, sku: str, qty: int) -> None:
        self.emit(cid, A.MANUFACTURER, A.WAREHOUSE, E.REPLENISHMENT_SHIPPED, S.OK, {"sku": sku, "qty": qty})

    def on_replenishment_arrived(self, cid: str, sku: str, qty: int) -> None:
        self.emit(cid, A.MANUFACTURER, A.WAREHOUSE, E.REPLENISHMENT_ARRIVED, S.OK, {"sku": sku, "qty": qty})
        self._open_replenishments.discard(sku)
        self.replenishments += 1
        # Wake only the backorders that were waiting for this SKU, in arrival order.
        still_waiting: list[str] = []
        for oid in self._backorders:
            run = self.orders[oid]
            if run.is_terminal():
                continue
            if run.pending_qty(sku) > 0:
                self.schedule(self.now, "on_reserve", oid)
            else:
                still_waiting.append(oid)
        self._backorders = still_waiting

    def on_ship(self, oid: str, lines: tuple[tuple[str, int], ...]) -> None:
        run = self.orders[oid]
        if run.cancelled:
            return
        run.shipments += 1
        shipment_id = f"{oid}-S{run.shipments}"
        payload_lines = [{"sku": sku, "qty": qty} for sku, qty in lines]
        for sku, qty in lines:
            run.shipped[sku] = run.shipped.get(sku, 0) + qty
        self.emit(oid, A.WAREHOUSE, A.CUSTOMER, E.SHIPMENT_DISPATCHED, S.OK,
                  {"shipment_id": shipment_id, "lines": payload_lines})
        transit = self.a.minutes("shipment_transit")
        delay = run.spec.faults.shipment_delay_minutes if run.shipments == 1 else 0
        self.schedule(self.now + transit + delay, "on_arrive", oid, shipment_id, lines)
        if delay > 0:
            self.emit(oid, A.WAREHOUSE, A.RETAILER, E.SHIPMENT_DELAYED, S.DELAYED, {
                "shipment_id": shipment_id, "delay_minutes": delay,
                "planned_arrival_t": self.now + transit, "revised_arrival_t": self.now + transit + delay,
            })
            run.exceptions += 1
            case = ExceptionCase(oid, KIND_SHIPMENT_DELAYED, delay_minutes=delay, po_amount_cents=run.spec.total_cents)
            self.handle_exception(oid, case, advance=False)

    def on_arrive(self, oid: str, shipment_id: str, lines: tuple[tuple[str, int], ...]) -> None:
        run = self.orders[oid]
        for sku, qty in lines:
            run.received[sku] = run.received.get(sku, 0) + qty
        self.emit(oid, A.CUSTOMER, A.RETAILER, E.SHIPMENT_ARRIVED, S.OK,
                  {"shipment_id": shipment_id, "lines": [{"sku": s, "qty": q} for s, q in lines],
                   "received_qty": sum(run.received.values()), "ordered_qty": run.spec.total_qty})
        if run.fully_received() and not run.invoiced:
            run.invoiced = True
            self.schedule(self.now + self.a.minutes("invoice_issue"), "on_issue_invoice", oid, False)

    # ---- invoice and three-way match ------------------------------------------------
    def on_issue_invoice(self, oid: str, duplicate: bool) -> None:
        run = self.orders[oid]
        self._invoice_seq += 1
        invoice_id = f"SYN-INV-{self._invoice_seq:06d}"
        po_amount = run.spec.total_cents
        if duplicate and run.primary_invoice is not None:
            amount = run.invoices[run.primary_invoice]
        else:
            amount = apply_bps(po_amount, run.spec.faults.price_variance_bps)
        run.invoices[invoice_id] = amount
        if run.primary_invoice is None:
            run.primary_invoice = invoice_id
        event = self.emit(oid, A.INVOICE_PAYMENT_SERVICE, A.CUSTOMER, E.INVOICE_ISSUED, S.OK, {
            "invoice_id": invoice_id, "amount_cents": amount, "po_amount_cents": po_amount,
            "duplicate_of": run.primary_invoice if duplicate else None,
        }, advance=not duplicate)
        self.schedule(self.now + self.a.minutes("three_way_match"), "on_match", oid, invoice_id)
        if not duplicate and run.spec.faults.duplicate_invoice:
            self.schedule(self.now + self.a.minutes("duplicate_invoice_gap"), "on_issue_invoice", oid, True)
        if not duplicate and run.spec.faults.replay_same_id:
            self.replay(event)

    def on_match(self, oid: str, invoice_id: str) -> None:
        run = self.orders[oid]
        amount, po_amount = run.invoices[invoice_id], run.spec.total_cents
        received, ordered = sum(run.received.values()), run.spec.total_qty
        kind = None
        if invoice_id != run.primary_invoice:
            kind = KIND_DUPLICATE_INVOICE
        elif received != ordered:
            kind = KIND_QUANTITY_MISMATCH
        elif amount != po_amount:
            kind = KIND_PRICE_VARIANCE
        is_dup = kind == KIND_DUPLICATE_INVOICE
        self.emit(oid, A.INVOICE_PAYMENT_SERVICE, A.RETAILER, E.THREE_WAY_MATCH, S.OK if kind is None else S.EXCEPTION, {
            "invoice_id": invoice_id, "po_amount_cents": po_amount, "invoice_amount_cents": amount,
            "ordered_qty": ordered, "received_qty": received, "result": "matched" if kind is None else kind,
        }, advance=not is_dup)
        if kind is None:
            self._start_payment(oid, 1, False)
            return
        run.exceptions += 1
        if is_dup:
            self.duplicate_invoices_detected += 1
        case = ExceptionCase(oid, kind, invoice_id, 0, run.spec.faults.price_variance_bps, amount, po_amount)
        self.handle_exception(oid, case, advance=not is_dup)

    # ---- reporting and cancellation --------------------------------------------------
    def on_report(self, oid: str) -> None:
        run = self.orders[oid]
        run.t_completed = self.now
        self.emit(oid, A.RETAILER, A.RETAILER, E.REPORTED, S.OK, {
            "cycle_minutes": self.now - run.spec.t_arrival, "amount_cents": run.spec.total_cents,
            "exceptions": run.exceptions, "reviews": run.reviews,
        })

    def on_cancel(self, oid: str) -> None:
        run = self.orders[oid]
        if run.shipments > 0 or run.state not in (OrderState.PURCHASE_ORDER, OrderState.FULFILLMENT):
            return
        run.cancelled = True
        if oid in self._backorders:
            self._backorders.remove(oid)
        self.emit(oid, A.CUSTOMER, A.RETAILER, E.ORDER_CANCELLED, S.CANCELLED,
                  {"reason": "customer_cancelled_before_shipment", "amount_cents": run.spec.total_cents})
        lines = [{"sku": sku, "qty": qty} for sku, qty in run.reserved.items() if qty > 0]
        if lines:
            self.emit(oid, A.WAREHOUSE, A.WAREHOUSE, E.COMPENSATION_APPLIED, S.OK,
                      {"kind": "release_reservation", "lines": lines})
            run.reserved = {}


def run_simulation(scenario: Scenario, policy: str | Policy, workload: Workload | None = None,
                   assumptions: Assumptions | None = None) -> SimulationResult:
    pol = get_policy(policy) if isinstance(policy, str) else policy
    wl = workload if workload is not None else generate_workload(scenario)
    asm = assumptions if assumptions is not None else load_assumptions()
    return Simulator(scenario, wl, pol, asm).run()
