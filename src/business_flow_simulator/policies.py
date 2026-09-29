"""Exception-handling policies compared on identical workloads.

* ``manual``: every exception goes to the human review queue (continuous reviewers).
* ``rules_automation``: deterministic rules resolve the cases they cover; the rest
  go to the human queue.
* ``capacity_limited_review``: same decisions as ``manual`` but the queue can only
  start a fixed number of reviews per period, so a backlog can form.

The human resolution of each exception kind is fixed (``human_resolution``) so the
policies differ only in routing and capacity, never in what a reviewer decides.
"""
from __future__ import annotations

from dataclasses import dataclass

KIND_DUPLICATE_INVOICE = "duplicate_invoice"
KIND_PRICE_VARIANCE = "price_variance"
KIND_QUANTITY_MISMATCH = "quantity_mismatch"
KIND_PAYMENT_FAILED = "payment_failed"
KIND_RETRIES_EXHAUSTED = "retries_exhausted"
KIND_SHIPMENT_DELAYED = "shipment_delayed"
EXCEPTION_KINDS = (KIND_DUPLICATE_INVOICE, KIND_PRICE_VARIANCE, KIND_QUANTITY_MISMATCH,
                   KIND_PAYMENT_FAILED, KIND_RETRIES_EXHAUSTED, KIND_SHIPMENT_DELAYED)

ACTION_APPROVE = "approve"
ACTION_REJECT_DUPLICATE = "reject_duplicate"
ACTION_RETRY = "retry"
ACTION_MANUAL_SETTLE = "manual_settle"
ACTION_ACKNOWLEDGE = "acknowledge"

ROUTE_AUTO = "auto"
ROUTE_REVIEW = "review"

QUEUE_SERVERS = "servers"
QUEUE_CAPACITY = "capacity"


@dataclass(frozen=True)
class ExceptionCase:
    order_id: str
    kind: str
    invoice_id: str = ""
    attempt: int = 0
    variance_bps: int = 0
    amount_cents: int = 0
    po_amount_cents: int = 0
    delay_minutes: int = 0


@dataclass(frozen=True)
class Thresholds:
    """Scenario and assumption values a rule may consult."""

    max_attempts: int
    price_variance_tolerance_bps: int
    shipment_delay_tolerance_minutes: int


@dataclass(frozen=True)
class Decision:
    route: str
    action: str
    reason: str


def human_resolution(case: ExceptionCase) -> str:
    """What a reviewer does with each kind of exception (identical for all policies)."""
    if case.kind == KIND_DUPLICATE_INVOICE:
        return ACTION_REJECT_DUPLICATE
    if case.kind == KIND_PAYMENT_FAILED:
        return ACTION_RETRY
    if case.kind == KIND_RETRIES_EXHAUSTED:
        return ACTION_MANUAL_SETTLE
    if case.kind == KIND_SHIPMENT_DELAYED:
        return ACTION_ACKNOWLEDGE
    return ACTION_APPROVE


class Policy:
    name: str = "base"
    queue_mode: str = QUEUE_SERVERS

    def decide(self, case: ExceptionCase, thresholds: Thresholds) -> Decision:
        raise NotImplementedError


class ManualPolicy(Policy):
    name = "manual"
    queue_mode = QUEUE_SERVERS

    def decide(self, case: ExceptionCase, thresholds: Thresholds) -> Decision:
        return Decision(ROUTE_REVIEW, human_resolution(case), "manual: every exception is reviewed")


class RulesAutomationPolicy(Policy):
    name = "rules_automation"
    queue_mode = QUEUE_SERVERS

    def decide(self, case: ExceptionCase, thresholds: Thresholds) -> Decision:
        if case.kind == KIND_DUPLICATE_INVOICE:
            return Decision(ROUTE_AUTO, ACTION_REJECT_DUPLICATE, "R1: second invoice for a matched PO is rejected")
        if case.kind == KIND_PRICE_VARIANCE and abs(case.variance_bps) <= thresholds.price_variance_tolerance_bps:
            return Decision(ROUTE_AUTO, ACTION_APPROVE,
                            f"R2: variance within {thresholds.price_variance_tolerance_bps} bps tolerance")
        if case.kind == KIND_PAYMENT_FAILED and case.attempt < thresholds.max_attempts:
            return Decision(ROUTE_AUTO, ACTION_RETRY, "R3: retry with backoff while attempts remain")
        if case.kind == KIND_SHIPMENT_DELAYED and case.delay_minutes <= thresholds.shipment_delay_tolerance_minutes:
            return Decision(ROUTE_AUTO, ACTION_ACKNOWLEDGE,
                            f"R4: carrier delay within {thresholds.shipment_delay_tolerance_minutes} min tolerance")
        return Decision(ROUTE_REVIEW, human_resolution(case), "no rule covers this case; reviewed")


class CapacityLimitedReviewPolicy(Policy):
    name = "capacity_limited_review"
    queue_mode = QUEUE_CAPACITY

    def decide(self, case: ExceptionCase, thresholds: Thresholds) -> Decision:
        return Decision(ROUTE_REVIEW, human_resolution(case), "capacity-limited: every exception is reviewed")


POLICIES: dict[str, type[Policy]] = {
    ManualPolicy.name: ManualPolicy,
    RulesAutomationPolicy.name: RulesAutomationPolicy,
    CapacityLimitedReviewPolicy.name: CapacityLimitedReviewPolicy,
}
POLICY_NAMES: tuple[str, ...] = tuple(POLICIES)


def get_policy(name: str) -> Policy:
    try:
        return POLICIES[name]()
    except KeyError as exc:
        raise ValueError(f"unknown policy {name!r}; known: {list(POLICY_NAMES)}") from exc
