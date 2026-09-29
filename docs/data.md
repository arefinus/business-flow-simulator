# Data

See DATA_CARD.md for the full card. In short: there is no external data. The simulator
consumes a scenario file and produces a seeded synthetic workload; the only committed
data file is the baseline workload fixture at seed 42
(`examples/fixtures/v1/workload_baseline.json`, described in
`examples/fixtures/v1/FIXTURE.md`).

## Scenarios shipped

| Scenario | Orders | What it adds to the baseline |
|---|---|---|
| `baseline` | 60 | background price variance (6%), declined payments (4%), cancellations (3%) |
| `delayed_shipment` | 60 | 30% of first shipments delayed by 2,880 simulated minutes (two days) |
| `duplicate_invoice` | 60 | 25% of orders receive a second invoice with a new id; 20% have the original invoice event replayed with the same id |
| `failed_payment_step` | 60 | 35% of orders have at least one declined payment attempt; 60% chance each decline repeats |
| `capacity_crunch` | 160 | dense arrivals (mean gap 40 min), thin stock, 25% price variance, 15% declines, 10% duplicates, 10% one-day delays |

All five share seed 42 and a 14-day horizon (20,160 minutes). Probabilities are inputs
to the generator, not observed rates.

## Why the workload is materialised first

Policies are compared on identical input. If faults were drawn during the run, a policy
that changed the order of events would also change the random draws and the comparison
would mix two effects. Materialising every draw into the workload removes that
confound; the comparison JSON records the workload hash so this can be checked.
