from __future__ import annotations

from dataclasses import replace

import pytest

from business_flow_simulator.engine import SimulationResult
from business_flow_simulator.events import Event, EventStatus, EventType
from business_flow_simulator.metrics import compute_kpis
from business_flow_simulator.outputs import event_log_text
from business_flow_simulator.policies import POLICY_NAMES
from business_flow_simulator.scenario import list_scenarios, load_scenario
from business_flow_simulator.schemas import validate_against
from business_flow_simulator.simulator import run_simulation
from business_flow_simulator.workload import generate_workload
from tests.conftest import clean_faults, with_faults


def events_of(result: SimulationResult, oid: str, event_type: EventType | None = None) -> list[Event]:
    return [e for e in result.events if e.correlation_id == oid and (event_type is None or e.event_type == event_type.value)]


@pytest.mark.parametrize("scenario_name", sorted(list_scenarios()))
def test_every_policy_runs_every_scenario_and_conserves(scenario_name, assumptions):
    scenario = load_scenario(scenario_name)
    workload = generate_workload(scenario)
    for policy in POLICY_NAMES:
        result = run_simulation(scenario, policy, workload=workload, assumptions=assumptions)
        kpis = compute_kpis(result)
        assert result.inventory_conserved and result.cash_conserved
        assert kpis["completed_orders"] > 0 and kpis["total_orders"] == len(workload.orders)
        assert kpis["completed_orders"] + kpis["cancelled_orders"] + kpis["incomplete_orders"] == kpis["total_orders"]
        assert all(e.t <= scenario.horizon_minutes for e in result.events)
        validate_against("kpi", kpis)


def test_same_seed_byte_identical_log_and_different_seed_differs(baseline, assumptions):
    small = baseline.with_orders(20)
    a = run_simulation(small, "manual", assumptions=assumptions)
    b = run_simulation(small, "manual", assumptions=assumptions)
    assert event_log_text(a.events) == event_log_text(b.events)
    assert compute_kpis(a) == compute_kpis(b)
    c = run_simulation(small.with_seed(43), "manual", assumptions=assumptions)
    assert event_log_text(c.events) != event_log_text(a.events)


def test_versions_are_contiguous_and_events_validate(small_scenario, small_workload, assumptions):
    result = run_simulation(small_scenario, "rules_automation", workload=small_workload, assumptions=assumptions)
    seen: dict[str, int] = {}
    for e in result.events:
        assert e.version == seen.get(e.correlation_id, 0) + 1
        seen[e.correlation_id] = e.version
        validate_against("event", e.to_dict())
    ids = [e.id for e in result.events]
    assert len(ids) == len(set(ids))


def test_processing_cost_is_sum_of_event_costs_and_cycle_times_match_events(small_scenario, small_workload, assumptions):
    result = run_simulation(small_scenario, "manual", workload=small_workload, assumptions=assumptions)
    assert result.processing_cost_cents == sum(int(e.payload["cost_cents"]) for e in result.events)
    for rec in result.orders:
        if rec.completed:
            placed = events_of(result, rec.order_id, EventType.PURCHASE_ORDER_PLACED)[0]
            reported = events_of(result, rec.order_id, EventType.REPORTED)[0]
            assert rec.cycle_minutes == reported.t - placed.t == reported.payload["cycle_minutes"]


def test_failed_payment_recovers_via_retry_under_rules(small_scenario, small_workload, assumptions):
    wl = with_faults(clean_faults(small_workload), 0, payment_failures=1)
    oid = wl.orders[0].order_id
    result = run_simulation(small_scenario, "rules_automation", workload=wl, assumptions=assumptions)
    attempts = events_of(result, oid, EventType.PAYMENT_ATTEMPTED)
    assert [a.status for a in attempts] == [EventStatus.FAILED.value, EventStatus.OK.value]
    retry = events_of(result, oid, EventType.PAYMENT_RETRY_SCHEDULED)
    assert len(retry) == 1 and retry[0].payload["backoff_minutes"] == small_scenario.retry_policy["base_backoff_minutes"]
    assert attempts[1].t - attempts[0].t == retry[0].payload["backoff_minutes"]
    assert len(events_of(result, oid, EventType.SETTLED)) == 1
    assert len(events_of(result, oid, EventType.REVIEW_ENQUEUED)) == 0
    assert result.cash_conserved and any(r.order_id == oid and r.completed for r in result.orders)


def test_exhausted_retries_escalate_to_review_then_settle_exactly_once(small_scenario, small_workload, assumptions):
    max_attempts = small_scenario.retry_policy["max_attempts"]
    wl = with_faults(clean_faults(small_workload), 0, payment_failures=max_attempts + 2)
    oid = wl.orders[0].order_id
    for policy in POLICY_NAMES:
        result = run_simulation(small_scenario, policy, workload=wl, assumptions=assumptions)
        failed = [a for a in events_of(result, oid, EventType.PAYMENT_ATTEMPTED) if a.status == EventStatus.FAILED.value]
        assert len(failed) == max_attempts
        reviews = events_of(result, oid, EventType.REVIEW_ENQUEUED)
        assert any(r.payload["kind"] == "retries_exhausted" for r in reviews)
        settled = events_of(result, oid, EventType.SETTLED)
        assert len(settled) == 1 and settled[0].payload["amount_cents"] == wl.orders[0].total_cents
        ok = [a for a in events_of(result, oid, EventType.PAYMENT_ATTEMPTED) if a.status == EventStatus.OK.value]
        assert len(ok) == 1 and ok[0].payload["manual_settlement"] is True
        assert result.cash_conserved


def test_cancellation_compensation_restores_stock_and_no_shipment(small_scenario, small_workload, assumptions):
    ack = assumptions.minutes("po_acknowledge")
    wl = with_faults(clean_faults(small_workload), 0, cancel_after_minutes=ack + 10)
    oid = wl.orders[0].order_id
    result = run_simulation(small_scenario, "manual", workload=wl, assumptions=assumptions)
    assert events_of(result, oid, EventType.INVENTORY_RESERVED)
    assert not events_of(result, oid, EventType.SHIPMENT_DISPATCHED)
    cancelled = events_of(result, oid, EventType.ORDER_CANCELLED)
    comp = events_of(result, oid, EventType.COMPENSATION_APPLIED)
    assert len(cancelled) == 1 and len(comp) == 1 and comp[0].payload["kind"] == "release_reservation"
    released = {line["sku"]: line["qty"] for line in comp[0].payload["lines"]}
    assert released == {line.sku: line.qty for line in wl.orders[0].lines}
    assert result.inventory_conserved
    rec = next(r for r in result.orders if r.order_id == oid)
    assert rec.cancelled and not rec.completed
    # cancellations after dispatch are ignored: no event at all
    late = with_faults(clean_faults(small_workload), 0, cancel_after_minutes=ack + assumptions.minutes("pick_pack") + 5)
    late_result = run_simulation(small_scenario, "manual", workload=late, assumptions=assumptions)
    assert not events_of(late_result, oid, EventType.ORDER_CANCELLED)


def test_duplicate_invoice_is_detected_rejected_and_paid_once(small_scenario, small_workload, assumptions):
    wl = with_faults(clean_faults(small_workload), 1, duplicate_invoice=True)
    oid = wl.orders[1].order_id
    for policy, expect_review in (("rules_automation", 0), ("manual", 1)):
        result = run_simulation(small_scenario, policy, workload=wl, assumptions=assumptions)
        invoices = events_of(result, oid, EventType.INVOICE_ISSUED)
        assert len(invoices) == 2 and invoices[1].payload["duplicate_of"] == invoices[0].payload["invoice_id"]
        matches = events_of(result, oid, EventType.THREE_WAY_MATCH)
        assert [m.payload["result"] for m in matches] == ["matched", "duplicate_invoice"]
        rejected = events_of(result, oid, EventType.INVOICE_REJECTED)
        assert len(rejected) == 1 and rejected[0].payload["invoice_id"] == invoices[1].payload["invoice_id"]
        assert len(events_of(result, oid, EventType.REVIEW_ENQUEUED)) == expect_review
        assert len(events_of(result, oid, EventType.SETTLED)) == 1
        assert result.duplicate_invoices_detected == 1 and result.cash_conserved


def test_replayed_event_id_is_ignored_and_does_not_double_charge(small_scenario, small_workload, assumptions):
    wl = with_faults(clean_faults(small_workload), 2, replay_same_id=True)
    oid = wl.orders[2].order_id
    result = run_simulation(small_scenario, "rules_automation", workload=wl, assumptions=assumptions)
    assert result.replayed_event_ids == 1 and result.store_counters.duplicates_ignored == 1
    assert len(events_of(result, oid, EventType.INVOICE_ISSUED)) == 1
    assert len(events_of(result, oid, EventType.SETTLED)) == 1
    assert result.cash_conserved
    clean = run_simulation(small_scenario, "rules_automation", workload=clean_faults(small_workload), assumptions=assumptions)
    assert [e.event_type for e in events_of(result, oid)] == [e.event_type for e in events_of(clean, oid)]
    assert compute_kpis(result)["duplicate_event_ids_ignored"] == 1


def test_acceptance_delayed_shipment_changes_state_queue_depth_and_cash_timing(small_scenario, small_workload, assumptions):
    """Same workload, same seed, same policy; the only difference is one injected delay."""
    delay = 2880
    base_wl = clean_faults(small_workload)
    delayed_wl = with_faults(base_wl, 0, shipment_delay_minutes=delay)
    oid = base_wl.orders[0].order_id
    control = run_simulation(small_scenario, "manual", workload=base_wl, assumptions=assumptions)
    treated = run_simulation(small_scenario, "manual", workload=delayed_wl, assumptions=assumptions)
    # state: a shipment_delayed event exists only in the treated run and the order stays in fulfillment longer
    assert not events_of(control, oid, EventType.SHIPMENT_DELAYED)
    delayed_ev = events_of(treated, oid, EventType.SHIPMENT_DELAYED)
    assert len(delayed_ev) == 1 and delayed_ev[0].state == "fulfillment" and delayed_ev[0].status == "delayed"
    arrive_c = events_of(control, oid, EventType.SHIPMENT_ARRIVED)[0].t
    arrive_t = events_of(treated, oid, EventType.SHIPMENT_ARRIVED)[0].t
    assert arrive_t - arrive_c == delay
    # queue depth: the delay raises a review item under the manual policy
    assert len(events_of(treated, oid, EventType.REVIEW_ENQUEUED)) == len(events_of(control, oid, EventType.REVIEW_ENQUEUED)) + 1
    assert treated.review_tickets == control.review_tickets + 1
    assert max(d for _, d in treated.backlog_series) >= max(d for _, d in control.backlog_series)
    # cash timing: settlement of the affected order moves by exactly the delay; other orders unchanged
    settle_c = events_of(control, oid, EventType.SETTLED)[0].t
    settle_t = events_of(treated, oid, EventType.SETTLED)[0].t
    assert settle_t - settle_c == delay
    other = base_wl.orders[1].order_id
    assert events_of(control, other, EventType.SETTLED)[0].t == events_of(treated, other, EventType.SETTLED)[0].t
    assert compute_kpis(treated)["cycle_time_p95_minutes"] > compute_kpis(control)["cycle_time_p95_minutes"]


def test_partial_fulfillment_backorders_then_completes(baseline, assumptions):
    thin = replace(baseline, workload={**baseline.workload, "initial_stock_per_sku": 15, "reorder_point": 10,
                                       "reorder_qty": 500, "orders": 6, "min_qty_per_line": 10, "max_qty_per_line": 20})
    wl = clean_faults(generate_workload(thin))
    result = run_simulation(thin, "rules_automation", workload=wl, assumptions=assumptions)
    partial = [e for e in result.events if e.event_type == EventType.INVENTORY_RESERVED.value and e.status == "partial"]
    assert partial and result.stockout_count > 0 and result.replenishments > 0
    kpis = compute_kpis(result)
    assert kpis["partial_shipment_orders"] > 0 and kpis["completed_orders"] == 6
    assert result.inventory_conserved and result.cash_conserved
    for line in partial[0].payload["lines"]:
        assert line["reserved"] + line["backordered"] == line["requested"]


def test_capacity_limited_queue_builds_backlog_and_respects_capacity(assumptions):
    scenario = load_scenario("failed_payment_step")
    workload = generate_workload(scenario)
    manual = run_simulation(scenario, "manual", workload=workload, assumptions=assumptions)
    capped = run_simulation(scenario, "capacity_limited_review", workload=workload, assumptions=assumptions)
    assert capped.review_tickets == manual.review_tickets
    assert max(d for _, d in capped.backlog_series) > max(d for _, d in manual.backlog_series)
    period, cap = assumptions.review["period_minutes"], assumptions.review["capacity_per_period"]
    starts: dict[int, int] = {}
    for e in capped.events:
        if e.event_type == EventType.REVIEW_RESOLVED.value:
            start = e.t - assumptions.minutes("manual_review")
            starts[start // period] = starts.get(start // period, 0) + 1
    assert starts and max(starts.values()) <= cap


def test_short_horizon_leaves_orders_incomplete_not_fabricated(small_scenario, small_workload, assumptions):
    short = replace(small_scenario, horizon_minutes=3000)
    result = run_simulation(short, "manual", workload=small_workload, assumptions=assumptions)
    kpis = compute_kpis(result)
    assert kpis["completed_orders"] == 0 and kpis["incomplete_orders"] > 0
    assert all(e.t <= 3000 for e in result.events)
    assert result.inventory_conserved and result.cash_conserved
