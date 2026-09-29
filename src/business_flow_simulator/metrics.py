"""KPI computation from a simulation result or from a saved event log. Every number is
a property of the synthetic run it was computed from; nothing here is a benchmark."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from business_flow_simulator.engine import SimulationResult
from business_flow_simulator.events import Event, EventStatus, EventType

KPI_COLUMNS: tuple[str, ...] = (
    "scenario_id", "policy", "seed", "evidence_label", "total_orders", "completed_orders",
    "cancelled_orders", "incomplete_orders", "cycle_time_median_minutes", "cycle_time_p95_minutes",
    "exception_rate", "exceptions_total", "review_items", "auto_resolutions", "escalations",
    "review_backlog_max", "review_backlog_mean", "review_backlog_final", "stockout_count",
    "replenishments", "partial_shipment_orders", "duplicate_invoices_detected",
    "duplicate_event_ids_ignored", "processing_cost_cents", "events_total",
    "inventory_conserved", "cash_conserved",
)


def _percentile(values: list[int], q: float) -> float | None:
    if not values:
        return None
    return round(float(np.percentile(np.asarray(values, dtype=float), q)), 1)


def compute_kpis(result: SimulationResult) -> dict[str, Any]:
    cycles = [o.cycle_minutes for o in result.orders if o.cycle_minutes is not None]
    total = len(result.orders)
    completed = sum(1 for o in result.orders if o.completed)
    cancelled = sum(1 for o in result.orders if o.cancelled)
    with_exceptions = sum(1 for o in result.orders if o.exceptions > 0)
    depths = [d for _, d in result.backlog_series]
    return {
        "scenario_id": result.scenario_id,
        "policy": result.policy,
        "seed": result.seed,
        "evidence_label": "demo",
        "total_orders": total,
        "completed_orders": completed,
        "cancelled_orders": cancelled,
        "incomplete_orders": total - completed - cancelled,
        "cycle_time_median_minutes": _percentile(cycles, 50),
        "cycle_time_p95_minutes": _percentile(cycles, 95),
        "exception_rate": round(with_exceptions / total, 4) if total else None,
        "exceptions_total": sum(o.exceptions for o in result.orders),
        "review_items": result.review_tickets,
        "auto_resolutions": result.auto_resolutions,
        "escalations": result.escalations,
        "review_backlog_max": max(depths) if depths else 0,
        "review_backlog_mean": round(float(np.mean(depths)), 2) if depths else 0.0,
        "review_backlog_final": depths[-1] if depths else 0,
        "stockout_count": result.stockout_count,
        "replenishments": result.replenishments,
        "partial_shipment_orders": sum(1 for o in result.orders if o.shipments > 1),
        "duplicate_invoices_detected": result.duplicate_invoices_detected,
        "duplicate_event_ids_ignored": result.replayed_event_ids,
        "processing_cost_cents": result.processing_cost_cents,
        "events_total": len(result.events),
        "inventory_conserved": result.inventory_conserved,
        "cash_conserved": result.cash_conserved,
    }


def kpi_table(rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        return pd.DataFrame(columns=list(KPI_COLUMNS))
    missing = [c for c in KPI_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"kpi rows missing columns {missing}")
    return frame[list(KPI_COLUMNS)]


def kpis_from_events(events: Iterable[Event]) -> dict[str, Any]:
    """Recompute the KPIs that a saved event log alone can support. Cost is summed from
    the per-event ``cost_cents`` payload field the engine writes."""
    evs = list(events)
    placed: dict[str, int] = {}
    reported: dict[str, int] = {}
    exceptions: dict[str, int] = {}
    cost = 0
    for e in evs:
        cost += int(e.payload.get("cost_cents", 0))
        if e.event_type == EventType.PURCHASE_ORDER_PLACED.value:
            placed[e.correlation_id] = e.t
        elif e.event_type == EventType.REPORTED.value:
            reported[e.correlation_id] = e.t
        if e.status in (EventStatus.EXCEPTION.value, EventStatus.FAILED.value):
            exceptions[e.correlation_id] = exceptions.get(e.correlation_id, 0) + 1
    cycles = [reported[o] - placed[o] for o in reported if o in placed]
    total = len(placed)
    return {
        "total_orders": total,
        "completed_orders": len(reported),
        "cycle_time_median_minutes": _percentile(cycles, 50),
        "cycle_time_p95_minutes": _percentile(cycles, 95),
        "exception_rate": round(sum(1 for o in placed if exceptions.get(o, 0) > 0) / total, 4) if total else None,
        "exceptions_total": sum(exceptions.values()),
        "processing_cost_cents": cost,
        "events_total": len(evs),
        "evidence_label": "demo",
    }
