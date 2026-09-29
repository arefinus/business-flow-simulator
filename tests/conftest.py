from __future__ import annotations

from dataclasses import replace

import pytest

from business_flow_simulator.assumptions import Assumptions, load_assumptions
from business_flow_simulator.scenario import Scenario, load_scenario
from business_flow_simulator.workload import FaultPlan, OrderSpec, Workload, generate_workload


@pytest.fixture(scope="session")
def assumptions() -> Assumptions:
    return load_assumptions()


@pytest.fixture(scope="session")
def baseline() -> Scenario:
    return load_scenario("baseline")


@pytest.fixture(scope="session")
def small_scenario(baseline: Scenario) -> Scenario:
    return baseline.with_orders(12)


@pytest.fixture(scope="session")
def small_workload(small_scenario: Scenario) -> Workload:
    return generate_workload(small_scenario)


def with_faults(workload: Workload, order_index: int, **fault_fields: object) -> Workload:
    """Return a copy of ``workload`` where one order's fault plan is overridden."""
    orders = list(workload.orders)
    spec: OrderSpec = orders[order_index]
    orders[order_index] = replace(spec, faults=replace(spec.faults, **fault_fields))
    return replace(workload, orders=tuple(orders))


def clean_faults(workload: Workload) -> Workload:
    """Return a copy of ``workload`` with every fault removed."""
    orders = tuple(replace(o, faults=FaultPlan()) for o in workload.orders)
    return replace(workload, orders=orders)
