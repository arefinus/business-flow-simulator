"""Service-time and cost assumptions, loaded from ``configs/assumptions.yaml``. These
are declared inputs of a fictional scenario, not measurements."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from business_flow_simulator.money import cents
from business_flow_simulator.paths import configs_dir

REQUIRED_SERVICE_TIMES = (
    "po_acknowledge", "inventory_reservation", "pick_pack", "shipment_transit",
    "replenishment_lead", "invoice_issue", "three_way_match", "payment_processing",
    "settlement_clearing", "manual_review", "reporting", "duplicate_invoice_gap",
)
REQUIRED_COSTS = (
    "automated_step", "manual_review_per_item", "payment_retry", "escalation",
    "backorder_line_handling",
)
REQUIRED_REVIEW = ("reviewers_manual", "period_minutes", "capacity_per_period",
                   "escalation_after_minutes", "price_variance_tolerance_bps",
                   "shipment_delay_tolerance_minutes")


class AssumptionsError(ValueError):
    """Raised when the assumptions file is missing a required key or has a bad type."""


@dataclass(frozen=True)
class Assumptions:
    service_minutes: Mapping[str, int]
    costs_cents: Mapping[str, int]
    review: Mapping[str, int]
    label: str
    source_file: str

    def minutes(self, key: str) -> int:
        return int(self.service_minutes[key])

    def cost(self, key: str) -> int:
        return cents(self.costs_cents[key])

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "service_times_minutes": dict(self.service_minutes),
            "costs_cents": dict(self.costs_cents),
            "review": dict(self.review),
        }


def _require_ints(section: Mapping[str, Any], keys: tuple[str, ...], name: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in keys:
        if key not in section:
            raise AssumptionsError(f"assumptions.{name} missing key {key!r}")
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise AssumptionsError(f"assumptions.{name}.{key} must be a non-negative int, got {value!r}")
        out[key] = value
    return out


def assumptions_from_dict(data: Mapping[str, Any], source: str = "<dict>") -> Assumptions:
    for section in ("service_times_minutes", "costs_cents", "review"):
        if not isinstance(data.get(section), Mapping):
            raise AssumptionsError(f"assumptions file must contain a mapping {section!r}")
    return Assumptions(
        service_minutes=_require_ints(data["service_times_minutes"], REQUIRED_SERVICE_TIMES, "service_times_minutes"),
        costs_cents=_require_ints(data["costs_cents"], REQUIRED_COSTS, "costs_cents"),
        review=_require_ints(data["review"], REQUIRED_REVIEW, "review"),
        label=str(data.get("label", "fictional")),
        source_file=source,
    )


def load_assumptions(path: str | Path | None = None) -> Assumptions:
    p = Path(path) if path is not None else configs_dir() / "assumptions.yaml"
    if not p.is_file():
        raise AssumptionsError(f"assumptions file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return assumptions_from_dict(data, source=p.name)
