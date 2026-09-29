"""Replay file for the portfolio's 3D scene. Shape (schemaVersion "1"):

    {schemaVersion, scenarioId, mode: "synthetic-demo", nodes: [{id, type, label}],
     edges: [{from, to}], events: [{t, id, correlationId, from, to, state, status}]}
"""
from __future__ import annotations

from typing import Any

from business_flow_simulator.assumptions import Assumptions
from business_flow_simulator.engine import SimulationResult
from business_flow_simulator.events import ActorType
from business_flow_simulator.scenario import Scenario

REPLAY_SCHEMA_VERSION = "1"
REPLAY_MODE = "synthetic-demo"
DEFAULT_REPLAY_ORDERS = 16
DEFAULT_MAX_EVENTS = 150

NODE_LABELS: dict[str, str] = {
    ActorType.SUPPLIER.value: "Component supplier (fictional)",
    ActorType.MANUFACTURER.value: "Manufacturer (fictional)",
    ActorType.WAREHOUSE.value: "Northwind Demo Supply warehouse",
    ActorType.RETAILER.value: "Northwind Demo Supply (retailer)",
    ActorType.CUSTOMER.value: "Blue Harbor Demo Retail (customer)",
    ActorType.INVOICE_PAYMENT_SERVICE.value: "Invoice and payment service",
    ActorType.REVIEW_QUEUE.value: "Human review queue",
}


def build_replay(result: SimulationResult, max_events: int = DEFAULT_MAX_EVENTS) -> dict[str, Any]:
    events = result.events[:max_events]
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for e in result.events:
        key = (e.actor_type, e.to_actor)
        if key not in seen:
            seen.add(key)
            edges.append({"from": key[0], "to": key[1]})
    return {
        "schemaVersion": REPLAY_SCHEMA_VERSION,
        "scenarioId": result.scenario_id,
        "mode": REPLAY_MODE,
        "policy": result.policy,
        "seed": result.seed,
        "label": "synthetic",
        "nodes": [{"id": a.value, "type": a.value, "label": NODE_LABELS[a.value]} for a in ActorType],
        "edges": edges,
        "events": [
            {"t": e.t, "id": e.id, "correlationId": e.correlation_id, "from": e.actor_type,
             "to": e.to_actor, "state": e.state, "status": e.status}
            for e in events
        ],
    }


def replay_for_scenario(scenario: Scenario, policy: str, assumptions: Assumptions,
                        orders: int = DEFAULT_REPLAY_ORDERS, max_events: int = DEFAULT_MAX_EVENTS) -> dict[str, Any]:
    from business_flow_simulator.simulator import run_simulation

    small = scenario.with_orders(orders)
    result = run_simulation(small, policy, assumptions=assumptions)
    return build_replay(result, max_events=max_events)
