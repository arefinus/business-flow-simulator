from __future__ import annotations

import pytest

from business_flow_simulator.policies import (ACTION_ACKNOWLEDGE, ACTION_APPROVE, ACTION_MANUAL_SETTLE,
                                              ACTION_REJECT_DUPLICATE, ACTION_RETRY, KIND_DUPLICATE_INVOICE,
                                              KIND_PAYMENT_FAILED, KIND_PRICE_VARIANCE, KIND_RETRIES_EXHAUSTED,
                                              KIND_SHIPMENT_DELAYED, POLICY_NAMES, QUEUE_CAPACITY, QUEUE_SERVERS,
                                              ROUTE_AUTO, ROUTE_REVIEW, ExceptionCase, Thresholds, get_policy)
from business_flow_simulator.review_queue import QueueError, ReviewQueue

T = Thresholds(max_attempts=3, price_variance_tolerance_bps=150, shipment_delay_tolerance_minutes=1440)


def test_rules_auto_reject_duplicate_invoice():
    d = get_policy("rules_automation").decide(ExceptionCase("o", KIND_DUPLICATE_INVOICE), T)
    assert (d.route, d.action) == (ROUTE_AUTO, ACTION_REJECT_DUPLICATE) and d.reason.startswith("R1")


def test_rules_price_variance_tolerance_boundary_and_delay_rule():
    rules = get_policy("rules_automation")
    inside = rules.decide(ExceptionCase("o", KIND_PRICE_VARIANCE, variance_bps=-150), T)
    outside = rules.decide(ExceptionCase("o", KIND_PRICE_VARIANCE, variance_bps=151), T)
    assert (inside.route, inside.action) == (ROUTE_AUTO, ACTION_APPROVE)
    assert (outside.route, outside.action) == (ROUTE_REVIEW, ACTION_APPROVE)
    short = rules.decide(ExceptionCase("o", KIND_SHIPMENT_DELAYED, delay_minutes=1440), T)
    long = rules.decide(ExceptionCase("o", KIND_SHIPMENT_DELAYED, delay_minutes=2880), T)
    assert (short.route, short.action) == (ROUTE_AUTO, ACTION_ACKNOWLEDGE)
    assert (long.route, long.action) == (ROUTE_REVIEW, ACTION_ACKNOWLEDGE)


def test_rules_retry_while_attempts_remain_then_review():
    rules = get_policy("rules_automation")
    d1 = rules.decide(ExceptionCase("o", KIND_PAYMENT_FAILED, attempt=2), T)
    d2 = rules.decide(ExceptionCase("o", KIND_RETRIES_EXHAUSTED, attempt=3), T)
    assert (d1.route, d1.action) == (ROUTE_AUTO, ACTION_RETRY)
    assert (d2.route, d2.action) == (ROUTE_REVIEW, ACTION_MANUAL_SETTLE)


def test_manual_and_capacity_policies_review_everything_with_identical_actions():
    manual, capped = get_policy("manual"), get_policy("capacity_limited_review")
    assert manual.queue_mode == QUEUE_SERVERS and capped.queue_mode == QUEUE_CAPACITY
    for kind in (KIND_DUPLICATE_INVOICE, KIND_PRICE_VARIANCE, KIND_PAYMENT_FAILED, KIND_RETRIES_EXHAUSTED, KIND_SHIPMENT_DELAYED):
        a, b = manual.decide(ExceptionCase("o", kind, attempt=1), T), capped.decide(ExceptionCase("o", kind, attempt=1), T)
        assert a.route == b.route == ROUTE_REVIEW and a.action == b.action
    assert set(POLICY_NAMES) == {"manual", "rules_automation", "capacity_limited_review"}
    with pytest.raises(ValueError, match="unknown policy"):
        get_policy("magic")


def test_servers_queue_is_fifo_over_two_reviewers():
    q = ReviewQueue(QUEUE_SERVERS, reviewers=2, service_minutes=20, period_minutes=480,
                    capacity_per_period=4, escalation_after_minutes=720)
    t1, t2, t3 = (q.enqueue(0, f"o{i}") for i in range(3))
    assert (t1.t_start, t1.t_resolved) == (0, 20)
    assert (t2.t_start, t2.t_resolved) == (0, 20)
    assert (t3.t_start, t3.t_resolved) == (20, 40)
    assert q.backlog_at(0) == 3 and q.backlog_at(20) == 1 and q.backlog_at(40) == 0
    assert all(t.t_escalated is None for t in q.tickets)


def test_capacity_queue_enforces_per_period_limit_and_escalates_long_waits():
    q = ReviewQueue(QUEUE_CAPACITY, reviewers=1, service_minutes=20, period_minutes=480,
                    capacity_per_period=2, escalation_after_minutes=400)
    tickets = [q.enqueue(10, f"o{i}") for i in range(5)]
    assert [t.slot for t in tickets] == [0, 0, 1, 1, 2]
    assert tickets[2].t_start == 480 and tickets[4].t_start == 960
    assert all(v <= 2 for v in q.periods_used().values())
    assert tickets[0].t_escalated is None and tickets[2].t_escalated == 410
    assert q.escalations() == 3
    # tickets 0-1 resolve at 30, tickets 2-3 at 500, ticket 4 at 980
    series = q.backlog_series([0, 10, 499, 500, 1000])
    assert series == ((0, 0), (10, 5), (499, 3), (500, 1), (1000, 0))


def test_invalid_queue_configuration_raises():
    with pytest.raises(QueueError):
        ReviewQueue("elastic", 1, 20, 480, 4, 720)
    with pytest.raises(QueueError):
        ReviewQueue(QUEUE_SERVERS, 0, 20, 480, 4, 720)
    with pytest.raises(QueueError):
        ReviewQueue(QUEUE_CAPACITY, 1, 20, 480, 0, 720)
