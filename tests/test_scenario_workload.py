from __future__ import annotations

import json
import re

import pytest

from business_flow_simulator.outputs import canonical_json, read_json
from business_flow_simulator.paths import fixtures_dir
from business_flow_simulator.scenario import (ScenarioCodecError, ScenarioError, export_scenario, import_scenario,
                                              list_scenarios, load_scenario, scenario_from_dict)
from business_flow_simulator.schemas import SchemaError, validate_against
from business_flow_simulator.workload import Workload, generate_workload

EXPECTED_SCENARIOS = {"baseline", "delayed_shipment", "duplicate_invoice", "failed_payment_step", "capacity_crunch"}


def test_all_shipped_scenarios_load_and_validate():
    assert set(list_scenarios()) == EXPECTED_SCENARIOS
    for name in list_scenarios():
        sc = load_scenario(name)
        validate_against("scenario", sc.to_dict())
        assert sc.scenario_id == name and sc.seed == 42


def test_unknown_scenario_and_bad_fields_raise():
    with pytest.raises(ScenarioError, match="Known scenarios"):
        load_scenario("does_not_exist")
    good = load_scenario("baseline").to_dict()
    bad_prob = json.loads(json.dumps(good))
    bad_prob["faults"]["price_variance"]["probability"] = 1.5
    with pytest.raises(ScenarioError, match="probability"):
        scenario_from_dict(bad_prob)
    bad_fault = json.loads(json.dumps(good))
    bad_fault["faults"]["meteor_strike"] = {"probability": 0.1}
    with pytest.raises(ScenarioError, match="unknown fault"):
        scenario_from_dict(bad_fault)
    bad_range = json.loads(json.dumps(good))
    bad_range["workload"]["min_qty_per_line"] = 99
    with pytest.raises(ScenarioError):
        scenario_from_dict(bad_range)


def test_scenario_url_string_round_trip():
    for name in list_scenarios():
        sc = load_scenario(name).with_seed(7)
        text = export_scenario(sc)
        assert text.startswith("bfs1.") and re.fullmatch(r"bfs1\.[A-Za-z0-9_-]+", text)
        assert import_scenario(text) == sc
        assert import_scenario(text).to_dict() == sc.to_dict()


def test_tampered_or_foreign_scenario_string_is_rejected():
    text = export_scenario(load_scenario("baseline"))
    body = text[5:]
    flipped = "bfs1." + body[:20] + ("A" if body[20] != "A" else "B") + body[21:]
    with pytest.raises(ScenarioCodecError):
        import_scenario(flipped)
    with pytest.raises(ScenarioCodecError):
        import_scenario("nope." + body)
    with pytest.raises(ScenarioCodecError):
        import_scenario("bfs1.%%%not-base64%%%")


def test_workload_is_deterministic_per_seed_and_differs_across_seeds():
    sc = load_scenario("baseline")
    a, b = generate_workload(sc), generate_workload(sc)
    assert canonical_json(a.to_dict()) == canonical_json(b.to_dict())
    c = generate_workload(sc.with_seed(43))
    assert canonical_json(c.to_dict()) != canonical_json(a.to_dict())
    assert len(a.orders) == sc.workload["orders"]


def test_workload_validates_and_uses_synthetic_ids_and_integer_money():
    wl = generate_workload(load_scenario("capacity_crunch"))
    data = wl.to_dict()
    validate_against("workload", data)
    for order in wl.orders:
        assert order.order_id.startswith("SYN-PO-") and order.customer_id.startswith("SYN-CUST-")
        for line in order.lines:
            assert isinstance(line.unit_price_cents, int) and isinstance(line.total_cents, int)
        assert 0 <= order.t_arrival <= 0.6 * 20160
    with pytest.raises(SchemaError):
        validate_against("workload", {**data, "label": "real"})


def test_workload_dict_round_trip():
    wl = generate_workload(load_scenario("duplicate_invoice"))
    again = Workload.from_dict(json.loads(json.dumps(wl.to_dict())))
    assert again == wl


def test_fixture_matches_generator():
    """The committed fixture must be exactly what the generator produces at seed 42."""
    on_disk = read_json(fixtures_dir() / "workload_baseline.json")
    regenerated = generate_workload(load_scenario("baseline").with_seed(42)).to_dict()
    assert canonical_json(on_disk) == canonical_json(regenerated)
    fixture_md = (fixtures_dir() / "FIXTURE.md").read_text(encoding="utf-8")
    assert "Authored synthetic demonstration data" in fixture_md and "seed 42" in fixture_md
