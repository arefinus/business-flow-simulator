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
