from __future__ import annotations

import dataclasses

import pytest

from business_flow_simulator.events import Event, iso_from_t
from business_flow_simulator.store import AppendResult, EventStore


def make(eid: str, version: int, cid: str = "SYN-PO-000001", t: int = 10) -> Event:
    return Event(id=eid, t=t, correlation_id=cid, version=version, actor_type="customer",
                 to_actor="retailer", event_type="purchase_order_placed", state="purchase_order",
                 status="ok", payload={"amount_cents": 1200, "lines": [{"sku": "SYN-SKU-001", "qty": 1}]})


def test_event_is_frozen():
    e = make("SYN-EV-0000001", 1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.t = 99  # type: ignore[misc]


def test_event_payload_is_read_only_and_detached_from_source():
    src = {"amount_cents": 5}
    e = Event(id="x", t=0, correlation_id="c", version=1, actor_type="customer", to_actor="retailer",
              event_type="purchase_order_placed", state="purchase_order", status="ok", payload=src)
    with pytest.raises(TypeError):
        e.payload["amount_cents"] = 6  # type: ignore[index]
    src["amount_cents"] = 7
    assert e.payload["amount_cents"] == 5


def test_timestamp_is_derived_from_simulated_time():
    e = make("SYN-EV-0000001", 1, t=90)
    assert e.timestamp == "2026-01-05T09:30:00Z" == iso_from_t(90)


def test_event_dict_round_trip_and_invalid_version():
    e = make("SYN-EV-0000001", 1)
    assert Event.from_dict(e.to_dict()) == e
    with pytest.raises(ValueError):
        make("SYN-EV-0000002", 0)
    with pytest.raises(ValueError):
        Event.from_dict({"id": "x"})


def test_store_applies_in_order_and_notifies_listener_once():
    store = EventStore()
    seen: list[str] = []
    store.subscribe(lambda ev: seen.append(ev.id))
    assert store.append(make("SYN-EV-0000001", 1)) is AppendResult.APPLIED
    assert store.append(make("SYN-EV-0000002", 2)) is AppendResult.APPLIED
    assert seen == ["SYN-EV-0000001", "SYN-EV-0000002"]
    assert len(store) == 2 and store.next_version("SYN-PO-000001") == 3


def test_duplicate_event_id_is_ignored_and_listener_not_called_again():
    store = EventStore()
    calls: list[str] = []
    store.subscribe(lambda ev: calls.append(ev.id))
    first = make("SYN-EV-0000001", 1)
    store.append(first)
    assert store.append(first) is AppendResult.DUPLICATE_IGNORED
    # same id, different content: still ignored
    assert store.append(make("SYN-EV-0000001", 2)) is AppendResult.DUPLICATE_IGNORED
    assert calls == ["SYN-EV-0000001"]
    assert store.counters().duplicates_ignored == 2
    assert len(store) == 1


def test_out_of_order_event_is_buffered_until_gap_closes():
    store = EventStore()
    applied: list[int] = []
    store.subscribe(lambda ev: applied.append(ev.version))
    assert store.append(make("SYN-EV-0000003", 3)) is AppendResult.BUFFERED
    assert store.append(make("SYN-EV-0000001", 1)) is AppendResult.APPLIED
    assert applied == [1] and store.counters().buffered_pending == 1
    assert store.append(make("SYN-EV-0000002", 2)) is AppendResult.APPLIED
    assert applied == [1, 2, 3] and store.counters().buffered_pending == 0
    # replaying the buffered event's id is still a duplicate
    assert store.append(make("SYN-EV-0000003", 3)) is AppendResult.DUPLICATE_IGNORED


def test_stale_version_is_rejected_and_never_reaches_listener():
    store = EventStore()
    applied: list[str] = []
    store.subscribe(lambda ev: applied.append(ev.id))
    store.append(make("SYN-EV-0000001", 1))
    store.append(make("SYN-EV-0000002", 2))
    assert store.append(make("SYN-EV-0000009", 1)) is AppendResult.REJECTED_STALE
    assert applied == ["SYN-EV-0000001", "SYN-EV-0000002"]
    assert store.counters().rejected_stale == 1


def test_store_is_append_only_and_streams_are_independent():
    store = EventStore()
    store.append(make("SYN-EV-0000001", 1, cid="SYN-PO-000001"))
    store.append(make("SYN-EV-0000002", 1, cid="SYN-PO-000002"))
    snapshot = store.events
    assert isinstance(snapshot, tuple) and len(snapshot) == 2
    assert not hasattr(store, "remove") and not hasattr(store, "delete")
    assert store.next_version("SYN-PO-000001") == 2 and store.next_version("SYN-PO-000002") == 2
