"""argparse entry point: smoke, demo, run, compare, export-scenario, import-scenario,
figures, evaluate. Library modules never print; this module is the only place that
writes to stdout/stderr."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from business_flow_simulator import PROJECT_ID, __version__
from business_flow_simulator.assumptions import Assumptions, AssumptionsError, load_assumptions
from business_flow_simulator.compare import build_comparison, run_all_policies
from business_flow_simulator.engine import EngineError, SimulationResult
from business_flow_simulator.figures import render_all
from business_flow_simulator.manifest import build_manifest, configuration_hash, utc_now, write_manifest
from business_flow_simulator.metrics import compute_kpis, kpi_table, kpis_from_events
from business_flow_simulator.outputs import (canonical_json, read_event_log, read_json, sha256_bytes,
                                             write_event_log, write_json, write_text)
from business_flow_simulator.paths import fixtures_dir, output_dir, repo_root
from business_flow_simulator.policies import POLICY_NAMES
from business_flow_simulator.replay import build_replay, replay_for_scenario
from business_flow_simulator.scenario import (Scenario, ScenarioCodecError, ScenarioError, export_scenario,
                                              import_scenario, list_scenarios, load_scenario, save_scenario)
from business_flow_simulator.schemas import SchemaError, validate_against
from business_flow_simulator.simulator import run_simulation
from business_flow_simulator.workload import Workload, generate_workload

REPLAY_SCENARIOS = ("baseline", "delayed_shipment", "duplicate_invoice")
DEMO_EVENT_LOG_POLICY = "rules_automation"
EXIT_OK, EXIT_FAIL, EXIT_MISSING_INPUT = 0, 1, 2


def _workload_hash(workload: Workload) -> str:
    return sha256_bytes(canonical_json(workload.to_dict()).encode("utf-8"))


def _relative(path: str | Path | None) -> str | None:
    """Manifest paths are repo-relative (or bare names) so no machine-specific path is written."""
    if path is None:
        return None
    p = Path(path).resolve()
    try:
        return p.relative_to(repo_root()).as_posix()
    except ValueError:
        return p.name


def _manifest(mode: str, out: Path, scenario: Scenario, assumptions: Assumptions, workload: Workload,
              started: str, events: int, metrics_file: str | None) -> Path:
    manifest = build_manifest(
        mode=mode, status="completed", started_at=started, finished_at=utc_now(), seed=scenario.seed,
        config_hash=configuration_hash(scenario.to_dict(), assumptions.to_dict()),
        data_hash=_workload_hash(workload),
        sample_counts={"orders": len(workload.orders), "events": events},
        metrics_file=_relative(metrics_file),
    )
    return write_manifest(manifest, out / "run_manifest.yaml")


def _write_run(out: Path, result: SimulationResult) -> tuple[Path, Path]:
    tag = f"{result.scenario_id}_{result.policy}"
    log = write_event_log(result.events, out / f"event_log_{tag}.json")
    kpi = write_json(out / f"kpi_{tag}.json", compute_kpis(result))
    return log, kpi


def cmd_run(args: argparse.Namespace) -> int:
    started = utc_now()
    scenario = load_scenario(args.scenario)
    if args.seed is not None:
        scenario = scenario.with_seed(args.seed)
    assumptions = load_assumptions(args.assumptions)
    workload = Workload.from_dict(read_json(args.workload)) if args.workload else generate_workload(scenario)
    result = run_simulation(scenario, args.policy, workload=workload, assumptions=assumptions)
    out = Path(args.out)
    log, kpi = _write_run(out, result)
    _manifest("experiment", out, scenario, assumptions, workload, started, len(result.events), str(kpi))
    print(json.dumps({"event_log": str(log), "kpis": compute_kpis(result)}, indent=2))
    return EXIT_OK


def _compare_scenario(scenario: Scenario, assumptions: Assumptions, out: Path) -> tuple[dict[str, Any], dict[str, SimulationResult], Workload]:
    workload = generate_workload(scenario)
    results = run_all_policies(scenario, assumptions, workload)
    comparison = build_comparison(scenario, results, _workload_hash(workload))
    write_json(out / f"comparison_{scenario.scenario_id}.json", comparison)
    return comparison, results, workload


def cmd_compare(args: argparse.Namespace) -> int:
    started = utc_now()
    scenario = load_scenario(args.scenario)
    if args.seed is not None:
        scenario = scenario.with_seed(args.seed)
    assumptions = load_assumptions(args.assumptions)
    out = Path(args.out)
    comparison, results, workload = _compare_scenario(scenario, assumptions, out)
    table = kpi_table([r["kpis"] for r in comparison["policies"].values()])
    csv_path = out / f"kpi_report_{scenario.scenario_id}.csv"
    write_text(csv_path, table.to_csv(index=False, lineterminator="\n"))
    total_events = sum(len(r.events) for r in results.values())
    _manifest("experiment", out, scenario, assumptions, workload, started, total_events, str(csv_path))
    print(table.to_string(index=False))
    return EXIT_OK


def _kpi_markdown(table: Any) -> str:
    cols = ["scenario_id", "policy", "completed_orders", "cycle_time_median_minutes", "cycle_time_p95_minutes",
            "exception_rate", "review_items", "auto_resolutions", "escalations", "review_backlog_max",
            "stockout_count", "processing_cost_cents"]
    head = "| " + " | ".join(cols) + " |\n|" + "|".join(["---"] * len(cols)) + "|\n"
    rows = "".join("| " + " | ".join(str(r[c]) for c in cols) + " |\n" for _, r in table[cols].iterrows())
    return head + rows


def cmd_demo(args: argparse.Namespace) -> int:
    started = utc_now()
    assumptions = load_assumptions(args.assumptions)
    out = Path(args.out)
    rows: list[dict[str, Any]] = []
    total_events = 0
    baseline_comparison: dict[str, Any] | None = None
    baseline_workload: Workload | None = None
    for name in list_scenarios():
        scenario = load_scenario(name)
        comparison, results, workload = _compare_scenario(scenario, assumptions, out)
        rows.extend(r["kpis"] for r in comparison["policies"].values())
        total_events += sum(len(r.events) for r in results.values())
        if name == "baseline":
            baseline_comparison, baseline_workload = comparison, workload
            _write_run(out, results[DEMO_EVENT_LOG_POLICY])
            write_text(out / "scenario_baseline.url.txt", export_scenario(scenario) + "\n")
    table = kpi_table(rows)
    csv_path = write_text(out / "kpi_report.csv", table.to_csv(index=False, lineterminator="\n"))
    write_text(out / "kpi_report.md", _kpi_markdown(table))
    for name in REPLAY_SCENARIOS:
        replay = replay_for_scenario(load_scenario(name), DEMO_EVENT_LOG_POLICY, assumptions)
        validate_against("replay", replay)
        write_json(out / f"replay_{name}.json", replay, indent=None)
    render_all(repo_root() / "docs" / "figures", baseline_comparison)
    if baseline_workload is None or baseline_comparison is None:
        raise ScenarioError("demo requires a scenario named 'baseline'")
    _manifest("demo", out, load_scenario("baseline"), assumptions, baseline_workload, started, total_events, str(csv_path))
    print(table.to_string(index=False))
    print(f"\nwrote {len(rows)} KPI rows to {csv_path}")
    return EXIT_OK


def cmd_smoke(args: argparse.Namespace) -> int:
    started = utc_now()
    fixture = fixtures_dir() / "workload_baseline.json"
    if not fixture.is_file():
        raise FileNotFoundError(f"fixture missing: {fixture}. Regenerate with python tools/make_fixture.py")
    workload_dict = read_json(fixture)
    validate_against("workload", workload_dict)
    workload = Workload.from_dict(workload_dict)
    scenario = load_scenario("baseline")
    assumptions = load_assumptions(args.assumptions)
    result = run_simulation(scenario, DEMO_EVENT_LOG_POLICY, workload=workload, assumptions=assumptions)
    out = Path(args.out)
    log, kpi = _write_run(out, result)
    for event in read_json(log):
        validate_against("event", event)
    validate_against("kpi", read_json(kpi))
    replay = build_replay(result)
    validate_against("replay", replay)
    write_json(out / "replay_smoke.json", replay, indent=None)
    if not (result.inventory_conserved and result.cash_conserved):
        raise EngineError("smoke: ledger conservation violated")
    manifest_path = _manifest("smoke", out, scenario, assumptions, workload, started, len(result.events), str(kpi))
    import yaml

    validate_against("run_manifest", yaml.safe_load(manifest_path.read_text(encoding="utf-8")))
    print(f"smoke ok: {len(result.events)} events, {compute_kpis(result)['completed_orders']} completed orders, outputs in {out}")
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    if args.seed is not None:
        scenario = scenario.with_seed(args.seed)
    print(export_scenario(scenario))
    return EXIT_OK


def cmd_import(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.string
    if not text:
        raise ScenarioCodecError("provide --string or --file")
    scenario = import_scenario(text)
    if args.out:
        save_scenario(scenario, args.out)
        print(f"wrote {args.out}")
    else:
        print(json.dumps(scenario.to_dict(), indent=2))
    return EXIT_OK


def cmd_figures(args: argparse.Namespace) -> int:
    comparison = read_json(args.comparison) if args.comparison and Path(args.comparison).is_file() else None
    written = render_all(args.out, comparison)
    for p in written:
        print(f"wrote {p}")
    if comparison is None:
        print("note: no comparison file found, backlog figure skipped (run demo first)")
    return EXIT_OK


def cmd_evaluate(args: argparse.Namespace) -> int:
    p = Path(args.events)
    if not p.is_file():
        print(f"evaluate: event log not found: {p}. Run 'python -m {PROJECT_ID.replace('-', '_')} demo' first.", file=sys.stderr)
        return EXIT_MISSING_INPUT
    events = read_event_log(p)
    kpis = kpis_from_events(events)
    if args.out:
        write_json(args.out, kpis)
    print(json.dumps(kpis, indent=2))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="business_flow_simulator",
                                     description="Deterministic discrete-event simulator of a fictional B2B workflow.")
    parser.add_argument("--version", action="version", version=f"{PROJECT_ID} {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser, default_out: str) -> None:
        p.add_argument("--out", default=default_out, help="output directory")
        p.add_argument("--assumptions", default=None, help="path to assumptions.yaml (default: configs/)")

    p = sub.add_parser("smoke", help="fast offline check on the committed fixture")
    add_common(p, "build/smoke")
    p.set_defaults(func=cmd_smoke)
    p = sub.add_parser("demo", help="all scenarios x all policies, replays, figures")
    add_common(p, str(output_dir()))
    p.set_defaults(func=cmd_demo)
    p = sub.add_parser("run", help="one scenario under one policy")
    p.add_argument("--scenario", required=True)
    p.add_argument("--policy", required=True, choices=POLICY_NAMES)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--workload", default=None, help="run on a saved workload JSON instead of generating one")
    add_common(p, "build/run")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("compare", help="three policies on one identical workload")
    p.add_argument("--scenario", required=True)
    p.add_argument("--seed", type=int, default=None)
    add_common(p, "build/compare")
    p.set_defaults(func=cmd_compare)
    p = sub.add_parser("export-scenario", help="print a scenario as a compact URL-safe string")
    p.add_argument("--scenario", required=True)
    p.add_argument("--seed", type=int, default=None)
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("import-scenario", help="decode a scenario string")
    p.add_argument("--string", default=None)
    p.add_argument("--file", default=None)
    p.add_argument("--out", default=None, help="write the decoded scenario as YAML")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("figures", help="render SVG figures")
    p.add_argument("--comparison", default=str(output_dir() / "comparison_baseline.json"))
    p.add_argument("--out", default=str(repo_root() / "docs" / "figures"))
    p.set_defaults(func=cmd_figures)
    p = sub.add_parser("evaluate", help="recompute KPIs from a saved event log")
    p.add_argument("--events", default=str(output_dir() / "event_log_baseline_rules_automation.json"))
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (ScenarioError, ScenarioCodecError, AssumptionsError, SchemaError, EngineError,
            FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAIL
