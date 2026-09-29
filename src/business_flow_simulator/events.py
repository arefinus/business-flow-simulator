"""Immutable event model. Every fact in the simulation is an ``Event``; nothing else
is persisted. Timestamps are derived from a fictional epoch plus simulated minutes so
that two runs with the same seed produce byte-identical logs."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

EPOCH = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
EVENT_SCHEMA_VERSION = 1


class ActorType(str, Enum):
    SUPPLIER = "supplier"
    MANUFACTURER = "manufacturer"
    WAREHOUSE = "warehouse"
    RETAILER = "retailer"
    CUSTOMER = "customer"
    INVOICE_PAYMENT_SERVICE = "invoice_payment_service"
    REVIEW_QUEUE = "review_queue"


class OrderState(str, Enum):
    PURCHASE_ORDER = "purchase_order"
    FULFILLMENT = "fulfillment"
    INVOICE = "invoice"
    PAYMENT_REVIEW = "payment_review"
    SETTLEMENT = "settlement"
    REPORTING = "reporting"
    CANCELLED = "cancelled"


class EventStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    DELAYED = "delayed"
    FAILED = "failed"
    EXCEPTION = "exception"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class EventType(str, Enum):
    PURCHASE_ORDER_PLACED = "purchase_order_placed"
    INVENTORY_RESERVED = "inventory_reserved"
    REPLENISHMENT_ORDERED = "replenishment_ordered"
    SUPPLY_DISPATCHED = "supply_dispatched"
    REPLENISHMENT_SHIPPED = "replenishment_shipped"
    REPLENISHMENT_ARRIVED = "replenishment_arrived"
    SHIPMENT_DISPATCHED = "shipment_dispatched"
    SHIPMENT_DELAYED = "shipment_delayed"
    SHIPMENT_ARRIVED = "shipment_arrived"
    INVOICE_ISSUED = "invoice_issued"
    THREE_WAY_MATCH = "three_way_match"
    AUTO_RESOLVED = "auto_resolved"
    REVIEW_ENQUEUED = "review_enqueued"
    REVIEW_ESCALATED = "review_escalated"
    REVIEW_RESOLVED = "review_resolved"
    INVOICE_REJECTED = "invoice_rejected"
    PAYMENT_ATTEMPTED = "payment_attempted"
    PAYMENT_RETRY_SCHEDULED = "payment_retry_scheduled"
    SETTLED = "settled"
    REPORTED = "reported"
    ORDER_CANCELLED = "order_cancelled"
    COMPENSATION_APPLIED = "compensation_applied"


def iso_from_t(t_minutes: int) -> str:
    return (EPOCH + timedelta(minutes=int(t_minutes))).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Event:
    """One immutable fact. ``version`` is the 1-based position of this event inside
    its ``correlation_id`` stream; the store uses it to detect gaps and stale replays."""

    id: str
    t: int
    correlation_id: str
    version: int
    actor_type: str
    to_actor: str
    event_type: str
    state: str
    status: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    schema_version: int = EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError(f"event version must be >= 1, got {self.version}")
        if self.t < 0:
            raise ValueError(f"event time must be >= 0, got {self.t}")
        frozen_payload = MappingProxyType(copy.deepcopy(dict(self.payload)))
        object.__setattr__(self, "payload", frozen_payload)
        if not self.timestamp:
            object.__setattr__(self, "timestamp", iso_from_t(self.t))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "t": self.t,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "version": self.version,
            "actor_type": self.actor_type,
            "to_actor": self.to_actor,
            "event_type": self.event_type,
            "state": self.state,
            "status": self.status,
            "payload": copy.deepcopy(dict(self.payload)),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Event":
        required = ("id", "t", "correlation_id", "version", "actor_type", "to_actor",
                    "event_type", "state", "status")
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"event dict missing fields: {missing}")
        return cls(
            id=str(data["id"]),
            t=int(data["t"]),
            correlation_id=str(data["correlation_id"]),
            version=int(data["version"]),
            actor_type=str(data["actor_type"]),
            to_actor=str(data["to_actor"]),
            event_type=str(data["event_type"]),
            state=str(data["state"]),
            status=str(data["status"]),
            payload=dict(data.get("payload", {})),
            timestamp=str(data.get("timestamp", "")),
            schema_version=int(data.get("schema_version", EVENT_SCHEMA_VERSION)),
        )
