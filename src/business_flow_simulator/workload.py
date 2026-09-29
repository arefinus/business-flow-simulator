"""Seeded workload generator. A workload is fully materialised (arrivals, lines, prices
and every fault draw) before any policy runs, so the three policies are compared on
identical input. IDs are visibly synthetic."""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from business_flow_simulator.money import line_total
from business_flow_simulator.scenario import Scenario

WORKLOAD_SCHEMA_VERSION = 1
NO_CANCEL = -1
CUSTOMER_LABELS = ("Blue Harbor Demo Retail", "Cedar Point Demo Stores", "Granite Row Demo Goods",
                   "Maple Bend Demo Market", "Salt Marsh Demo Outfitters", "Iron Creek Demo Hardware",
                   "Willow Gate Demo Grocers", "Copper Hill Demo Pharmacy")
RETAILER_LABEL = "Northwind Demo Supply"


@dataclass(frozen=True)
class OrderLine:
    sku: str
    qty: int
    unit_price_cents: int

    @property
    def total_cents(self) -> int:
        return line_total(self.qty, self.unit_price_cents)


@dataclass(frozen=True)
class FaultPlan:
    shipment_delay_minutes: int = 0
    duplicate_invoice: bool = False
    replay_same_id: bool = False
    payment_failures: int = 0
    price_variance_bps: int = 0
    cancel_after_minutes: int = NO_CANCEL


@dataclass(frozen=True)
class OrderSpec:
    order_id: str
    customer_id: str
    t_arrival: int
    lines: tuple[OrderLine, ...]
    faults: FaultPlan

    @property
    def total_cents(self) -> int:
        return sum(line.total_cents for line in self.lines)

    @property
    def total_qty(self) -> int:
        return sum(line.qty for line in self.lines)


@dataclass(frozen=True)
class Workload:
    scenario_id: str
    seed: int
    orders: tuple[OrderSpec, ...]
    skus: tuple[str, ...]
    initial_stock: Mapping[str, int]
    reorder_point: int
    reorder_qty: int
    customers: tuple[str, ...]
    opening_balances: Mapping[str, int]
    schema_version: int = WORKLOAD_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "label": "synthetic",
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "skus": list(self.skus),
            "initial_stock": dict(self.initial_stock),
            "reorder_point": self.reorder_point,
            "reorder_qty": self.reorder_qty,
            "customers": list(self.customers),
            "opening_balances_cents": dict(self.opening_balances),
            "orders": [
                {
                    "order_id": o.order_id,
                    "customer_id": o.customer_id,
                    "t_arrival": o.t_arrival,
                    "lines": [asdict(line) for line in o.lines],
                    "faults": asdict(o.faults),
                }
                for o in self.orders
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Workload":
        orders = tuple(
            OrderSpec(
                order_id=str(o["order_id"]),
                customer_id=str(o["customer_id"]),
                t_arrival=int(o["t_arrival"]),
                lines=tuple(OrderLine(str(l["sku"]), int(l["qty"]), int(l["unit_price_cents"])) for l in o["lines"]),
                faults=FaultPlan(**{k: int(v) if not isinstance(v, bool) else v for k, v in o["faults"].items()}),
            )
            for o in data["orders"]
        )
        return cls(
            scenario_id=str(data["scenario_id"]),
            seed=int(data["seed"]),
            orders=orders,
            skus=tuple(data["skus"]),
            initial_stock={k: int(v) for k, v in data["initial_stock"].items()},
            reorder_point=int(data["reorder_point"]),
            reorder_qty=int(data["reorder_qty"]),
            customers=tuple(data["customers"]),
            opening_balances={k: int(v) for k, v in data["opening_balances_cents"].items()},
            schema_version=int(data.get("schema_version", WORKLOAD_SCHEMA_VERSION)),
        )


def _fault(faults: Mapping[str, Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    return faults.get(name, {})


def _draw_faults(rng: random.Random, sc: Scenario) -> FaultPlan:
    f = sc.faults
    delay = 0
    ds = _fault(f, "delayed_shipment")
    if rng.random() < float(ds.get("probability", 0.0)):
        delay = int(ds.get("delay_minutes", 0))
    di = _fault(f, "duplicate_invoice")
    dup = rng.random() < float(di.get("probability", 0.0))
    replay = rng.random() < float(di.get("replay_same_id_probability", 0.0))
    fp = _fault(f, "failed_payment_step")
    failures = 0
    p_fail = float(fp.get("probability", 0.0))
    max_attempts = int(sc.retry_policy["max_attempts"])
    if rng.random() < p_fail:
        failures = 1
        while failures <= max_attempts and rng.random() < float(fp.get("repeat_probability", 0.5)):
            failures += 1
    pv = _fault(f, "price_variance")
    variance = 0
    if rng.random() < float(pv.get("probability", 0.0)):
        max_bps = int(pv.get("max_variance_bps", 0))
        variance = rng.randint(-max_bps, max_bps) if max_bps > 0 else 0
    cx = _fault(f, "cancellation")
    cancel = NO_CANCEL
    if rng.random() < float(cx.get("probability", 0.0)):
        cancel = rng.randint(5, int(cx.get("max_cancel_after_minutes", 60)))
    return FaultPlan(delay, dup, replay, failures, variance, cancel)


def generate_workload(scenario: Scenario) -> Workload:
    rng = random.Random(scenario.seed)
    wl = scenario.workload
    skus = tuple(f"SYN-SKU-{i + 1:03d}" for i in range(int(wl["skus"])))
    prices = {sku: rng.randint(int(wl["min_unit_price_cents"]), int(wl["max_unit_price_cents"])) for sku in skus}
    n_customers = min(int(wl["customers"]), len(CUSTOMER_LABELS))
    customers = tuple(f"SYN-CUST-{i + 1:02d}" for i in range(n_customers))
    opening = {c: int(wl["customer_opening_balance_cents"]) for c in customers}
    mean_gap = int(wl["arrival_mean_gap_minutes"])
    latest_arrival = max(1, int(scenario.horizon_minutes * 0.6))
    orders: list[OrderSpec] = []
    t = 0
    for i in range(int(wl["orders"])):
        t += 1 + int(rng.expovariate(1.0 / mean_gap)) if mean_gap > 0 else 1
        t = min(t, latest_arrival)
        n_lines = rng.randint(int(wl["min_items_per_order"]), int(wl["max_items_per_order"]))
        chosen = rng.sample(skus, k=min(n_lines, len(skus)))
        lines = tuple(
            OrderLine(sku, rng.randint(int(wl["min_qty_per_line"]), int(wl["max_qty_per_line"])), prices[sku])
            for sku in chosen
        )
        orders.append(OrderSpec(
            order_id=f"SYN-PO-{i + 1:06d}",
            customer_id=rng.choice(customers),
            t_arrival=t,
            lines=lines,
            faults=_draw_faults(rng, scenario),
        ))
    return Workload(
        scenario_id=scenario.scenario_id,
        seed=scenario.seed,
        orders=tuple(orders),
        skus=skus,
        initial_stock={sku: int(wl["initial_stock_per_sku"]) for sku in skus},
        reorder_point=int(wl["reorder_point"]),
        reorder_qty=int(wl["reorder_qty"]),
        customers=customers,
        opening_balances=opening,
    )
