from __future__ import annotations

import json

import pytest
import yaml

from business_flow_simulator.cli import main
from business_flow_simulator.figures import backlog_svg, workflow_svg
from business_flow_simulator.manifest import build_manifest, configuration_hash
from business_flow_simulator.metrics import KPI_COLUMNS, compute_kpis, kpi_table, kpis_from_events
from business_flow_simulator.outputs import event_log_text, read_event_log, write_event_log
from business_flow_simulator.replay import replay_for_scenario
from business_flow_simulator.schemas import SchemaError, validate, validate_against
from business_flow_simulator.simulator import run_simulation
from business_flow_simulator.state_machine import HAPPY_PATH


def test_replay_shape_schema_and_size(baseline, assumptions):
    replay = replay_for_scenario(baseline, "rules_automation", assumptions)
    validate_against("replay", replay)
    assert replay["schemaVersion"] == "1" and replay["mode"] == "synthetic-demo" and replay["scenarioId"] == "baseline"
    node_ids = {n["id"] for n in replay["nodes"]}
    edge_ends = {e["from"] for e in replay["edges"]} | {e["to"] for e in replay["edges"]}
    assert len(node_ids) == 7 and edge_ends <= node_ids and {"customer", "retailer", "warehouse"} <= edge_ends
    assert 100 <= len(replay["events"]) <= 150
    assert set(replay["events"][0]) == {"t", "id", "correlationId", "from", "to", "state", "status"}
    assert [e["t"] for e in replay["events"]] == sorted(e["t"] for e in replay["events"])


def test_kpi_row_validates_and_table_has_contract_columns(small_scenario, small_workload, assumptions):
    result = run_simulation(small_scenario, "manual", workload=small_workload, assumptions=assumptions)
    row = compute_kpis(result)
    validate_against("kpi", row)
    table = kpi_table([row])
    assert list(table.columns) == list(KPI_COLUMNS) and len(table) == 1
    with pytest.raises(ValueError, match="missing columns"):
        kpi_table([{"scenario_id": "x"}])
    with pytest.raises(SchemaError):
        validate_against("kpi", {**row, "evidence_label": "reproduced"})


def test_manifest_builds_validates_and_rejects_bad_mode():
    h = configuration_hash({"a": 1}, {"b": 2})
    m = build_manifest(mode="smoke", status="completed", started_at="2026-09-27T00:00:00Z", finished_at="2026-09-27T00:00:01Z",
                       seed=42, config_hash=h, data_hash=h, sample_counts={"orders": 1}, metrics_file=None)
    validate_against("run_manifest", m)
    assert m["git_commit"] is None and m["evidence_status"] == "demo"
    with pytest.raises(ValueError):
        build_manifest(mode="train", status="completed", started_at="x", finished_at="y", seed=1,
                       config_hash=h, data_hash=h, sample_counts={}, metrics_file=None)


def test_event_log_round_trip_is_byte_identical(tmp_path, small_scenario, small_workload, assumptions):
    result = run_simulation(small_scenario, "rules_automation", workload=small_workload, assumptions=assumptions)
    path = write_event_log(result.events, tmp_path / "log.json")
    again = read_event_log(path)
    assert again == result.events
    assert event_log_text(again) == path.read_text(encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))[0]["id"] == result.events[0].id


def test_schema_validator_reports_paths():
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer", "minimum": 1},
              "b": {"type": "array", "items": {"enum": ["x"]}}}, "additionalProperties": False}
    validate({"a": 1, "b": ["x"]}, schema)
    with pytest.raises(SchemaError, match=r"\$\.a"):
        validate({"a": 0}, schema)
    with pytest.raises(SchemaError, match=r"\$\.b\[1\]"):
        validate({"a": 1, "b": ["x", "y"]}, schema)
    with pytest.raises(SchemaError, match="unexpected"):
        validate({"a": 1, "z": 2}, schema)
    with pytest.raises(SchemaError):
        validate({"a": True}, schema)


def test_cli_smoke_writes_validated_outputs(tmp_path, capsys):
    out = tmp_path / "smoke"
    assert main(["smoke", "--out", str(out)]) == 0
    assert (out / "event_log_baseline_rules_automation.json").is_file()
    assert (out / "kpi_baseline_rules_automation.json").is_file()
    assert (out / "replay_smoke.json").is_file()
    manifest = yaml.safe_load((out / "run_manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["mode"] == "smoke" and manifest["status"] == "completed"
    assert "smoke ok" in capsys.readouterr().out


def test_cli_run_and_compare_and_failure_exit_codes(tmp_path, capsys):
    assert main(["run", "--scenario", "delayed_shipment", "--policy", "manual", "--seed", "3", "--out", str(tmp_path / "r")]) == 0
    assert (tmp_path / "r" / "event_log_delayed_shipment_manual.json").is_file()
    assert main(["compare", "--scenario", "baseline", "--out", str(tmp_path / "c")]) == 0
    comparison = json.loads((tmp_path / "c" / "comparison_baseline.json").read_text(encoding="utf-8"))
    validate_against("comparison", comparison)
    assert set(comparison["policies"]) == {"manual", "rules_automation", "capacity_limited_review"}
    assert main(["run", "--scenario", "nope", "--policy", "manual", "--out", str(tmp_path / "x")]) == 1
    assert "Known scenarios" in capsys.readouterr().err
    assert main(["evaluate", "--events", str(tmp_path / "missing.json")]) == 2


def test_cli_export_import_round_trip(tmp_path, capsys):
    assert main(["export-scenario", "--scenario", "capacity_crunch", "--seed", "9"]) == 0
    text = capsys.readouterr().out.strip()
    out = tmp_path / "decoded.yaml"
    assert main(["import-scenario", "--string", text, "--out", str(out)]) == 0
    decoded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert decoded["scenario_id"] == "capacity_crunch" and decoded["seed"] == 9
    assert main(["import-scenario", "--string", "bfs1.garbage"]) == 1


def test_evaluate_from_saved_log_agrees_with_live_kpis(tmp_path, small_scenario, small_workload, assumptions):
    result = run_simulation(small_scenario, "manual", workload=small_workload, assumptions=assumptions)
    path = write_event_log(result.events, tmp_path / "log.json")
    live, replayed = compute_kpis(result), kpis_from_events(read_event_log(path))
    for key in ("total_orders", "completed_orders", "cycle_time_median_minutes", "cycle_time_p95_minutes",
                "processing_cost_cents", "events_total"):
        assert replayed[key] == live[key]
    assert main(["evaluate", "--events", str(path), "--out", str(tmp_path / "k.json")]) == 0
    assert json.loads((tmp_path / "k.json").read_text(encoding="utf-8"))["evidence_label"] == "demo"


def test_figures_render_states_actors_and_policies():
    svg = workflow_svg()
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    for state in HAPPY_PATH:
        assert state.value in svg
    for actor in ("supplier", "manufacturer", "warehouse", "retailer", "customer", "review queue"):
        assert actor in svg
    chart = backlog_svg({"manual": [[0, 0], [480, 3]], "rules_automation": [[0, 0], [480, 1]]}, "baseline", 42)
    assert "manual" in chart and "rules_automation" in chart and "polyline" in chart and "not a benchmark" in chart
