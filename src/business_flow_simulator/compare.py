"""Run the three policies on one identical seeded workload and assemble the
comparison document. No ROI or causal business claim is made anywhere; the output is a
description of what the synthetic simulation did under each policy."""
from __future__ import annotations

from typing import Any

from business_flow_simulator.assumptions import Assumptions
from business_flow_simulator.engine import SimulationResult
from business_flow_simulator.metrics import compute_kpis
from business_flow_simulator.policies import POLICY_NAMES
from business_flow_simulator.scenario import Scenario
from business_flow_simulator.simulator import run_simulation
from business_flow_simulator.workload import Workload, generate_workload

COMPARISON_SCHEMA_VERSION = 1


def run_all_policies(scenario: Scenario, assumptions: Assumptions,
                     workload: Workload | None = None) -> dict[str, SimulationResult]:
    wl = workload if workload is not None else generate_workload(scenario)
    return {name: run_simulation(scenario, name, workload=wl, assumptions=assumptions) for name in POLICY_NAMES}


def build_comparison(scenario: Scenario, results: dict[str, SimulationResult], workload_hash: str) -> dict[str, Any]:
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "scenario_id": scenario.scenario_id,
        "seed": scenario.seed,
        "evidence_label": "demo",
        "note": ("Identical seeded synthetic workload under three exception-handling policies. "
                 "Descriptive simulation output only; no ROI or causal business claim."),
        "workload_hash": workload_hash,
        "policies": {
            name: {
                "kpis": compute_kpis(res),
                "backlog_series": [list(pt) for pt in res.backlog_series],
            }
            for name, res in results.items()
        },
    }
