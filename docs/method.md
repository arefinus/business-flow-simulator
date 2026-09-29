# Method

## 1. Domain model

Seven actor types: `supplier`, `manufacturer`, `warehouse`, `retailer`, `customer`,
`invoice_payment_service`, `review_queue`. The retailer is the fictional wholesale
distributor "Northwind Demo Supply"; customers are fictional accounts such as "Blue
Harbor Demo Retail". Money is integer cents of a fictional USD scenario throughout
(`money.py` rejects floats and booleans).

Every fact is an `Event`, a frozen dataclass with `id`, `t`, `timestamp`,
`correlation_id`, `version`, `actor_type`, `to_actor`, `event_type`, `state`, `status`
and a read-only `payload`. Nothing else is persisted; the ledger and the KPIs are
projections of the event list.

## 2. Order state machine

```
purchase_order -> fulfillment -> invoice -> payment_review -> settlement -> reporting
      |               |                          ^    |
      +---------------+--> cancelled             +----+  (retry / review loop)
```

Legal moves are the table `TRANSITIONS` in `state_machine.py`; the engine calls
`assert_transition` before every state-changing event and an illegal move raises
`InvalidTransition`. `fulfillment -> fulfillment` covers partial reservations and
multiple shipments; `payment_review -> payment_review` covers retries and reviews;
`payment_review -> invoice` lets a late duplicate invoice be recorded. Events that
belong to a side stream (a duplicate invoice, its match, its rejection, a review of a
shipment delay) are emitted with `advance=False`: they carry the order's current state
and do not move it.

Fulfillment detail: the retailer reserves stock line by line. A line the warehouse
cannot cover is backordered and counted as one stockout; whatever was reserved ships as
a partial shipment; when a replenishment for that SKU arrives the waiting orders are
re-reserved in arrival order and a second shipment follows. The invoice is issued only
once the customer has received the full ordered quantity, so the three-way match
compares the purchase order (quantity and amount), the accumulated receipts (quantity)
and the invoice (amount).

Replenishment is its own correlation stream (`SYN-REPL-nnnn`): warehouse orders from the
manufacturer when on-hand stock falls to the reorder point; the supplier dispatches
components at 30% of the lead time, the manufacturer ships at 60%, stock arrives at 100%.

Cancellation and compensation: a customer cancellation fires between 5 and 60 minutes
after the order. If nothing has shipped, the order moves to `cancelled` and a
`compensation_applied` event with `kind: release_reservation` returns the reserved units
to on-hand stock. A cancellation that arrives after dispatch is ignored (no event). The
ledger also implements `return_to_stock` and `refund` compensation kinds for callers that
emit them; the shipped scenarios do not.

## 3. Event store: append-only and idempotent

`EventStore.append` returns one of four results: `applied`, `duplicate_ignored`,
`buffered`, `rejected_stale`. Listeners (the ledger) are notified only on `applied`, and
exactly once, so replaying an event id cannot double-charge cash or move stock twice.
Ordering is per correlation: `version` must equal the next expected value; a later
version is buffered and drained when the gap closes; an earlier version is rejected.
The engine asserts that every event it emits is `applied`; a fault-injected replay goes
through `Engine.replay` and is counted in `duplicate_event_ids_ignored`.

## 4. Ledger invariants

For each SKU: `initial + received == on_hand + reserved + in_transit + delivered`. For
cash: the sum over all accounts is constant (settlements and refunds transfer, never
create or destroy). Both are evaluated at the end of every run and reported in the KPI
row; the tests assert them after every scenario and after adversarial replays.

## 5. Discrete-event engine

A binary heap on `(t, sequence_number, handler, args)`. Equal times fire in scheduling
order, so the run is deterministic. The engine draws no random numbers; all randomness
is in the workload generator, seeded once. Events at `t > horizon` are never processed,
so orders still in flight at the horizon are reported as incomplete rather than
fabricated as complete.

## 6. Fault injection

All faults are drawn per order at workload generation (`FaultPlan`):

| Fault | Effect in the run | Exception kind |
|---|---|---|
| delayed shipment | `shipment_delayed` event; arrival shifted by `delay_minutes` | `shipment_delayed` |
| duplicate invoice | a second `invoice_issued` (new id, same PO) after `duplicate_invoice_gap`; match flags it | `duplicate_invoice` |
| replayed invoice event | the original `invoice_issued` event is appended again with the same id; the store ignores it | none (counted) |
| failed payment step | the first `payment_failures` attempts are declined | `payment_failed`, then `retries_exhausted` at `max_attempts` |
| price variance | invoice amount = PO amount adjusted by `price_variance_bps` | `price_variance` |
| cancellation | order cancelled before shipment; reservation released | none |

Retry policy (scenario): attempt `n` failing before `max_attempts` schedules attempt
`n+1` after `base_backoff_minutes * multiplier^(n-1)`. Failing at `max_attempts` raises
`retries_exhausted`, which every policy sends to review; the reviewer's action is
`manual_settle`, a forced successful collection.

Review escalation (assumptions): an item whose expected wait exceeds
`escalation_after_minutes` emits `review_escalated` once, at that moment, and incurs the
escalation cost. Its resolution time is unchanged.

## 7. Policies

The reviewer's decision for each exception kind is fixed (`human_resolution`): reject a
duplicate, approve a variance, retry a failed payment, settle manually after exhausted
retries, acknowledge a delay. Policies differ only in routing and capacity.

| Policy | Routing | Queue model |
|---|---|---|
| `manual` | every exception to the human queue | `reviewers_manual` continuous reviewers, FIFO, `manual_review` minutes each |
| `rules_automation` | R1 duplicate invoice: auto reject. R2 price variance within `price_variance_tolerance_bps`: auto approve. R3 failed payment with attempts left: auto retry. R4 shipment delay within `shipment_delay_tolerance_minutes`: auto acknowledge. Everything else: human queue | same as manual |
| `capacity_limited_review` | every exception to the human queue | at most `capacity_per_period` reviews may start per `period_minutes`; overflow waits for the next period with a free slot |

Costs: every event costs `automated_step`; a resolved review adds
`manual_review_per_item`; an escalation adds `escalation`; a declined payment adds
`payment_retry`; each newly backordered line adds `backorder_line_handling`. Values are
declared in `configs/assumptions.yaml` and are assumptions of the fictional scenario.

## 8. Metrics

Completed, cancelled and incomplete orders; cycle time median and p95 (purchase order to
reported, simulated minutes); exception rate (orders with at least one exception);
exceptions total; review items, auto resolutions, escalations; review backlog max, mean
and final (sampled every review period); stockouts; replenishments; partial-shipment
orders; duplicate invoices detected; duplicate event ids ignored; processing cost
(cents); events; the two conservation flags. Definitions in `docs/schema.md`.

## 9. What this method does not claim

It does not estimate return on investment, does not claim that automation causes any
business outcome, and does not calibrate to any real organisation. It describes what a
fully specified synthetic process does under three routing policies, with every
assumption written down and every number regenerable from a seed.
