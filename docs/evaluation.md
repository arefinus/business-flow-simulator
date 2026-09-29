# Evaluation

There is no model and no real data in this repository, so "evaluation" means two things:
the behaviour tests, and the demo KPI table that the simulator produces on the authored
synthetic fixture. Every number below carries the evidence label `demo`.

## Local test run (2026-09-27)

Command: `python -m pytest -q` (Python 3.10.11, Windows, numpy 1.26.4, pandas 2.3.3,
pyyaml 6.0.2, pytest 9.0.3). Real summary line from this session:

```
65 passed in 11.55s
```

65 tests in 8 files. What they cover, by file:

| File | Behaviours |
|---|---|
| `test_events_store.py` | frozen events, read-only payload, derived timestamps, dict round trip, in-order application, duplicate id ignored (listener not re-notified), out-of-order buffered until the gap closes, stale version rejected, append-only store |
| `test_ledger.py` | reservation, over-reservation raises, dispatch/arrival/replenishment chain conserved, settlement transfer and cash total, insufficient balance raises, replayed settlement id does not double-charge, replayed reservation id does not duplicate stock movement, compensation release and refund |
| `test_state_machine_money.py` | happy path legal, illegal transitions raise, cancellation only before invoice, every event type maps to a state, money rejects floats/bools, integer arithmetic |
| `test_scenario_workload.py` | all five scenarios load and validate, unknown scenario and bad fields raise, URL string round trip for every scenario, tampered/foreign strings rejected, seeded determinism, schema and synthetic ids, dict round trip, committed fixture equals generator output |
| `test_policies_queue.py` | R1 duplicate reject, R2 tolerance boundary and R4 delay rule, R3 retry then review, manual and capacity policies agree on actions, FIFO two-reviewer queue, per-period capacity and escalation timing, invalid queue config |
| `test_simulator.py` | every policy on every scenario conserves both ledgers and validates KPIs, byte-identical logs for the same seed, contiguous versions and schema-valid events, cost equals the sum of event costs and cycle times equal event timestamps, retry recovery, exhausted retries escalate and settle once, cancellation compensation restores stock, duplicate invoice detected/rejected/paid once, replayed event id ignored with no double charge, the delayed-shipment acceptance case, partial fulfillment with backorders, capacity queue backlog and per-period limit, short horizon leaves orders incomplete |
| `test_outputs_cli.py` | replay shape/schema/size, KPI row schema and table columns, manifest schema and bad mode, event log byte-identical round trip, schema validator paths, CLI smoke/run/compare/export/import/evaluate and exit codes 0/1/2, figures contain states, actors and policies |

## Smoke run (2026-09-27)

`python -m business_flow_simulator smoke` on `examples/fixtures/v1/workload_baseline.json`
(sha256 `5ca717da28f131c10e7301ccddf98ed4d00c20fd05a87fd9bfaf2e0e68d5e932`), policy
`rules_automation`: 573 events, 60 completed orders, every event, the KPI row, the replay
file and the run manifest validated against `schemas/`, both ledgers conserved. Wall time
about 2 seconds.

## Demo KPI table (2026-09-27)

Computed by `python -m business_flow_simulator demo` on synthetic fixture v1, seed 42, not
a benchmark result. Fourteen simulated days per run; all three policies of a scenario
share one workload (hash recorded in each `comparison_<scenario>.json`). Cycle times are
simulated minutes from purchase order to reported; cost is integer cents of a fictional
USD scenario under `configs/assumptions.yaml`. Full 27-column rows in
`examples/output/kpi_report.csv`.

| scenario_id | policy | completed_orders | cycle_time_median_minutes | cycle_time_p95_minutes | exception_rate | review_items | auto_resolutions | escalations | review_backlog_max | stockout_count | processing_cost_cents |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | manual | 60 | 4416.0 | 4436.0 | 0.0667 | 4 | 0 | 0 | 0 | 1 | 11255 |
| baseline | rules_automation | 60 | 4416.0 | 4417.0 | 0.0667 | 2 | 2 | 0 | 0 | 1 | 7655 |
| baseline | capacity_limited_review | 60 | 4416.0 | 4436.0 | 0.0667 | 4 | 0 | 0 | 0 | 1 | 11255 |
| capacity_crunch | manual | 150 | 9128.0 | 15284.6 | 0.4938 | 109 | 0 | 0 | 1 | 304 | 575785 |
| capacity_crunch | rules_automation | 150 | 9118.0 | 15257.6 | 0.4938 | 37 | 72 | 0 | 0 | 304 | 446185 |
| capacity_crunch | capacity_limited_review | 141 | 8965.0 | 15331.0 | 0.4938 | 108 | 0 | 35 | 17 | 304 | 690945 |
| delayed_shipment | manual | 60 | 4416.0 | 7296.0 | 0.45 | 29 | 0 | 0 | 1 | 1 | 56505 |
| delayed_shipment | rules_automation | 60 | 4416.0 | 7296.0 | 0.45 | 27 | 2 | 0 | 1 | 1 | 52905 |
| delayed_shipment | capacity_limited_review | 60 | 4416.0 | 7296.0 | 0.45 | 29 | 0 | 0 | 1 | 1 | 56505 |
| duplicate_invoice | manual | 60 | 4416.0 | 4436.0 | 0.35 | 23 | 0 | 0 | 0 | 1 | 45835 |
| duplicate_invoice | rules_automation | 60 | 4416.0 | 4417.0 | 0.35 | 2 | 21 | 0 | 0 | 1 | 8035 |
| duplicate_invoice | capacity_limited_review | 60 | 4416.0 | 4436.0 | 0.35 | 23 | 0 | 0 | 0 | 1 | 45835 |
| failed_payment_step | manual | 58 | 4416.0 | 4841.9 | 0.3667 | 48 | 0 | 0 | 1 | 5 | 98020 |
| failed_payment_step | rules_automation | 58 | 4416.0 | 4807.9 | 0.3667 | 11 | 37 | 0 | 0 | 5 | 31420 |
| failed_payment_step | capacity_limited_review | 58 | 4416.0 | 5145.3 | 0.3667 | 48 | 0 | 0 | 4 | 5 | 98020 |

Observations, descriptive of the synthetic run only:

* The median cycle time of 4416.0 minutes is the sum of the assumed service times on the
  happy path (5 + 45 + 2880 + 15 + 1 + 30 + 1440). Policies only move the tail.
* `delayed_shipment` raises p95 from 4436.0 to 7296.0 under every policy: the delay
  (2880 minutes) lands on 30% of orders and is not something routing can remove.
* `rules_automation` reduces review items where a rule applies (duplicates: 23 to 2;
  declined payments: 48 to 11) and leaves them where none does (delays of 2880 minutes
  exceed the 1440-minute R4 tolerance, so 27 of 29 still go to a reviewer).
* `capacity_limited_review` is the only policy that leaves work unfinished at the
  horizon: in `capacity_crunch` 141 of 160 orders complete against 150 for the other two,
  with 35 escalations and a backlog peak of 17 items; in `failed_payment_step` the p95
  rises to 5145.3 with no change in completions.
* `duplicate_event_ids_ignored` (14 in `duplicate_invoice`, 8 in `capacity_crunch`) counts
  replayed invoice events that the store dropped; `cash_conserved` is true in every row,
  which is the observable consequence of that idempotency.
* Stockouts, replenishments and partial shipments are identical across policies within a
  scenario because fulfillment does not depend on exception routing.

## Figures

`docs/figures/workflow.svg` (state machine and actor flows) and
`docs/figures/review_backlog.svg` (open review items over simulated time for the three
policies on `baseline`, seed 42) are rendered by `tools/render_figures.py` from the
demo comparison file.

## What this evaluation does not show

No accuracy, no benchmark, no comparison with any published system, no real process. The
table is a property of the fixture and the assumptions; changing either changes the
numbers, which is the point of shipping the generator and the assumptions file rather
than the numbers alone.
