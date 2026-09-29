# Reproducibility

Release 2026-09-27, version 0.1.0.

## What is reproduced, exactly

Everything in `examples/output/` and `docs/figures/` is a deterministic function of the
scenario files, `configs/assumptions.yaml`, the seed, and the code. Two runs with the
same inputs produce byte-identical event logs, KPI files, comparison JSON and replay
files. A test (`tests/test_simulator.py::test_same_seed_byte_identical_log`) enforces
this. The only non-deterministic fields anywhere are `started_at`, `finished_at` and
`run_id` in `run_manifest.yaml`, plus the Python version string.

## What is not reproduced

Nothing here reproduces a published result or a real process. There is no real-data run,
no benchmark, no model. Every metric carries the evidence label `demo`.

## Commands

```
pip install -e . && pip install pytest      # or: make setup
python -m business_flow_simulator smoke     # fixture run, schema checks, < 30 s
python -m business_flow_simulator demo      # all scenarios x all policies -> examples/output/
python -m pytest -q                         # test suite
python tools/make_fixture.py                # regenerate examples/fixtures/v1 (byte-identical)
python tools/render_figures.py              # regenerate docs/figures/*.svg
```

Individual runs:

```
python -m business_flow_simulator run --scenario delayed_shipment --policy manual --seed 42 --out build/run
python -m business_flow_simulator compare --scenario capacity_crunch --seed 7 --out build/compare
python -m business_flow_simulator export-scenario --scenario baseline
python -m business_flow_simulator import-scenario --string "bfs1...." --out build/decoded.yaml
python -m business_flow_simulator evaluate --events examples/output/event_log_baseline_rules_automation.json
```

## Seeds

Every scenario file carries `seed: 42`. `--seed` overrides it for `run`, `compare` and
`export-scenario`. The seed drives only `workload.generate_workload`; the engine itself
never draws a random number.

## Hashes

`run_manifest.yaml` records `configuration_hash` (sha256 over the scenario dict and the
assumptions dict, canonical JSON) and `data.split_manifest_hash` (sha256 over the
canonical JSON of the workload). `examples/fixtures/v1/FIXTURE.md` records the fixture's
hash; `tests/test_scenario_workload.py::test_fixture_matches_generator` fails if the
committed fixture drifts from what the generator produces.

## Environment

Python 3.10 locally; CI runs 3.10, 3.11 and 3.12 on Ubuntu. Dependencies: numpy, pandas,
pyyaml (and pytest for tests). No GPU, network, API key or model is needed for any
target.

## Known sources of platform variation

None observed. Files are written with LF newlines and ASCII-only JSON, and the manifest
is the only file with wall-clock values.
