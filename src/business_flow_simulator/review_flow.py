"""Exception handling, human review, retries and payment attempts. Mixed into
``Simulator``; kept separate from the fulfillment handlers so each module stays small."""
from __future__ import annotations

from business_flow_simulator.engine import Engine
from business_flow_simulator.events import ActorType as A
from business_flow_simulator.events import EventStatus as S
from business_flow_simulator.events import EventType as E
from business_flow_simulator.ledger import RETAILER_ACCOUNT
from business_flow_simulator.policies import (ACTION_ACKNOWLEDGE, ACTION_APPROVE, ACTION_MANUAL_SETTLE,
                                              ACTION_REJECT_DUPLICATE, ACTION_RETRY, KIND_PAYMENT_FAILED,
                                              KIND_RETRIES_EXHAUSTED, ROUTE_AUTO, ExceptionCase, Thresholds)


class ReviewFlowMixin(Engine):
    thresholds: Thresholds

    def handle_exception(self, oid: str, case: ExceptionCase, advance: bool = True) -> None:
        run = self.orders[oid]
        decision = self.policy.decide(case, self.thresholds)
        if decision.route == ROUTE_AUTO:
            run.auto_resolutions += 1
            self.emit(oid, A.INVOICE_PAYMENT_SERVICE, A.RETAILER, E.AUTO_RESOLVED, S.OK,
                      {"kind": case.kind, "action": decision.action, "rule": decision.reason}, advance=advance)
            self.apply_action(oid, case, decision.action, advance)
            return
        ticket = self.queue.enqueue(self.now, oid)
        run.reviews += 1
        self.emit(oid, A.RETAILER, A.REVIEW_QUEUE, E.REVIEW_ENQUEUED, S.EXCEPTION, {
            "ticket_id": ticket.ticket_id, "kind": case.kind, "invoice_id": case.invoice_id,
            "attempt": case.attempt, "expected_resolution_t": ticket.t_resolved, "queue_mode": self.queue.mode,
        }, advance=advance)
        if ticket.t_escalated is not None:
            self.schedule(ticket.t_escalated, "on_escalate", oid, ticket.ticket_id, case.kind, advance)
        self.schedule(ticket.t_resolved, "on_review_resolved", oid, ticket.ticket_id, case, decision.action, advance)

    def on_escalate(self, oid: str, ticket_id: str, kind: str, advance: bool) -> None:
        self.orders[oid].escalations += 1
        self.emit(oid, A.REVIEW_QUEUE, A.RETAILER, E.REVIEW_ESCALATED, S.ESCALATED,
                  {"ticket_id": ticket_id, "kind": kind, "waited_minutes": self.a.review["escalation_after_minutes"]},
                  advance=advance)

    def on_review_resolved(self, oid: str, ticket_id: str, case: ExceptionCase, action: str, advance: bool) -> None:
        self.emit(oid, A.REVIEW_QUEUE, A.INVOICE_PAYMENT_SERVICE, E.REVIEW_RESOLVED, S.OK,
                  {"ticket_id": ticket_id, "kind": case.kind, "action": action}, advance=advance)
        self.apply_action(oid, case, action, advance)

    def apply_action(self, oid: str, case: ExceptionCase, action: str, advance: bool) -> None:
        run = self.orders[oid]
        if action == ACTION_REJECT_DUPLICATE:
            self.emit(oid, A.INVOICE_PAYMENT_SERVICE, A.CUSTOMER, E.INVOICE_REJECTED, S.REJECTED,
                      {"invoice_id": case.invoice_id, "duplicate_of": run.primary_invoice}, advance=False)
        elif action == ACTION_APPROVE:
            self._start_payment(oid, 1, False)
        elif action == ACTION_RETRY:
            rp = self.scenario.retry_policy
            backoff = rp["base_backoff_minutes"] * (rp["multiplier"] ** max(case.attempt - 1, 0))
            self.emit(oid, A.INVOICE_PAYMENT_SERVICE, A.INVOICE_PAYMENT_SERVICE, E.PAYMENT_RETRY_SCHEDULED, S.OK,
                      {"attempt": case.attempt + 1, "backoff_minutes": backoff, "retry_at_t": self.now + backoff},
                      advance=advance)
            self.schedule(self.now + backoff, "on_payment_attempt", oid, case.attempt + 1, False)
        elif action == ACTION_MANUAL_SETTLE:
            self._start_payment(oid, case.attempt + 1, True)
        elif action == ACTION_ACKNOWLEDGE:
            return  # the delayed shipment is already scheduled to arrive; nothing to redo
        else:
            raise ValueError(f"unknown action {action!r}")

    def _start_payment(self, oid: str, attempt: int, force: bool) -> None:
        """Begin (or, for a manual settlement, resume) the payment step. A second
        approval for an order already being paid is a no-op, which keeps a duplicate
        approval from ever double-charging."""
        run = self.orders[oid]
        if run.settled or (run.paying and not force):
            return
        run.paying = True
        self.schedule(self.now + self.a.minutes("payment_processing"), "on_payment_attempt", oid, attempt, force)

    def on_payment_attempt(self, oid: str, attempt: int, force: bool) -> None:
        run = self.orders[oid]
        if run.settled:
            return
        run.payment_attempts = attempt
        amount = run.invoices[run.primary_invoice or ""]
        max_attempts = self.scenario.retry_policy["max_attempts"]
        if not force and attempt <= run.spec.faults.payment_failures:
            self.emit(oid, A.CUSTOMER, A.INVOICE_PAYMENT_SERVICE, E.PAYMENT_ATTEMPTED, S.FAILED,
                      {"attempt": attempt, "amount_cents": amount, "reason": "synthetic_gateway_decline"})
            run.exceptions += 1
            kind = KIND_RETRIES_EXHAUSTED if attempt >= max_attempts else KIND_PAYMENT_FAILED
            self.handle_exception(oid, ExceptionCase(oid, kind, run.primary_invoice or "", attempt, 0, amount, run.spec.total_cents))
            return
        self.emit(oid, A.CUSTOMER, A.INVOICE_PAYMENT_SERVICE, E.PAYMENT_ATTEMPTED, S.OK,
                  {"attempt": attempt, "amount_cents": amount, "manual_settlement": force})
        run.settled = True
        self.emit(oid, A.INVOICE_PAYMENT_SERVICE, A.RETAILER, E.SETTLED, S.OK, {
            "invoice_id": run.primary_invoice, "amount_cents": amount,
            "payer_account": run.spec.customer_id, "payee_account": RETAILER_ACCOUNT,
        })
        self.schedule(self.now + self.a.minutes("settlement_clearing"), "on_report", oid)
