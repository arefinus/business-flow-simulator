# Published schemas

Machine-readable versions live in `schemas/*.json` (JSON Schema 2020-12 vocabulary,
validated in-repo by `business_flow_simulator.schemas`, a small subset validator with no
third-party dependency). `python -m business_flow_simulator smoke` validates every event,
the KPI row, the replay file, the workload fixture and the run manifest against them.

## Event (`schemas/event.schema.json`)

One immutable fact. Written as a JSON array, one event per line, in
`examples/output/event_log_*.json`.

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | const 1 | |
| `id` | `SYN-EV-nnnnnnn` | globally unique; a replayed id is ignored by the store |
| `t` | integer >= 0 | simulated minutes since the fictional epoch 2026-01-05T08:00:00Z |
| `timestamp` | ISO-8601 Z | derived from `t`, never from the wall clock |
| `correlation_id` | `SYN-PO-nnnnnn` or `SYN-REPL-nnnn` | the order or replenishment this event belongs to |
| `version` | integer >= 1 | 1-based position inside the correlation stream |
| `actor_type` | enum | emitting actor: supplier, manufacturer, warehouse, retailer, customer, invoice_payment_service, review_queue |
| `to_actor` | enum | receiving actor (same enum) |
| `event_type` | enum | 22 types, listed in the schema |
| `state` | enum | order state after this event: purchase_order, fulfillment, invoice, payment_review, settlement, reporting, cancelled |
| `status` | enum | ok, partial, delayed, failed, exception, escalated, cancelled, rejected |
| `payload` | object | type-specific; always carries `cost_cents` (integer); money fields end in `_cents` |

Ordering rule enforced by the store: a version equal to the next expected one is applied;
ahead of it is buffered until the gap closes; behind it is rejected as stale; a seen `id`
is ignored regardless of version.

## Workload (`schemas/workload.schema.json`)

The materialised synthetic input. See DATA_CARD.md for the column list. `label` is the
constant `synthetic`.

## Scenario (`schemas/scenario.schema.json`)

`scenario_id`, `description`, `horizon_minutes`, `seed`, `workload` (order count, arrival
gap, line and quantity ranges, SKU count, stock, reorder point and quantity, customers,
opening balance, unit price range), `faults` (five optional blocks: `delayed_shipment`,
`duplicate_invoice`, `failed_payment_step`, `price_variance`, `cancellation`, each with a
`probability` in [0, 1] and a magnitude field) and `retry_policy` (`max_attempts`,
`base_backoff_minutes`, `multiplier`).

Export format: `bfs1.` + URL-safe base64 of zlib-compressed canonical JSON, padding
stripped. zlib's Adler-32 checksum makes a corrupted string fail to decode rather than
decode to a different scenario.

## KPI row (`schemas/kpi.schema.json`)

One row per (scenario, policy). `evidence_label` is always `demo`. Cycle times are in
simulated minutes (median and 95th percentile over completed orders, numpy linear
interpolation). `exception_rate` is the share of orders with at least one exception.
`stockout_count` counts order lines that could not be fully reserved on their first
attempt. `processing_cost_cents` is the sum of `payload.cost_cents` over all events.
`inventory_conserved` and `cash_conserved` are the two ledger invariants evaluated at the
end of the run.

## Comparison (`schemas/comparison.schema.json`)

`scenario_id`, `seed`, `workload_hash` (sha256 of the canonical workload JSON, proving the
three policies saw the same input), and per policy a `kpis` row plus `backlog_series`
(`[[t, open_review_items], ...]`, sampled every review period).

## Replay (`schemas/replay.schema.json`)

Consumed by the portfolio's 3D scene.

```
{"schemaVersion": "1", "scenarioId": "...", "mode": "synthetic-demo",
 "nodes": [{"id", "type", "label"}], "edges": [{"from", "to"}],
 "events": [{"t", "id", "correlationId", "from", "to", "state", "status"}]}
```

The demo writes about 150 events per file (16 orders, capped at 150). Extra top-level
fields `policy`, `seed` and `label: "synthetic"` are informational.

## Run manifest (`schemas/run_manifest.schema.json`)

The contract's manifest: `schema_version`, `project_id`, `run_id`, `status`, `mode`,
`evidence_status` (`demo`), `git_commit` (null until push), `data` (source id, version,
workload hash, sample counts), `configuration_hash`, `seed`, `environment`,
`metrics_file`, `predictions_file` (null; there are no predictions), timestamps.
